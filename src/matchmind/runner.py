"""End-to-end local pipeline: simulate -> analyze -> interpret -> agents -> overlays -> replay.

This is the same chain the Azure services run incrementally; here it runs in one process, which
is what the tests, the CI evals and the zero-cost *replay package* use. A replay package is a
folder of static files (no backend, no model calls at view time) that the web app plays back
with the same overlay renderer it uses for a live match.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from .agents import producer, templates
from .agents import recap as recap_writer
from .agents.llm import HEADLINE_SALIENCE, MUST_SHOW, Faults, make_chat_client
from .agents.store import InMemoryMomentStore
from .agents.team import AgentSettings, AgentTeam
from .agents.verify import Registry
from .agents.workflow import Batch, BeatResult, WorkflowDeps, build_workflow, run_batch
from .analytics import load_models
from .analytics.report import MatchAnalytics
from .analytics.season import context_for, load_season, radars, team_radars
from .core.contracts import SUPPORTED_LANGUAGES, Cohort, Overlay
from .core.paths import league_dir
from .intel.baselines import load_baselines
from .intel.pipeline import interpret_match
from .intel.recap import build_pack, build_preview_pack
from .intel.xt import XTGrid
from .tracking import bundle
from .tracking.analyzer import analyze_match

BATCH_WINDOW_MS = 60_000
STORY_BUDGET_PER_10_MIN = 3
REPLAY_VERSION = "2"


def health_variants() -> dict[str, Faults]:
    """Recorded model-health scenarios shipped with every package (the healthy run is the main one)."""
    return {
        # Every other model call returns text with an invented number: the Verifier catches it and the
        # team retries with feedback, so beats land at level 1 or fall to templates.
        "unreliable": Faults(mode="hallucinate", every=2, tasks=frozenset({"explain", "story", "localize"})),
        # The model endpoint is down for the whole match.
        "outage": Faults(mode="error"),
    }


def default_cohorts(meta: dict) -> tuple[Cohort, ...]:
    """Cohorts a replay package covers: both modes in every language, plus each club's fans."""
    out = [Cohort(mode=m, language=lang) for lang in SUPPORTED_LANGUAGES for m in ("analyst", "casual")]
    for side in ("home", "away"):
        out.append(Cohort(mode="casual", language="en", perspective=meta[side]["id"]))
    return tuple(out)


@dataclass
class Replay:
    meta: dict
    cohorts: tuple[Cohort, ...]
    moments: list[dict]
    snapshots: list[dict]
    facts: list[dict]
    overlays: list[Overlay]
    events: list[dict]
    recaps: list[dict] = field(default_factory=list)
    variants: dict[str, dict] = field(default_factory=dict)  # model-health variants: narrative overlays + traces
    info: dict = field(default_factory=dict)
    analytics: dict = field(default_factory=dict)  # the Opta-style views of the match (analytics.json)


def _explanations(pack: dict, agent_made: dict | None) -> dict:
    """The explanation in every language: English from the agent team when it ran, the rest from templates."""
    out = {lang: templates.explain(pack, lang).model_dump() for lang in SUPPORTED_LANGUAGES}
    if agent_made:
        out["en"] = agent_made
    return out


async def _write_recaps(team, ip, cohorts, moments: dict[str, dict], registry, meta: dict) -> list[dict]:
    packs = {"preview": build_preview_pack(meta, ip.season), "half_time": build_pack(ip, "half_time"), "full_time": build_pack(ip, "full_time")}
    out = []
    for pack in packs.values():
        for c in cohorts:
            r = await recap_writer.write_recap(team, pack, c, moments, registry)
            out.append(r.model_dump(mode="json"))
    return out


def _overlay_levels(overlays: list[Overlay]) -> dict[str, int]:
    """How the narrative overlays were made: 0 first-time agent text, 1 after a retry, 2 template."""
    return {str(k): sum(1 for o in overlays if o.provenance.fallbackLevel == k and o.kind in ("lower_third", "ticker")) for k in (0, 1, 2)}


