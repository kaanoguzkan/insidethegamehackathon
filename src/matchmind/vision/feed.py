"""The video feed of one live match: chunks go in as they are published, tracking chunks come out for the analyzer.

``VisionFeed`` sits where the physical analyzer used to read the provider's tracking. Each time the player publishes a chunk, the feed renders it as video, runs
the detector and the tracker over the frames, and publishes the *reconstructed* chunk under the same name in its own store; the analyzer reads that store. So the
physical facts (speeds, sprints, pass difficulty, shot speed) in a live match come from what the video model saw.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from ..live.blobs import MemoryBlobs
from ..tracking.frames import Chunk, decode_chunk, encode_chunk
from .detect import Detections
from .render import PX, png, render_frame, to_px
from .track import VideoTracker

MAX_BACKLOG = 3  # chunks the video model may be behind before the next ones are taken from the provider's tracking instead, so the match never waits for it
KEEP_FRAMES = 750  # frames of detections kept for the preview (2.5 minutes of match: the picture runs up to a minute behind the feed at 10x)
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
    def __init__(self, truth_chunks: list[tuple[int, str, bytes]], docs: list[dict], hz: int = 5, from_ms: int = 0) -> None:
        self.ends = {name: end for end, name, _ in truth_chunks}
        self.from_ms = from_ms  # a viewer who joins mid-match: what came before is the provider's archive, the video starts here
        self.submitted = 0
        self.names = [name for _, name, _ in truth_chunks]
        self.truth = {name: data for _, name, data in truth_chunks}
        self.events = events_for_anchoring(docs, hz)
        self.blobs = MemoryBlobs()  # the reconstructed chunks: what the analyzer reads
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision")  # one at a time and in order: the tracker is sequential
        self.tracker: VideoTracker | None = None
        self.done = 0
        self.busy_s = 0.0
        self.failed = 0
        self.skipped = 0
        self.resync = False
        self._decoded: dict[str, Chunk] = {}
        self._lock = threading.Lock()
        self._det: dict[int, Detections] = {}

    # ----- the player publishes a chunk -----------------------------------------------------------------

    def submit(self, name: str) -> None:
        if self.ends.get(name, 0) <= self.from_ms:
            self.blobs.put(name, self.truth[name])  # before the join point: the archive, as the provider delivers it
            return
        if self.pending() >= MAX_BACKLOG:
            self.blobs.put(name, self.truth[name])  # the video model is behind (a fast match, a busy server): this chunk is the provider's tracking, and the model starts again after it
            self.skipped += 1
            self.resync = True
            return
        self.submitted += 1
        self.pool.submit(self._process, name)

    def pending(self) -> int:
        return self.submitted - self.done - self.failed

    def _process(self, name: str) -> None:
        t0 = time.perf_counter()
        try:
            truth = decode_chunk(self.truth[name])
            if self.tracker is None:
                self.tracker = VideoTracker(truth.frames[0])
            elif self.resync:
                self.resync = False
                self.tracker.reseed(truth.frames[0])
            a, b = truth.first_frame, truth.first_frame + truth.n
            seen = self.tracker.process(truth, [e for e in self.events if a <= e[0] < b], keep_frames=True)
            with self._lock:
                self._decoded[name] = truth
                self._det.update(self.tracker.last_detections)
                self.tracker.last_detections.clear()
                for f in [f for f in self._det if f < b - KEEP_FRAMES]:
                    del self._det[f]
                for old in [n for n in self._decoded if n != name and len(self._decoded) > 40]:
                    del self._decoded[old]
                    break
            self.blobs.put(name, encode_chunk(seen))
            self.done += 1
        except Exception as e:  # noqa: BLE001 - a chunk the video model could not read must not stop the match: the analyzer waits, and the next ones go on
            self.failed += 1
            print(f"WARN vision: {name}: {type(e).__name__}: {e}", flush=True)
        finally:
            self.busy_s += time.perf_counter() - t0

    # ----- what the viewer is shown ---------------------------------------------------------------------

    def frame_png(self, frame: int) -> bytes | None:
        """The video frame with what the detector found boxed, or None if that frame has not been processed (yet or any more)."""
        with self._lock:
            det = self._det.get(frame)
            truth = next((c for c in self._decoded.values() if c.first_frame <= frame < c.first_frame + c.n), None)
        if det is None or truth is None:
            return None
        i = frame - truth.first_frame
        img = render_frame(truth.frames[i], truth.ball[i], np.random.default_rng(frame))
        for kind, x, y, r in det.blobs:
            x0, y0, x1, y1 = int(x - r - 1), int(y - r - 1), int(x + r + 1), int(y + r + 1)
            x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, img.shape[1] - 1), min(y1, img.shape[0] - 1)
            col = np.array(BOX[kind], dtype=np.uint8)
            img[y0, x0 : x1 + 1] = col
            img[y1, x0 : x1 + 1] = col
            img[y0 : y1 + 1, x0] = col
            img[y0 : y1 + 1, x1] = col
        return png(img)

    def stats(self) -> dict:
        s = self.tracker.stats.summary() if self.tracker else {}
        return {**s, "chunks": self.done, "skippedChunks": self.skipped, "msPerChunk": round(1000 * self.busy_s / self.done, 1) if self.done else None, "pxPerMetre": PX}

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


__all__ = ["TeeBlobs", "VisionFeed", "to_px"]
