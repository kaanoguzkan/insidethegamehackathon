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
from .agents.llm import Faults, make_chat_client
from .agents.store import InMemoryMomentStore
from .agents.team import AgentSettings, AgentTeam
from .agents.verify import Registry
from .agents.workflow import Batch, BeatResult, WorkflowDeps, build_workflow, run_batch
from .core.contracts import SUPPORTED_LANGUAGES, Cohort, Overlay
from .core.paths import league_dir
from .intel.baselines import load_baselines
from .intel.pipeline import interpret_match
from .intel.xt import XTGrid
from .tracking import bundle
from .tracking.analyzer import analyze_match

BATCH_WINDOW_MS = 60_000
STORY_BUDGET_PER_10_MIN = 3
REPLAY_VERSION = "1"


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
    info: dict = field(default_factory=dict)


def _explanations(pack: dict, agent_made: dict | None) -> dict:
    """The explanation in every language: English from the agent team when it ran, the rest from templates."""
    out = {lang: templates.explain(pack, lang).model_dump() for lang in SUPPORTED_LANGUAGES}
    if agent_made:
        out["en"] = agent_made
    return out


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
                kept_at.append(next(m["detectedAt"]["matchMs"] for m in batch_moments if m["id"] == r.momentId))
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
    ip, out = interpret_match(
        result,
        baselines=load_baselines(),
        xt=XTGrid.load(league_dir() / "xt_grid.json"),
    )
    client = make_chat_client(llm, faults=faults)
    store = InMemoryMomentStore()
    registry = Registry.from_meta(meta)
    deps = WorkflowDeps(team=AgentTeam(client, settings), registry=registry, store=store)
    beats = asyncio.run(_run_agents(out.moments, cohorts, deps, budget_s))

    names = {pid: p["name"] for side in ("home", "away") for pid, p in meta[side]["players"].items()}
    short = {meta[s]["id"]: meta[s]["short"] for s in ("home", "away")}
    overlays: list[Overlay] = [o for b in beats for o in b.overlays]
    for lang in SUPPORTED_LANGUAGES:
        shared = Cohort(mode="any", language=lang)
        for fact in out.facts:
            o = producer.fact_overlay(fact, shared, names)
            if o is not None:
                overlays.append(o)
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
        "levels": {str(k): sum(1 for b in beats if b.level == k) for k in (0, 1, 2, 3)},
    }
    events = sorted([*result.events, *analysis.events], key=lambda e: (e["clock"]["matchMs"], e["seq"]))
    return Replay(meta=meta, cohorts=cohorts, moments=moments, snapshots=out.snapshots, facts=out.facts, overlays=overlays, events=events, info=info)


def write_replay(replay: Replay, result, outdir: Path) -> Path:
    """Write the static package: JSON documents plus one compact tracking bundle."""
    outdir.mkdir(parents=True, exist_ok=True)

    def dump(name: str, obj) -> None:
        (outdir / name).write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n")

    dump("meta.json", {**replay.meta, "package": replay.info})
    dump("moments.json", replay.moments)
    dump("snapshots.json", replay.snapshots)
    dump("facts.json", replay.facts)
    dump("overlays.json", [o.model_dump(mode="json") for o in replay.overlays])
    dump("events.json", [_slim_event(e) for e in replay.events])
    size = bundle.write(result, outdir)
    dump("manifest.json", {**replay.info, "matchId": replay.meta["matchId"], "trackingBytes": size, "files": ["meta.json", "moments.json", "snapshots.json", "facts.json", "overlays.json", "events.json", "slots.json", "tracking.bin.gz"]})
    return outdir


_KEEP = ("id", "type", "clock", "team", "player", "receiver", "location", "end", "outcome")


def _slim_event(e: dict) -> dict:
    """Events as the web app needs them: enough to draw an evidence chain on the pitch."""
    slim = {k: e[k] for k in _KEEP if k in e}
    if e["type"] in ("pass", "shot"):
        slim["kind"] = e["attributes"].get("passType") or e["attributes"].get("bodyPart")
    return slim
