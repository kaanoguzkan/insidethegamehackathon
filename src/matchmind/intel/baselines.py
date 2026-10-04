"""League baselines for the explainability indices.

Chaos and pressure are z-scored against what a typical five minutes of *this league* looks
like. The baselines are measured, not assumed: simulate matches, slide a five-minute window
across each, and take the mean and spread of every ingredient. ``matchmind build-league-data``
writes the result to ``data/league/baselines.json``.
"""

from __future__ import annotations

import itertools
import json
import math
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from ..core.paths import league_dir
from ..sim.engine import simulate
from ..sim.league import generate_league
from .config import MINUTE
from .pipeline import interpret_match

NAMES = (
    "turnovers_per_min", "duels_per_min", "long_ball_share", "avg_possession_s",
    "log_ppda", "pressures_per_min", "high_regains", "tempo",
)  # fmt: skip


def _samples_for_match(args: tuple[int, str, str, int]) -> dict[str, list[float]]:
    i, home, away, seed = args
    clubs = generate_league()
    res = simulate(f"b{i:04d}", clubs[home], clubs[away], seed=seed)
    ip, _ = interpret_match(res, baselines={})
    cfg = ip.cfg
    out: dict[str, list[float]] = {n: [] for n in NAMES}
    end = int(res.meta["frames"] * 200)
    for t in range(cfg.window_ms, end, MINUTE):
        w = ip.window(t - cfg.window_ms, t)
        m = w["match"]
        for key in ("turnovers_per_min", "duels_per_min", "long_ball_share", "avg_possession_s"):
            if m[key] is not None:
                out[key].append(m[key])
        for c in ip.clubs:
            tw = w[c]
            if tw["ppda"] is not None and tw["opp_build_passes"] >= 6:
                out["log_ppda"].append(math.log(max(tw["ppda"], 0.5)))
            out["pressures_per_min"].append(tw["pressures_per_min"])
            out["high_regains"].append(tw["high_regains"])
            if tw["tempo"] is not None:
                out["tempo"].append(tw["tempo"])
    return out


def compute_baselines(n_matches: int = 24, workers: int | None = None, seed0: int = 5000) -> dict[str, list[float]]:
    clubs = list(generate_league())
    pairs = [(h, a) for h, a in itertools.product(clubs, clubs) if h != a]
    jobs = [(i, *pairs[i % len(pairs)], seed0 + i) for i in range(n_matches)]
    if workers == 1:
        parts = [_samples_for_match(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            parts = list(ex.map(_samples_for_match, jobs))
    merged: dict[str, list[float]] = {n: [] for n in NAMES}
    for p in parts:
        for n in NAMES:
            merged[n].extend(p[n])
    return {
        n: [round(float(np.mean(v)), 4), round(float(np.std(v)) or 1.0, 4)] for n, v in merged.items()
    }


def load_baselines(path: Path | None = None) -> dict[str, list[float]]:
    path = path or league_dir() / "baselines.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}
