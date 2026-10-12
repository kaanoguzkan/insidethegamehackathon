"""The physical analyzer as an event-driven worker: tracking chunk in Blob Storage, physical facts out in Cosmos DB.

The simulator job publishes five-second tracking chunks to Blob Storage as the match is played. Each new blob raises an Event Grid event that wakes the
``analyze`` Function, which calls :meth:`AnalyzerWorker.drain`. Event Grid delivers at least once and in no particular order, and the analyzer is a
stateful, strictly sequential algorithm, so ``drain`` does not process "the chunk in the event": it processes **the next chunks in order, as many as
exist**, under a lock (a second invocation that finds the lock taken simply returns, and the holder looks once more after releasing it, so a chunk that
arrives at the wrong moment is never forgotten).

The analyzer's state (about 4 MB at the end of a match) is kept in memory while the instance is warm and checkpointed to blob storage every
``CHECKPOINT_EVERY`` chunks. A cold instance restores the last checkpoint and replays the chunks since, discarding what it already wrote; its output
documents have deterministic ids and are created only if absent, so replaying changes nothing.

After each chunk the worker writes the documents first and then states the **physical watermark**: the match time up to which every physical
document is known to be written. A document is never emitted more than one chunk (5.2 s, measured on all three scenarios) after its own match time,
so after chunk *k* everything up to the chunk's end minus ``LOOKBACK_MS`` is complete. The interpreter reads up to the lower of the feed's and this
watermark, which keeps what it sees in a fixed order whatever the order in which the pieces were produced.
"""

from __future__ import annotations

import gzip
import os
import pickle  # noqa: S403 - only ever loads blobs that carry a valid HMAC from this service's own key
from dataclasses import dataclass

from ..tracking.analyzer import PhysicalAnalyzer
from ..tracking.frames import decode_chunk
from .blobs import Blobs, sign, unsign
from .feed import INF, analyzer_docs, chunk_name
from .store import LiveStore

LOOKBACK_MS = 6000  # a physical document is emitted at most 5.2 s after its own match time
CHECKPOINT_EVERY = 30  # chunks (2.5 minutes of match time)
LOCK = "analyzer"
LOCK_TTL_MS = 60_000
EVENT_TYPES = ("period_start", "pass", "shot", "offside")  # the events the analyzer needs from the feed


def signing_key() -> bytes | None:
    """The key checkpoints are signed with: the service's shared secret. With none configured there are no checkpoints at all (a worker that
    fell back to a key anyone can read would load whatever somebody planted in the storage account)."""
    key = os.environ.get("MATCHMIND_LIVE_KEY")
    return key.encode() if key else None


@dataclass
class _Run:
    analyzer: PhysicalAnalyzer
    next: int = 0  # the next chunk to process
    seen_n: int = -1  # the last feed document handed to the analyzer


