"""The video model's reading of a demo match, done once and shared by every viewer.

A demo match is deterministic, so what the video model sees in it is the same for everyone: the same frames, the same detections, the same rebuilt tracking.
Reading it once per viewer made the video stage the most expensive thing a viewer cost (about a tenth of a core each, and several times that on the Container
App). One worker per demo now reads the match chunk by chunk, in the background, and keeps the rebuilt chunks; a viewer's session takes them as they are ready
(and the provider's own tracking for any chunk the worker has not reached yet), so the cost depends on the number of demos, not of viewers.
"""

from __future__ import annotations

import json
import os
import re
import struct
import threading
import time
from pathlib import Path

from ..tracking.frames import Chunk, decode_chunk, encode_chunk
from .track import VideoTracker, VisionStats

BAKE_VERSION = 2
MAGIC = b"MMV2"
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
PAUSE_S = 0.04  # a breath between chunks: the worker must never starve the matches that are being played


class SharedVision:
    def __init__(self, demo_id: str, truth: list[tuple[int, str, bytes]], events: list[tuple[int, str, float, float]]) -> None:
        self.demo_id = demo_id
        self.truth = truth  # (end ms, name, bytes) per chunk, in order
        self.events = events
        self.results: dict[int, bytes] = {}
        self.tracker: VideoTracker | None = None
        self.busy_s = 0.0
        self.failed = 0
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.baked = False
        self._stats: dict = {}
        self._load_baked()

    # ----- a reading done ahead of time (data/vision/<demo>.mmv, made by `matchmind vision-bake` and copied into the image) ---------------

    @staticmethod
    def baked_path(demo_id: str) -> Path:
        root = Path(os.environ.get("MATCHMIND_DATA") or Path(__file__).resolve().parents[3] / "data")
        if not SAFE_ID.match(demo_id):
            raise ValueError(f"invalid demo id {demo_id!r}")
        return root / "vision" / f"{demo_id}.mmv"

    def _load_baked(self) -> None:
        path = self.baked_path(self.demo_id)
        try:
            if not path.exists():
                return
            data = path.read_bytes()  # a plain container, not a pickle: a JSON header, then the chunks one after another, each as long as the header says
            if data[:4] != MAGIC:
                return
            (hl,) = struct.unpack(">I", data[4:8])
            head = json.loads(data[8 : 8 + hl])
            sizes = head["sizes"]
            if head.get("version") == BAKE_VERSION and len(sizes) == len(self.truth) and 8 + hl + sum(sizes) == len(data):
                at, results = 8 + hl, {}
                for i, n in enumerate(sizes):
                    results[i] = data[at : at + n]
                    at += n
                self.results, self._stats, self.baked = results, head["stats"], True
        except Exception as e:  # noqa: BLE001 - a file that does not load is as good as none: the worker reads the demo
            print(f"WARN vision baked {path.name}: {type(e).__name__}: {e}", flush=True)

    def run_all(self) -> None:
        """Read the whole demo now, in this thread (what `vision-bake` does)."""
        self._run(pause=0.0)

    def dump(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        chunks = [self.results[i] for i in range(len(self.truth))]
        head = json.dumps({"version": BAKE_VERSION, "demo": self.demo_id, "stats": self.stats(), "sizes": [len(c) for c in chunks]}, separators=(",", ":")).encode()
        path.write_bytes(MAGIC + struct.pack(">I", len(head)) + head + b"".join(chunks))

    # ----- the worker -----------------------------------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self._thread is None and not self.baked:
                self._thread = threading.Thread(target=self._run, name=f"vision-{self.demo_id}", daemon=True)
                self._thread.start()

    def _run(self, pause: float = PAUSE_S) -> None:
        for i, (_, _name, data) in enumerate(self.truth):
            if self._stop.is_set():
                return
            t0 = time.perf_counter()
            try:
                chunk = decode_chunk(data)
                if self.tracker is None:
                    self.tracker = VideoTracker(chunk.frames[0])
                a, b = chunk.first_frame, chunk.first_frame + chunk.n
                seen: Chunk = self.tracker.process(chunk, [e for e in self.events if a <= e[0] < b])
                self.results[i] = encode_chunk(seen)
            except Exception as e:  # noqa: BLE001 - a chunk the model could not read is the provider's chunk for everyone; the worker carries on
                self.failed += 1
                print(f"WARN vision {self.demo_id} chunk {i}: {type(e).__name__}: {e}", flush=True)
                if self.tracker is not None:
                    self.tracker.reseed(decode_chunk(data).frames[0])
            self.busy_s += time.perf_counter() - t0
            if pause:
                time.sleep(pause)

    def stop(self) -> None:
        self._stop.set()

    # ----- what a viewer's session takes ----------------------------------------------------------------

    def get(self, index: int) -> bytes | None:
        return self.results.get(index)

    def wait(self, index: int, timeout_s: float) -> bytes | None:
        """The rebuilt chunk, waiting a moment for the worker if it is about to finish it. A chunk well ahead of the worker is not waited for at all."""
        deadline = time.monotonic() + timeout_s
        while True:
            got = self.results.get(index)
            if got is not None or self._stop.is_set() or index > len(self.results) + 1 or time.monotonic() >= deadline:
                return got
            time.sleep(0.05)

    def stats(self) -> dict:
        if self.baked:
            return {**self._stats, "chunks": len(self.results), "of": len(self.truth), "msPerChunk": 0.0, "baked": True}
        s: VisionStats | None = self.tracker.stats if self.tracker else None
        done = len(self.results)
        return {**(s.summary() if s else {}), "chunks": done, "of": len(self.truth), "msPerChunk": round(1000 * self.busy_s / done, 1) if done else None}


_SHARED: dict[str, SharedVision] = {}
_LOCK = threading.Lock()


def shared_for(demo_id: str, truth: list[tuple[int, str, bytes]], events: list[tuple[int, str, float, float]]) -> SharedVision:
    """The one reader of a demo (made, and started, the first time it is asked for)."""
    with _LOCK:
        sv = _SHARED.get(demo_id)
        if sv is None:
            sv = _SHARED[demo_id] = SharedVision(demo_id, truth, events)
        sv.start()
        return sv


def reset() -> None:
    """Stop and forget every shared reader (tests)."""
    with _LOCK:
        for sv in _SHARED.values():
            sv.stop()
        _SHARED.clear()