def _batches(moments: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = []
    for m in sorted(moments, key=lambda m: m["detectedAt"]["matchMs"]):
        t = m["detectedAt"]["matchMs"]
        if out and t - out[-1][0]["detectedAt"]["matchMs"] <= BATCH_WINDOW_MS:
            out[-1].append(m)
        else:
            out.append([m])
    return out


async def _run_agents(moments: list[dict], cohorts: tuple[Cohort, ...], deps: WorkflowDeps, budget_s: float) -> list[BeatResult]:
    wf = build_workflow(deps)
    results: list[BeatResult] = []
    kept_at: list[int] = []  # match time of story beats kept so far (for the rolling budget)
    for batch_moments in _batches(moments):
        t0 = batch_moments[0]["detectedAt"]["matchMs"]
        recent = sum(1 for t in kept_at if t0 - t < 10 * 60_000)
        budget = max(0, STORY_BUDGET_PER_10_MIN - recent)
        res = await run_batch(wf, Batch(moments=tuple(batch_moments), cohorts=cohorts, budget=budget, budget_s=budget_s))
        for r in res:
            if r.overlays and r.overlays[0].kind != "ticker":
                m = next(m for m in batch_moments if m["id"] == r.momentId)
                if m["type"] not in MUST_SHOW and m["salience"] < HEADLINE_SALIENCE:  # only the optional beats use up the budget
                    kept_at.append(m["detectedAt"]["matchMs"])
        results.extend(res)
    return results


def build_replay(
    result,
    *,
    llm: str | None = None,
    faults: Faults | None = None,
    cohorts: tuple[Cohort, ...] | None = None,
    budget_s: float = 30.0,
    settings: AgentSettings | None = None,
) -> Replay:
    meta = result.meta
    cohorts = cohorts or default_cohorts(meta)
    analysis = analyze_match(result)
    season_data = load_season()
    ctx = context_for(season_data, meta["home"]["id"], meta["away"]["id"])
    ip, out = interpret_match(
        result,
        baselines=load_baselines(),
        xt=XTGrid.load(league_dir() / "xt_grid.json"),
        season=ctx,
        models=load_models(),
    )
    client = make_chat_client(llm, faults=faults)
    store = InMemoryMomentStore()
    registry = Registry.from_meta(meta)
    deps = WorkflowDeps(team=AgentTeam(client, settings), registry=registry, store=store)
    beats = asyncio.run(_run_agents(out.moments, cohorts, deps, budget_s))
    by_id = {m["id"]: m for m in out.moments}
    if hasattr(client, "context"):
        client.context["moments"] = by_id
    recaps = asyncio.run(_write_recaps(deps.team, ip, cohorts, by_id, registry, meta))

    variants: dict[str, dict] = {}
    if llm in (None, "offline"):
        for name, vf in health_variants().items():
            vstore = InMemoryMomentStore()
            vclient = make_chat_client(llm, faults=vf)
            vdeps = WorkflowDeps(team=AgentTeam(vclient, settings), registry=registry, store=vstore)
            vbeats = asyncio.run(_run_agents(out.moments, cohorts, vdeps, budget_s))
            variants[name] = {
                "overlays": producer.resolve_collisions([o for b in vbeats for o in b.overlays]),
                "moments": {
                    m["id"]: {
                        "level": vstore.get(m["id"]).get("level"),
                        "trace": [{k: v for k, v in step.items() if k in ("agent", "outcome", "issues")} for step in vstore.get(m["id"]).get("trace", [])],
                    }
                    for m in out.moments
                },
                "levels": _overlay_levels([o for b in vbeats for o in b.overlays]),
            }

    names = {pid: p["name"] for side in ("home", "away") for pid, p in meta[side]["players"].items()}
    short = {meta[s]["id"]: meta[s]["short"] for s in ("home", "away")}
    names = {**names, **short}  # fact cards name clubs as well as players (club ids never collide with player ids)
    overlays: list[Overlay] = [o for b in beats for o in b.overlays]
    for lang in SUPPORTED_LANGUAGES:
        shared = Cohort(mode="any", language=lang)
        for fact in out.facts:
            o = producer.fact_overlay(fact, shared, names)
            if o is not None:
                overlays.append(o)
            g = producer.graphic_overlay(fact, shared, names)
            if g is not None:
                overlays.append(g)
        for snap in out.snapshots:
            overlays.extend(producer.momentum_overlays(snap, short, shared))
    overlays = producer.resolve_collisions(overlays)

    moments = []
    for m in out.moments:
        doc = store.get(m["id"])
        moments.append(
            {
                **m,
                "status": doc.get("status"),
                "level": doc.get("level"),
                "explanation": doc.get("explanation"),
                "explanations": _explanations(m, doc.get("explanation")),
                "variants": {n: v["moments"][m["id"]] for n, v in variants.items()},
                "trace": [{k: v for k, v in step.items() if k in ("agent", "outcome", "issues")} for step in doc.get("trace", [])],
            }
        )
    info = {
        "version": REPLAY_VERSION,
        "llm": llm or "offline",
        "cohorts": [c.key for c in cohorts],
        "languages": list(SUPPORTED_LANGUAGES),
        "moments": len(moments),
        "overlays": len(overlays),
        "recaps": len(recaps),
        "variants": {n: v["levels"] for n, v in variants.items()},
        "levels": _overlay_levels([o for b in beats for o in b.overlays]),
    }
    events = sorted([*result.events, *analysis.events], key=lambda e: (e["clock"]["matchMs"], e["seq"]))
    analytics = build_analytics(ip, season_data, ctx, meta)
    info["analytics"] = bool(analytics)
    return Replay(meta=meta, cohorts=cohorts, moments=moments, snapshots=out.snapshots, facts=out.facts, overlays=overlays, events=events, recaps=recaps, variants=variants, info=info, analytics=analytics)


def build_analytics(ip, season_data: dict, ctx: dict, meta: dict) -> dict:
    """The match analytics plus the season context and player and team radars that go with it."""
    an = MatchAnalytics(ip).summary()
    if ctx:
        clubs = [meta["home"]["id"], meta["away"]["id"]]
        an["season"] = {k: ctx[k] for k in ("season", "round", "played", "standings", "form", "streaks", "headToHead", "topScorers", "records", "prediction")}
        an["season"]["ratings"] = {c: ctx["ratings"][c] for c in clubs}
        an["radars"] = radars(season_data, an["players"])
        an["teamRadars"] = team_radars(season_data, clubs)
    return an


def write_replay(replay: Replay, result, outdir: Path) -> Path:
    """Write the static package: JSON documents plus one compact tracking bundle."""
    outdir.mkdir(parents=True, exist_ok=True)

    def dump(name: str, obj) -> None:
        (outdir / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")

    dump("meta.json", {**replay.meta, "package": replay.info})
    dump("moments.json", replay.moments)
    dump("snapshots.json", replay.snapshots)
    dump("facts.json", replay.facts)
    dump("recaps.json", replay.recaps)
    for name, v in replay.variants.items():
        dump(f"overlays.{name}.json", [o.model_dump(mode="json") for o in v["overlays"]])
    dump("overlays.json", [o.model_dump(mode="json") for o in replay.overlays])
    dump("events.json", [_slim_event(e) for e in replay.events if e["type"] not in _INTERNAL_EVENTS])
    if replay.analytics:
        dump("analytics.json", replay.analytics)
    size = bundle.write(result, outdir)
    report = _write_report(outdir)
    dump("manifest.json", {**replay.info, "matchId": replay.meta["matchId"], "trackingBytes": size, "files": [*(["report.pdf"] if report else []), *(f"overlays.{n}.json" for n in replay.variants), "meta.json", "moments.json", "snapshots.json", "facts.json", "overlays.json", "recaps.json", "events.json", *(["analytics.json"] if replay.analytics else []), "slots.json", "tracking.bin.gz"]})
    return outdir


def _write_report(outdir: Path) -> bool:
    """The printable report, built from the package just written. Optional: needs the ``report`` extra (reportlab)."""
    try:
        from .report import build_report
    except ImportError:
        return False
    build_report(outdir)
    return True


_KEEP = ("id", "type", "clock", "team", "player", "receiver", "location", "end", "outcome")


_TACTICAL_EVENTS = {"corner", "free_kick", "goal_kick", "throw_in", "formation_change", "off_ball_run"}
_TACTICAL_ATTRS = {"routine", "wall", "formation", "previous", "attack", "block", "kind", "distanceM", "peakKmh", "from", "to", "startMs", "durationMs"}
_INTERNAL_EVENTS = {"space_control", "shape_profile", "player_load", "phase_change"}  # analyzer inputs; their results live in analytics.json


def _slim_event(e: dict) -> dict:
    """Events as the web app needs them: enough to draw an evidence chain on the pitch."""
    slim = {k: e[k] for k in _KEEP if k in e}
    if e["type"] in ("pass", "shot"):
        slim["kind"] = e["attributes"].get("passType") or e["attributes"].get("bodyPart")
    if e["type"] in _TACTICAL_EVENTS:  # the routine and shape labels the Tactics panel reads
        keep = {k: v for k, v in e.get("attributes", {}).items() if k in _TACTICAL_ATTRS}
        if keep:
            slim["attributes"] = keep
    return slim
