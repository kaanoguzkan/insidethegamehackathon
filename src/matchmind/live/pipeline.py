"""The interpret stage between the feed and the viewers, a plain function over a :class:`~matchmind.live.store.LiveStore`.

* :func:`interpret` is what the Cosmos change-feed Function runs when new feed documents arrive: it replays the match's documents through the
  interpreter in arrival order, stores the moments it finds (the new ones are what the dispatcher acts on) and the template overlays that need no
  model (facts, graphics, momentum). The interpreter is deterministic, so replaying from the start gives the same moments every time and a
  re-delivered batch changes nothing; keeping no state between invocations is what lets the Function scale to zero and be restarted freely.
  The narrative overlays for the new moments are written by :func:`matchmind.live.dispatch.write_beats`, in the Brain.

Both stages are idempotent and neither knows whether it runs in a Function, the Brain or a test.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from ..agents import producer
from ..analytics import load_models
from ..analytics.season import context_for, load_season
from ..core.contracts import SUPPORTED_LANGUAGES, Cohort
from ..core.paths import league_dir
from ..intel.baselines import load_baselines
from ..intel.interpreter import Interpreter, InterpretOutput
from ..intel.xt import XTGrid
from .store import FINAL, LiveStore


@dataclass
class Intel:
    """What the interpreter is calibrated with: the league baselines, the xT grid, the fitted models and the season so far."""

    baselines: dict
    xt: XTGrid
    models: dict
    season: dict

    @classmethod
    @cache
    def load(cls) -> Intel:
        return cls(load_baselines(), XTGrid.load(league_dir() / "xt_grid.json"), load_models(), load_season())


def interpret(store: LiveStore, match_id: str, intel: Intel | None = None) -> dict:
    """Run every document of the match so far through the interpreter; store the new moments and the model-free overlays."""
    info = store.get_match(match_id)
    if info is None:
        return {"matchId": match_id, "error": "unknown match"}
    intel = intel or Intel.load()
    meta = info["meta"]
    ip = Interpreter(
        meta, baselines=intel.baselines, xt=intel.xt, models=intel.models,
        season=context_for(intel.season, meta["home"]["id"], meta["away"]["id"]),
    )
    out = InterpretOutput()
    docs = store.docs(match_id)
    finished = False
    for d in docs:
        if d["kind"] == FINAL:
            finished = True
            continue
        out.extend(ip.ingest(d["doc"], arrival_ms=d["arrivalMs"]))
    if finished:
        out.extend(ip.finish())
    new_moments = store.add_moments(match_id, out.moments)

    names = {pid: p["name"] for side in ("home", "away") for pid, p in meta[side]["players"].items()}
    short = {meta[s]["id"]: meta[s]["short"] for s in ("home", "away")}
    names = {**names, **short}
    overlays = []
    for lang in SUPPORTED_LANGUAGES:
        shared = Cohort(mode="any", language=lang)
        for fact in out.facts:
            for o in (producer.fact_overlay(fact, shared, names), producer.graphic_overlay(fact, shared, names)):
                if o is not None:
                    overlays.append(o)
        for snap in out.snapshots:
            overlays.extend(producer.momentum_overlays(snap, short, shared))
    new_overlays = store.add_overlays(match_id, [o.model_dump(mode="json") for o in overlays])
    return {
        "matchId": match_id, "documents": len(docs), "moments": len(out.moments), "newMoments": new_moments,
        "newOverlays": len(new_overlays), "finished": finished,
    }
