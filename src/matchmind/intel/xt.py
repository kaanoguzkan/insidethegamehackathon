"""Expected threat (xT): how valuable it is to have the ball in each part of the pitch.

The grid is *fitted* from simulated league data with the standard iterative method (value of
a zone = probability of shooting there x probability of scoring + probability of moving the
ball x expected value of where it goes). Until a fitted grid is available the analytic
surface in ``core.models.threat`` is used, so the interpreter always has a value function.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ..core import geometry as G
from ..core.models import threat, xg

NX, NY = 12, 8


class XTGrid:
    def __init__(self, grid: np.ndarray | None = None) -> None:
        self.grid = grid

    def value(self, ax: float, ay: float) -> float:
        if self.grid is None:
            return threat(ax, ay)
        ix, iy = G.zone(ax, ay, NX, NY)
        return float(self.grid[iy, ix])

    def to_dict(self) -> dict:
        return {"nx": NX, "ny": NY, "grid": None if self.grid is None else np.round(self.grid, 5).tolist()}

    @classmethod
    def from_dict(cls, d: dict) -> XTGrid:
        return cls(None if d.get("grid") is None else np.array(d["grid"], dtype=float))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict()) + "\n")

    @classmethod
    def load(cls, path: Path | None) -> XTGrid:
        if path is not None and path.exists():
            return cls.from_dict(json.loads(path.read_text()))
        return cls(None)


def _attack_xy(e: dict, key: str, dirs: dict) -> tuple[float, float] | None:
    p = e.get(key)
    if not p:
        return None
    d = dirs[e["clock"]["period"]][e["team"]]
    return G.to_att(p["x"], p["y"], d)


def fit_xt(matches: list[tuple[list[dict], dict]], iterations: int = 5) -> XTGrid:
    """Fit a grid from ``[(events, meta), ...]``."""
    shots = np.zeros((NY, NX))
    goals = np.zeros((NY, NX))
    moves = np.zeros((NY, NX))
    trans = np.zeros((NY, NX, NY, NX))

    for events, meta in matches:
        dirs = {p["period"]: p["attackDirection"] for p in meta["periods"]}
        for e in events:
            t = e["type"]
            if t not in ("pass", "carry", "dribble", "shot"):
                continue
            a = _attack_xy(e, "location", dirs)
            if a is None:
                continue
            ix, iy = G.zone(a[0], a[1], NX, NY)
            if t == "shot":
                shots[iy, ix] += 1
                goals[iy, ix] += 1 if e.get("outcome") == "goal" else 0
                continue
            if e.get("outcome") != "complete":
                moves[iy, ix] += 1  # a failed move still counts as an attempted move
                continue
            b = _attack_xy(e, "end", dirs)
            if b is None:
                continue
            jx, jy = G.zone(b[0], b[1], NX, NY)
            moves[iy, ix] += 1
            trans[iy, ix, jy, jx] += 1

    total = shots + moves
    total = np.where(total == 0, 1, total)
    p_shot = shots / total
    p_move = moves / total
    p_goal = np.where(shots > 0, goals / np.maximum(shots, 1), 0.0)
    # Cells with few shots borrow the analytic xG so the grid stays smooth.
    centre_x = (np.arange(NX) + 0.5) * G.PITCH_L / NX
    centre_y = (np.arange(NY) + 0.5) * G.PITCH_W / NY
    prior = np.array([[xg(x, y) for x in centre_x] for y in centre_y])
    weight = np.minimum(1.0, shots / 8.0)
    p_goal = weight * p_goal + (1 - weight) * prior

    move_prob = np.where(moves[..., None, None] > 0, trans / np.maximum(moves, 1)[..., None, None], 0.0)
    v = np.zeros((NY, NX))
    for _ in range(iterations):
        future = (move_prob * v[None, None, :, :]).sum(axis=(2, 3))
        v = p_shot * p_goal + p_move * future
    # Zones nobody ever played from get the analytic value.
    unseen = (shots + moves) == 0
    analytic = np.array([[threat(x, y) for x in centre_x] for y in centre_y])
    v = np.where(unseen, analytic, v)
    return XTGrid(v)
