"""The dispatch stage: write the narrative overlays for new moments of a live match with the fast path and store them.

Kept apart from :mod:`matchmind.live.pipeline` because it needs the agent framework and a model: it runs in the Brain, while the interpret stage runs
in a Function that has no use for either.
"""

from __future__ import annotations

from ..agents.llm import HEADLINE_SALIENCE, MUST_SHOW
from ..agents.service import RECORDED_ONLY, BeatRequest, serve_beats
from ..agents.team import AgentTeam
from ..agents.verify import Registry
from ..runner import BATCH_WINDOW_MS, STORY_BUDGET_PER_10_MIN, default_cohorts
from .store import LiveStore


def _batches(moments: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = []
    for m in sorted(moments, key=lambda m: m["detectedAt"]["matchMs"]):
        t = m["detectedAt"]["matchMs"]
        if out and t - out[-1][0]["detectedAt"]["matchMs"] <= BATCH_WINDOW_MS and len(out[-1]) < 6:
            out[-1].append(m)
        else:
            out.append([m])
    return out


async def write_beats(
    store: LiveStore, match_id: str, moment_ids: list[str], *, team: AgentTeam, cache=None, deadline_ms: int = 6000,  # noqa: ANN001
) -> dict:
    """The narrative overlays for the given moments of a live match, written with the fast path and stored. Returns what happened."""
    info = store.get_match(match_id)
    if info is None:
        return {"matchId": match_id, "error": "unknown match"}
    meta = info["meta"]
    registry = Registry.from_meta(meta)
    packs = {m["id"]: {k: v for k, v in m.items() if k not in RECORDED_ONLY} for m in store.moments(match_id)}
    done: list[str] = list(store.get_state(match_id, "dispatched", []))  # a re-delivered change-feed batch must not write a second set
    wanted = [packs[i] for i in dict.fromkeys(moment_ids) if i in packs and i not in done]
    cohorts = default_cohorts(meta)
    kept_at: list[int] = list(store.get_state(match_id, "kept_at", []))
    written = rejected = calls = 0
    for batch in _batches(wanted):
        t0 = batch[0]["detectedAt"]["matchMs"]
        budget = max(0, STORY_BUDGET_PER_10_MIN - sum(1 for t in kept_at if t0 - t < 10 * 60_000))
        req = BeatRequest(match_id=match_id, moment_ids=[m["id"] for m in batch], cohorts=list(cohorts), budget=budget, mode="fast", deadlineMs=deadline_ms)
        res = await serve_beats(req, packs=packs, registry=registry, team=team, cache=cache)
        for beat in res["beats"]:
            overlays = beat["overlays"]
            written += len(store.add_overlays(match_id, overlays))
            if overlays and overlays[0]["kind"] != "ticker":
                m = packs[beat["momentId"]]
                if m["type"] not in MUST_SHOW and m["salience"] < HEADLINE_SALIENCE:
                    kept_at.append(m["detectedAt"]["matchMs"])
        stats = res.get("stats") or {}
        rejected += stats.get("rejected", 0)
        calls += stats.get("modelCalls", 0)
    store.put_state(match_id, "kept_at", kept_at)
    store.put_state(match_id, "dispatched", [*done, *(m["id"] for m in wanted)])
    return {"matchId": match_id, "moments": len(wanted), "overlaysWritten": written, "modelCalls": calls, "rejected": rejected}
