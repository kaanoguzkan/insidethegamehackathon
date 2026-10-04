"""Tracking feed chunks.

Tracking is delivered as 5-second chunks (25 frames at 5 Hz) of gzip JSON, the way low-latency
video is segmented. Positions are integers in decimetres (0.1 m) so chunks stay small; ``null``
marks a player who is off the pitch. A chunk names the player in each of the 22 tracking
slots, so substitutions are visible at chunk boundaries.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SCALE = 10  # decimetres per metre


@dataclass
class Chunk:
    match_id: str
    index: int
    start_ms: int
    hz: int
    slots: list[str]  # player id per tracking slot (0-10 home, 11-21 away)
    frames: np.ndarray  # (n, 22, 2) float32 metres, NaN when off the pitch
    ball: np.ndarray  # (n, 3) float32 metres: x, y, height
    alive: np.ndarray  # (n,) bool: ball in play (False during stoppages and restarts)

    @property
    def n(self) -> int:
        return self.frames.shape[0]

    @property
    def first_frame(self) -> int:
        return round(self.start_ms * self.hz / 1000)


def encode_chunk(chunk: Chunk) -> bytes:
    players = np.where(np.isnan(chunk.frames), np.nan, np.round(chunk.frames * SCALE))
    rows = []
    for fr in players:
        rows.append([None if np.isnan(p[0]) else [int(p[0]), int(p[1])] for p in fr])
    body = {
        "matchId": chunk.match_id,
        "chunk": chunk.index,
        "startMs": chunk.start_ms,
        "hz": chunk.hz,
        "scale": SCALE,
        "slots": chunk.slots,
        "ball": [[int(round(v * SCALE)) for v in b] for b in chunk.ball],
        "alive": [int(a) for a in chunk.alive],
        "players": rows,
    }
    return gzip.compress(json.dumps(body, separators=(",", ":")).encode(), compresslevel=6)


def decode_chunk(data: bytes) -> Chunk:
    body = json.loads(gzip.decompress(data))
    scale = body["scale"]
    n = len(body["players"])
    frames = np.full((n, 22, 2), np.nan, dtype=np.float32)
    for i, row in enumerate(body["players"]):
        for j, p in enumerate(row):
            if p is not None:
                frames[i, j] = (p[0] / scale, p[1] / scale)
    ball = np.array(body["ball"], dtype=np.float32) / scale
    alive = np.array(body.get("alive", [1] * n), dtype=bool)
    return Chunk(
        match_id=body["matchId"],
        index=body["chunk"],
        start_ms=body["startMs"],
        hz=body["hz"],
        slots=body["slots"],
        frames=frames,
        ball=ball,
        alive=alive,
    )


def iter_chunks(result) -> Iterator[Chunk]:
    """Cut a simulated match into tracking chunks (what the simulator job publishes)."""
    n = result.meta["chunkTicks"]
    hz = result.meta["hz"]
    for i in range(len(result.chunk_slots)):
        a, b = i * n, (i + 1) * n
        yield Chunk(
            match_id=result.meta["matchId"],
            index=i,
            start_ms=int(round(a * 1000 / hz)),
            hz=hz,
            slots=result.chunk_slots[i],
            frames=result.frames[a:b],
            ball=result.ball[a:b, :3],
            alive=result.ball[a:b, 3] > 0.5,
        )


def write_chunks(result, outdir: Path) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    count = 0
    for ch in iter_chunks(result):
        (outdir / f"{ch.index:05d}.json.gz").write_bytes(encode_chunk(ch))
        count += 1
    return count


def read_chunks(indir: Path) -> Iterator[Chunk]:
    for p in sorted(indir.glob("*.json.gz")):
        yield decode_chunk(p.read_bytes())
