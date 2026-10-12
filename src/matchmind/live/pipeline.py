"""The interpret stage between the feed and the viewers, over a :class:`~matchmind.live.store.LiveStore`.

:class:`InterpretWorker` is what the Cosmos change-feed Function runs when new documents arrive. It is **incremental and event-time driven**:

* It reads only the documents in ``(limit it has reached, new limit]`` and feeds them to the interpreter in arrival order. The new limit is the lower of
  two **watermarks**: the feed's (the job states, after writing a batch, that every document up to that match time is written) and the physical
  analyzer's (the analyzer Function states the same after each tracking chunk; see :mod:`matchmind.live.analysis`). Everything the interpreter ever
  sees is therefore complete and in a fixed order, so the moments it finds and their ids do not depend on which piece happened to be produced first.
* The interpreter's state stays in memory while the instance is warm and is checkpointed to blob storage (signed) for recovery; a cold instance restores
  the checkpoint and reads the documents since. Moments and overlays are created only if absent, so re-reading changes nothing.
* When both watermarks say "finished", the interpreter is flushed (``finish()``): the last moments, the full-time facts.

The narrative overlays for new moments are written by :func:`matchmind.live.dispatch.write_beats`, in the Brain. Neither stage knows whether it runs
in a Function, the Brain or a test.
"""

from __future__ import annotations

import gzip
import pickle  # noqa: S403 - only ever loads checkpoints that carry a valid HMAC from this service's own key
import time
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
from .analysis import signing_key
from .blobs import Blobs, sign, unsign
from .feed import INF
from .store import FINAL, LiveStore

LOCK = "interpret"
LOCK_TTL_MS = 60_000
CHECKPOINT_EVERY_S = 20.0


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


@dataclass
class _Run:
    ip: Interpreter
    limit: int = -1  # every document with arrivalMs <= limit has been interpreted
    finished: bool = False
    checkpointed_at: float = 0.0


class InterpretWorker:
    def __init__(self, store: LiveStore, checkpoints: Blobs | None = None, intel: Intel | None = None, key: bytes | None = None, checkpoint_every_s: float = CHECKPOINT_EVERY_S) -> None:
        self.store, self.checkpoints, self.intel = store, checkpoints, intel
        self.key = key if key is not None else signing_key()  # None: no checkpoints
        self.checkpoint_every_s = checkpoint_every_s
        self._cache: dict[str, _Run] = {}

    # ----- watermarks ---------------------------------------------------------------------------------

    def _limit(self, match_id: str, info: dict) -> tuple[int, bool, dict]:
        """How far the match can be interpreted now, whether it is complete, and the two watermarks (for the caller to report)."""
        if info.get("physical", "inline") == "inline":  # the physical facts are in the feed: everything written is complete
            docs = self.store.docs(match_id)
            done = any(d["kind"] == FINAL for d in docs)
            feed = INF if done else max((d["arrivalMs"] for d in docs), default=-1)
            return feed, done, {"feedMs": feed, "physicalMs": INF}
        feed = self.store.get_state(match_id, "feedWm", -1)
        analyzer = self.store.get_state(match_id, "analyzer", None) or {}
        physical = analyzer.get("wmMs", -1)
        return min(feed, physical), feed >= INF and physical >= INF, {"feedMs": feed, "physicalMs": physical}

    # ----- the entry point ----------------------------------------------------------------------------

    def run(self, match_id: str) -> dict:
        info = self.store.get_match(match_id)
        if info is None or not info.get("meta"):
            return {"matchId": match_id, "error": "unknown match"}
        if not self.store.acquire(match_id, LOCK, LOCK_TTL_MS):
            return {"matchId": match_id, "busy": True}
        try:
            return self._run_locked(match_id, info)
        finally:
            self.store.release(match_id, LOCK)

    def _run_locked(self, match_id: str, info: dict) -> dict:
        meta = info["meta"]
        run = self._cache.get(match_id) or self._restore(match_id, info)
        limit, complete, marks = self._limit(match_id, info)
        out = InterpretOutput()
        read = 0
        if limit > run.limit:
            for d in self.store.docs_between(match_id, run.limit, limit):
                if d["kind"] == FINAL:
                    continue
                out.extend(run.ip.ingest(d["doc"], arrival_ms=d["arrivalMs"]))
                read += 1
            run.limit = limit
        if complete and not run.finished:
            out.extend(run.ip.finish())
            run.finished = True
        self._cache[match_id] = run

        new_moments = self.store.add_moments(match_id, out.moments)
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
        new_overlays = self.store.add_overlays(match_id, [o.model_dump(mode="json") for o in overlays])
        self._maybe_checkpoint(match_id, run)
        return {
            "matchId": match_id, "read": read, "limitMs": run.limit, **marks, "moments": len(out.moments), "newMoments": new_moments,
            "newOverlays": len(new_overlays), "finished": run.finished,
        }

    # ----- recovery -----------------------------------------------------------------------------------

    def _fresh(self, info: dict) -> Interpreter:
        intel = self.intel or Intel.load()
        meta = info["meta"]
        return Interpreter(meta, baselines=intel.baselines, xt=intel.xt, models=intel.models, season=context_for(intel.season, meta["home"]["id"], meta["away"]["id"]))

    def _restore(self, match_id: str, info: dict) -> _Run:
        raw = unsign(self.checkpoints.get(f"interpreter/{match_id}.bin"), self.key) if self.checkpoints is not None and self.key else None
        if raw is not None:
            try:
                saved = pickle.loads(gzip.decompress(raw))  # noqa: S301 - signed by this service
                return _Run(saved["ip"], saved["limit"], saved["finished"], time.monotonic())
            except Exception:  # noqa: BLE001 - a checkpoint that does not load is as good as none
                pass
        return _Run(self._fresh(info), checkpointed_at=time.monotonic())

    def _maybe_checkpoint(self, match_id: str, run: _Run) -> None:
        if self.checkpoints is None or not self.key or time.monotonic() - run.checkpointed_at < self.checkpoint_every_s:
            return
        blob = gzip.compress(pickle.dumps({"ip": run.ip, "limit": run.limit, "finished": run.finished}, protocol=5), compresslevel=1)
        self.checkpoints.put(f"interpreter/{match_id}.bin", sign(blob, self.key))
        run.checkpointed_at = time.monotonic()


def interpret(store: LiveStore, match_id: str, intel: Intel | None = None) -> dict:
    """One pass from scratch over what is complete so far (no cache, no checkpoint): what the tests and a one-off run use."""
    return InterpretWorker(store, None, intel).run(match_id)
