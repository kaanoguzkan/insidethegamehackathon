"""Single-file tracking bundle for replay packages.

The live system streams 5-second chunks. A finished match served from static hosting is better
as one file: 16-byte header, then little-endian ``int16`` decimetres, gzip-compressed.

    header   magic "MMT1", version u8, hz u8, reserved u16, frames u32, players u8, reserved 3 bytes
    players  int16[frames * 22 * 2]   x, y in 0.1 m; -32768 while a player is off the pitch
    ball     int16[frames * 4]        x, y, height in 0.1 m, then 1 while the ball is in play

``slots.json`` (next to it) says which player id occupies each of the 22 slots from which frame,
so substitutions are visible. The browser decodes it with ``DecompressionStream('gzip')``.
"""

from __future__ import annotations

import gzip
import json
import struct
from pathlib import Path

import numpy as np

MAGIC = b"MMT1"
OFF = -32768
HEADER = struct.Struct("<4sBBHIB3x")


def encode(result) -> bytes:
    n = result.meta["frames"]
    pos = np.where(np.isnan(result.frames[:n]), OFF, np.round(result.frames[:n] * 10)).astype("<i2")
    ball = result.ball[:n]
    b = np.stack([np.round(ball[:, 0] * 10), np.round(ball[:, 1] * 10), np.round(ball[:, 2] * 10), (ball[:, 3] > 0.5).astype(float)], axis=1).astype("<i2")
    head = HEADER.pack(MAGIC, 1, result.meta["hz"], 0, n, 22)
    return gzip.compress(head + pos.tobytes() + b.tobytes(), compresslevel=9)


def slot_table(result) -> list[dict]:
    """Run-length list of ``{fromFrame, ids}``: a new row only when a substitution changes a slot."""
    out: list[dict] = []
    per = result.meta["chunkTicks"]
    for i, ids in enumerate(result.chunk_slots):
        if not out or out[-1]["ids"] != ids:
            out.append({"fromFrame": i * per, "ids": list(ids)})
    return out


def write(result, outdir: Path) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    data = encode(result)
    (outdir / "tracking.bin.gz").write_bytes(data)
    (outdir / "slots.json").write_text(json.dumps(slot_table(result), separators=(",", ":")) + "\n")
    return len(data)


def decode(data: bytes) -> tuple[np.ndarray, np.ndarray, int]:
    """Back to ``(positions (n,22,2) metres with NaN, ball (n,4), hz)``."""
    raw = gzip.decompress(data)
    magic, version, hz, _, n, players = HEADER.unpack_from(raw)
    if magic != MAGIC or version != 1 or players != 22:
        raise ValueError("not a MatchMind tracking bundle")
    off = HEADER.size
    pos = np.frombuffer(raw, dtype="<i2", count=n * 22 * 2, offset=off).reshape(n, 22, 2).astype(np.float32)
    off += n * 22 * 2 * 2
    ball = np.frombuffer(raw, dtype="<i2", count=n * 4, offset=off).reshape(n, 4).astype(np.float32)
    pos = np.where(pos == OFF, np.nan, pos / 10.0)
    ball = np.concatenate([ball[:, :3] / 10.0, ball[:, 3:]], axis=1)
    return pos, ball, hz
