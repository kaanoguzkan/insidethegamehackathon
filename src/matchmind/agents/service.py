"""The "beats" service: overlays for chosen moments and viewer cohorts, as one request and one answer.

Shared by everything that serves it, so they all run the same code: the Brain's ``POST /api/beats`` and the hosted
Foundry agent (``foundry_host``). A request names a match, moments and cohorts; the answer carries each moment's overlays,
the agents that made them and a trace of what each did.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from ..core.contracts import Cohort
from .cache import BeatCache
from .fast import run_fast
from .store import InMemoryMomentStore
from .team import AgentSettings, AgentTeam
from .verify import Registry
from .workflow import Batch, WorkflowDeps, build_workflow, run_batch

MAX_COHORTS = 12  # cost guard: text is generated once per cohort, so bound the number per request
MAX_MOMENTS = 6

# Keys the replay runner adds to a moment after the evidence pack is built (the agents' own recorded answers).
RECORDED_ONLY = {"status", "level", "explanation", "explanations", "variants", "trace"}


class BeatRequest(BaseModel):
    match_id: str
    moment_ids: list[str] = Field(min_length=1, max_length=MAX_MOMENTS)
    cohorts: list[Cohort] = Field(min_length=1, max_length=MAX_COHORTS)
    budget: int = Field(3, ge=0, le=MAX_MOMENTS)
    mode: Literal["fast", "full"] = Field(
        "fast", description="fast: one model call per cohort inside deadlineMs, template text for what misses it; full: the five-agent workflow"
    )
    deadlineMs: int = Field(5000, ge=500, le=30000, description="fast mode: wall-clock limit for the whole request")
    useCache: bool = Field(True, description="fast mode: serve and store verified model text in the Brain's cache")


class UnknownMoments(LookupError):
    """The request names moments the match does not have."""


def load_recorded(root: Path, match_id: str) -> tuple[dict[str, dict], Registry] | None:
    """Moment packs and the name registry from a replay package on disk, or None if it has none.

    Reading the package is milliseconds; the alternative, re-simulating the match from its seed, is about 6 s on a laptop
    and about 20 s on a 1-vCPU container.
    """
    d = root / match_id
    if not ((d / "moments.json").exists() and (d / "meta.json").exists()):
        return None
    packs = {m["id"]: {k: v for k, v in m.items() if k not in RECORDED_ONLY} for m in json.loads((d / "moments.json").read_text())}
    return packs, Registry.from_meta(json.loads((d / "meta.json").read_text()))


async def serve_beats(
    req: BeatRequest, *, packs: dict[str, dict], registry: Registry, team: AgentTeam, cache: BeatCache | None = None,
    settings: AgentSettings | None = None,
) -> dict:
    """Run the request and return the answer as plain JSON. Raises :class:`UnknownMoments` for ids the match lacks."""
    missing = [m for m in req.moment_ids if m not in packs]
    if missing:
        raise UnknownMoments(f"unknown moments: {missing}")
    settings = settings or AgentSettings.from_env()
    store = InMemoryMomentStore()
    batch = Batch(
        moments=tuple(packs[m] for m in req.moment_ids), cohorts=tuple(req.cohorts), budget=req.budget,
        budget_s=min(settings.beat_budget_s or 15.0, 90.0),
    )
    t0 = time.monotonic()
    stats: dict = {}
    if req.mode == "fast":
        results = await run_fast(team, batch, deadline_s=req.deadlineMs / 1000.0, registry=registry, store=store, cache=cache if req.useCache else None, stats=stats)
    else:
        results = await run_batch(build_workflow(WorkflowDeps(team=team, registry=registry, store=store)), batch)
    return {
        "mode": req.mode,
        "stats": {**stats, "cacheSize": len(cache) if cache is not None else 0} if req.mode == "fast" else None,
        "elapsedMs": round((time.monotonic() - t0) * 1000),
        "beats": [
            {
                "momentId": r.momentId, "level": r.level, "agents": list(r.agents),
                "overlays": [o.model_dump(mode="json") for o in r.overlays],
                "trace": [{k: v for k, v in s.items() if k in ("agent", "outcome", "ms")} for s in store.get(r.momentId).get("trace", [])],
            }
            for r in sorted(results, key=lambda r: r.momentId)
        ],
    }