class AnalyzerWorker:
    def __init__(self, store: LiveStore, frames: Blobs, checkpoints: Blobs, key: bytes | None = None) -> None:
        self.store, self.frames, self.checkpoints = store, frames, checkpoints
        self.key = key if key is not None else signing_key()  # None: no checkpoints; a cold instance replays from the first chunk
        self._cache: dict[str, _Run] = {}

    # ----- the entry point --------------------------------------------------------------------------

    def drain(self, match_id: str) -> dict:
        """Process every chunk that is available and next in order. Safe to call from any number of concurrent triggers."""
        info = self.store.get_match(match_id)
        if info is None or info.get("physical") != "chunks":
            return {"matchId": match_id, "skipped": True}
        total = int(info["chunks"])
        processed = 0
        for _ in range(3):  # release, then look again: a chunk that arrived while the lock was held must not wait for the next event
            if not self.store.acquire(match_id, LOCK, LOCK_TTL_MS):
                return {"matchId": match_id, "processed": processed, "busy": True}
            try:
                processed += self._drain_locked(match_id, info, total)
                nxt = self._cache[match_id].next
            finally:
                self.store.release(match_id, LOCK)
            if nxt >= total or not self.frames.exists(chunk_name(match_id, nxt)):
                break
        state = self.store.get_state(match_id, "analyzer", {})
        return {"matchId": match_id, "processed": processed, "next": state.get("next", 0), "watermarkMs": state.get("wmMs"), "final": state.get("final", False)}

    # ----- internals --------------------------------------------------------------------------------

    def _drain_locked(self, match_id: str, info: dict, total: int) -> int:
        state = self.store.get_state(match_id, "analyzer", {"next": 0, "wmMs": -1, "final": False})
        run = self._cache.get(match_id)
        if run is None or run.next != state["next"]:
            run = self._restore(match_id, info, state["next"])
        count = 0
        while run.next < total:
            data = self.frames.get(chunk_name(match_id, run.next))
            if data is None:
                break
            out_docs, end = self._step(run, match_id, decode_chunk(data), last=run.next == total - 1)
            self.store.add_docs(match_id, out_docs)  # the documents first ...
            run.next += 1
            last = run.next >= total
            self.store.put_state(match_id, "analyzer", {"next": run.next, "wmMs": INF if last else end - LOOKBACK_MS, "final": last})  # ... then the watermark
            if run.next % CHECKPOINT_EVERY == 0:
                self._checkpoint(match_id, run)
            count += 1
        self._cache[match_id] = run
        return count

    def _step(self, run: _Run, match_id: str, chunk, *, last: bool) -> tuple[list[dict], int]:  # noqa: ANN001
        end = chunk.start_ms + chunk.n * 1000 // chunk.hz
        self._feed_events(run, match_id, end)
        out = run.analyzer.process_chunk(chunk)
        docs = analyzer_docs(out)
        if last:  # the match is over: the analyzer also gets the events after the last chunk (the final whistle) and settles what is pending
            self._feed_events(run, match_id, INF)
            docs += analyzer_docs(run.analyzer.flush())
        return docs, end

    def _feed_events(self, run: _Run, match_id: str, upto_ms: int) -> None:
        """Hand the analyzer the feed events up to ``upto_ms`` that it has not seen (it needs the passes and shots to enrich them)."""
        while True:
            page = self.store.docs_after(match_id, run.seen_n, 200)
            take = []
            for d in page:
                if d["arrivalMs"] > upto_ms:
                    break
                take.append(d)
            if take:
                run.seen_n = take[-1]["n"]
                run.analyzer.add_events([d["doc"] for d in take if d["doc"].get("type") in EVENT_TYPES])
            if len(take) < len(page) or len(page) < 200:
                return

    def _restore(self, match_id: str, info: dict, next_index: int) -> _Run:
        """A run at chunk ``next_index``: from the last checkpoint if there is a valid one, replaying the chunks since without writing anything."""
        run: _Run | None = None
        raw = unsign(self.checkpoints.get(f"analyzer/{match_id}.bin"), self.key) if self.key else None
        if raw is not None:
            try:
                saved = pickle.loads(gzip.decompress(raw))  # noqa: S301 - signed by this service
                if saved["next"] <= next_index:
                    run = _Run(saved["analyzer"], saved["next"], saved["seenN"])
            except Exception:  # noqa: BLE001 - a checkpoint that does not load is as good as none
                run = None
        if run is None:
            run = _Run(PhysicalAnalyzer(info["meta"]))
        while run.next < next_index:
            data = self.frames.get(chunk_name(match_id, run.next))
            if data is None:
                break
            self._step(run, match_id, decode_chunk(data), last=False)  # its documents are already stored
            run.next += 1
        return run

    def _checkpoint(self, match_id: str, run: _Run) -> None:
        if not self.key:
            return
        blob = gzip.compress(pickle.dumps({"next": run.next, "seenN": run.seen_n, "analyzer": run.analyzer}, protocol=5), compresslevel=1)
        self.checkpoints.put(f"analyzer/{match_id}.bin", sign(blob, self.key))
