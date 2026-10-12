"""Match packs: a simulated match, stored once, played any number of times.

Simulating a match takes tens of seconds on a small container; playing one should take a moment. A **pack** is everything the live feed needs of a finished
simulation, in the compact forms the project already has: the metadata, the full event list (gzip JSON), and the tracking as the single-file bundle used by
replay packages (``bundle.py``: int16 decimetres, gzip, about 1.7 MB for a whole match) with its substitution table. From a pack the player builds the feed
documents and the five-second tracking chunks exactly as ``feed.build_feed`` / ``feed.build_chunks`` would from the simulation itself, so starting a match
costs a few blob reads instead of a simulation. Chunks are cut and encoded when they are due, not all at once.

Layout in the ``packs`` container, one folder per fixture: ``<prefix>/meta.json``, ``events.json.gz``, ``tracking.bin.gz``, ``slots.json``.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from ..tracking import bundle
from ..tracking.frames import Chunk, encode_chunk
from .blobs import Blobs
from .feed import build_feed, chunk_name, jsonable


@dataclass
class Pack:
    meta: dict
    events: list[dict]
    pos: np.ndarray  # (frames, 22, 2) metres, NaN while a player is off the pitch
    ball: np.ndarray  # (frames, 4) x, y, height, in-play flag
    slots: list[dict]  # [{fromFrame, ids}]: who occupies the 22 tracking slots from which frame

    @property
    def match_id(self) -> str:
        return self.meta["matchId"]

    @property
    def per_chunk(self) -> int:
        return int(self.meta["chunkTicks"])

    @property
    def hz(self) -> int:
        return int(self.meta["hz"])

    @property
    def n_chunks(self) -> int:
        return -(-len(self.pos) // self.per_chunk)

    def _slots_at(self, frame: int) -> list[str]:
        ids = self.slots[0]["ids"]
        for row in self.slots:
            if row["fromFrame"] <= frame:
                ids = row["ids"]
            else:
                break
        return ids

    def chunk(self, index: int, match_id: str | None = None) -> Chunk:
        a, b = index * self.per_chunk, min((index + 1) * self.per_chunk, len(self.pos))
        return Chunk(
            match_id=match_id or self.match_id, index=index, start_ms=int(round(a * 1000 / self.hz)), hz=self.hz, slots=self._slots_at(a),
            frames=self.pos[a:b], ball=self.ball[a:b, :3], alive=self.ball[a:b, 3] > 0.5,
        )

    def chunks(self, match_id: str | None = None) -> LazyChunks:
        return LazyChunks(self, match_id or self.match_id)

    def feed(self, match_id: str | None = None) -> list[dict]:
        """The feed documents (events only; the physical facts come from the chunks), as ``feed.build_feed(result, physical="chunks")`` makes them."""

        return build_feed(SimpleNamespace(events=self.events), physical="chunks")  # build_feed reads only ``events`` from a simulation result


class LazyChunks:
    """The match's tracking chunks as the playback loop reads them: ``(end ms, blob name, gzip JSON)`` by index, encoded when asked for."""

    def __init__(self, pack: Pack, match_id: str) -> None:
        self.pack, self.match_id = pack, match_id
        self._last: tuple[int, tuple[int, str, bytes]] | None = None

    def __len__(self) -> int:
        return self.pack.n_chunks

    def __getitem__(self, i: int) -> tuple[int, str, bytes]:
        if self._last is not None and self._last[0] == i:
            return self._last[1]
        ch = self.pack.chunk(i, self.match_id)
        item = (ch.start_ms + ch.n * 1000 // ch.hz, chunk_name(self.match_id, i), encode_chunk(ch))
        self._last = (i, item)
        return item


def write_pack(blobs: Blobs, prefix: str, result) -> int:  # noqa: ANN001
    """Store a finished simulation as a pack. Returns the bytes written."""
    events = gzip.compress(json.dumps(jsonable(result.events), separators=(",", ":")).encode(), compresslevel=6, mtime=0)
    meta = json.dumps(jsonable(result.meta), separators=(",", ":")).encode()
    tracking = bundle.encode(result)
    slots = json.dumps(bundle.slot_table(result), separators=(",", ":")).encode()
    for name, data in (("meta.json", meta), ("events.json.gz", events), ("tracking.bin.gz", tracking), ("slots.json", slots)):
        blobs.put(f"{prefix}/{name}", data)
    return len(meta) + len(events) + len(tracking) + len(slots)


def read_pack(blobs: Blobs, prefix: str) -> Pack | None:
    """A pack from storage, or None if any part is missing (a pack that is still being written is not played)."""
    parts = [blobs.get(f"{prefix}/{n}") for n in ("meta.json", "events.json.gz", "tracking.bin.gz", "slots.json")]
    if any(p is None for p in parts):
        return None
    meta_b, events_b, tracking_b, slots_b = parts
    pos, ball, _ = bundle.decode(tracking_b)  # type: ignore[arg-type]
    return Pack(json.loads(meta_b), json.loads(gzip.decompress(events_b)), pos, ball, json.loads(slots_b))  # type: ignore[arg-type]
