"""The video feed of one live match: chunks go in as they are published, tracking chunks come out for the analyzer.

``VisionFeed`` sits where the physical analyzer used to read the provider's tracking. When the player publishes a chunk, the feed hands the analyzer what the video
model rebuilt from it: the model's reading of a demo is done once for everyone (:mod:`shared`), so a session only *takes* the rebuilt chunk (waiting a moment if the
worker is just finishing it) and falls back to the provider's own tracking for a chunk the worker has not reached. The physical facts (speeds, sprints, pass
difficulty, shot speed) in a live match therefore come from what the video model saw, and a viewer costs almost nothing.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..live.blobs import MemoryBlobs
from ..tracking.frames import Chunk, decode_chunk
from .detect import detect
from .render import PX, png, render_frame, to_px
from .shared import SharedVision, shared_for

WAIT_S = 2.5  # how long a chunk waits for the shared reader before the provider's tracking is used for it
BOX = {"home": (255, 220, 120), "away": (140, 220, 255), "ball": (255, 255, 0)}


def events_for_anchoring(docs: list[dict], hz: int) -> list[tuple[int, str, float, float]]:
    """(frame, player, x, y) of every feed event that names a player and a place: what the tracker uses to tell who is who."""
    out = []
    for d in docs:
        x = d.get("doc") or {}
        loc = x.get("location")
        if x.get("player") and loc:
            out.append((round(x["clock"]["matchMs"] * hz / 1000), x["player"], float(loc["x"]), float(loc["y"])))
    return sorted(out)


class VisionFeed:
    def __init__(self, demo_id: str, truth_chunks: list[tuple[int, str, bytes]], docs: list[dict], hz: int = 5, shared: SharedVision | None = None, from_ms: int = 0) -> None:
        self.ends = {name: end for end, name, _ in truth_chunks}
        self.from_ms = from_ms  # a viewer who joins mid-match: the chunks before this are the past, never waited for
        self.names = [name for _, name, _ in truth_chunks]
        self.index = {name: i for i, name in enumerate(self.names)}
        self.truth = {name: data for _, name, data in truth_chunks}
        self.hz = hz
        self.shared = shared or shared_for(demo_id, truth_chunks, events_for_anchoring(docs, hz))
        self.blobs = MemoryBlobs()  # the chunks the analyzer reads: the video model's, or the provider's where the model was not ready
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision-take")  # waiting threads, in order; no CPU of their own
        self.submitted = 0
        self.resolved = 0
        self.taken = 0
        self.skipped = 0
        self._decoded: dict[str, Chunk] = {}
        self._lock = threading.Lock()

    # ----- the player publishes a chunk -----------------------------------------------------------------

    def submit(self, name: str) -> None:
        self.submitted += 1
        self.pool.submit(self._take, name)

    def pending(self) -> int:
        return self.submitted - self.resolved

    def _take(self, name: str) -> None:
        try:
            past = self.ends[name] <= self.from_ms
            got = self.shared.get(self.index[name]) if past else self.shared.wait(self.index[name], WAIT_S)
            if got is None:
                got = self.truth[name]  # the video model has not reached this chunk (a fast match, a cold server): the provider's tracking, so the match never waits
                self.skipped += 1
            else:
                self.taken += 1
            self.blobs.put(name, got)
        finally:
            self.resolved += 1

    # ----- what the viewer is shown ---------------------------------------------------------------------

    def _chunk(self, i: int) -> Chunk | None:
        if not 0 <= i < len(self.names):
            return None
        name = self.names[i]
        with self._lock:
            c = self._decoded.get(name)
            if c is None:
                c = self._decoded[name] = decode_chunk(self.truth[name])
                for old in [n for n in self._decoded if n != name][: max(0, len(self._decoded) - 6)]:
                    del self._decoded[old]
        return c

    def frame_png(self, frame: int) -> bytes | None:
        """The video frame with what the detector finds in it boxed (read again here, so nothing is stored per frame), or None if there is no such frame."""
        per = max(1, round(5 * self.hz))
        c = self._chunk(frame // per)
        if c is None or not c.first_frame <= frame < c.first_frame + c.n or frame // per >= len(self.shared.results) + 1:
            return None
        i = frame - c.first_frame
        img = render_frame(c.frames[i], c.ball[i], np.random.default_rng(frame))
        for kind, x, y, r in detect(img).blobs:
            x0, y0, x1, y1 = int(x - r - 1), int(y - r - 1), int(x + r + 1), int(y + r + 1)
            x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, img.shape[1] - 1), min(y1, img.shape[0] - 1)
            col = np.array(BOX[kind], dtype=np.uint8)
            img[y0, x0 : x1 + 1] = col
            img[y1, x0 : x1 + 1] = col
            img[y0 : y1 + 1, x0] = col
            img[y0 : y1 + 1, x1] = col
        return png(img)

    def stats(self) -> dict:
        return {**self.shared.stats(), "takenChunks": self.taken, "skippedChunks": self.skipped, "pxPerMetre": PX}

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


class TeeBlobs:
    """What the match player writes chunks to: the shared store as before, and the video feed too."""

    def __init__(self, blobs: MemoryBlobs, feed: VisionFeed) -> None:
        self.blobs, self.feed = blobs, feed

    def put(self, name: str, data: bytes) -> None:
        self.blobs.put(name, data)
        self.feed.submit(name)

    def get(self, name: str) -> bytes | None:
        return self.blobs.get(name)

    def exists(self, name: str) -> bool:
        return self.blobs.exists(name)

    def purge(self, prefix: str) -> None:
        self.blobs.purge(prefix)


__all__ = ["TeeBlobs", "VisionFeed", "events_for_anchoring", "to_px"]
