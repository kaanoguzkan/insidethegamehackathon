"""Realism calibration for the synthetic data.

Simulates many matches and compares league averages with target bands taken from typical
top-flight football. The point is to make the claim "this data is football-realistic"
measurable: the report is printed by ``matchmind report-realism`` and checked in CI, so a
code change that makes matches unrealistic fails loudly.

The bands are deliberately wide; they describe a plausible league, not any real one.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

import numpy as np

from .engine import DT, MatchResult, simulate
from .league import generate_league

SPRINT_MS = 25.0 / 3.6  # 25 km/h

# name: (low, high, description). Values are per match unless noted.
BANDS: dict[str, tuple[float, float, str]] = {
    "goals": (2.4, 3.2, "goals, both teams"),
    "shots": (20.0, 30.0, "shots, both teams"),
    "shots_on_target": (6.5, 11.5, "shots on target (incl. goals), both teams"),
    "passes": (850.0, 1150.0, "passes, both teams"),
    "pass_completion": (0.78, 0.86, "pass completion"),
    "possession_share": (0.35, 0.65, "possession share per team (mean of the larger share)"),
    "distance_km": (9.5, 12.0, "distance per outfield starter, km"),
    "top_speed_kmh": (31.0, 36.5, "fastest player speed in the match, km/h"),
    "sprints_per_team": (35.0, 120.0, "sprints (>= 25 km/h for 1 s), per team"),
    "tackles": (28.0, 55.0, "tackles, both teams"),
    "interceptions": (14.0, 40.0, "interceptions, both teams"),
    "fouls": (18.0, 30.0, "fouls, both teams"),
    "corners": (7.0, 14.0, "corners, both teams"),
    "throw_ins": (60.0, 110.0, "throw-ins, both teams"),
    "goal_kicks": (12.0, 28.0, "goal kicks, both teams"),
    "clearances": (28.0, 70.0, "clearances, both teams"),
    "offsides": (3.0, 11.0, "offsides, both teams"),
    "yellow_cards": (1.5, 5.5, "yellow cards, both teams"),
    "pressures": (200.0, 520.0, "pressure events, both teams"),
}


def match_stats(res: MatchResult) -> dict[str, float]:
    ev = res.events
    c = Counter(e["type"] for e in ev)
    shots = [e for e in ev if e["type"] == "shot"]
    passes = [e for e in ev if e["type"] == "pass"]
    complete = sum(1 for e in passes if e.get("outcome") == "complete")
    cards = Counter(e.get("outcome") for e in ev if e["type"] == "card")

    # Possession: time between the first and last event of each possession, by team.
    spans: dict[str, list] = {}
    for e in ev:
        pid = e.get("possessionId")
        if pid and e["type"] in ("pass", "carry", "shot", "dribble", "clearance"):
            s = spans.setdefault(pid, [e["team"], e["clock"]["matchMs"], e["clock"]["matchMs"]])
            s[2] = e["clock"]["matchMs"]
    poss = Counter()
    for team, a, b in spans.values():
        poss[team] += (b - a) + 2000
    total = sum(poss.values()) or 1
    share = max(poss.values()) / total if poss else 0.5

    frames = res.frames.astype(np.float64)
    step = np.diff(frames, axis=0)
    speed = np.hypot(step[..., 0], step[..., 1]) / DT  # (n-1, 22)
    for m in res.meta["periods"]:
        if m["period"] > 1:  # players are repositioned at the break, not running
            speed[m["startFrame"] - 1] = np.nan
    # Light smoothing, as a tracking provider would apply.
    k = np.ones(3) / 3
    sm = np.apply_along_axis(lambda v: np.convolve(np.nan_to_num(v), k, mode="same"), 0, speed)
    top = float(np.nanmax(np.where(np.isfinite(speed), sm, 0.0))) * 3.6
    starters = [p for side in ("home", "away") for p in res.meta[side]["lineup"][1:]]
    dist_starters = [res.stats["distance_km"].get(p, 0.0) for p in starters]
    sprint_counts = []
    for team in (0, 1):
        n = 0
        for i in range(team * 11 + 1, team * 11 + 11):
            above = sm[:, i] >= SPRINT_MS
            run = 0
            for flag in above:
                if flag:
                    run += 1
                    if run == 5:
                        n += 1
                else:
                    run = 0
        sprint_counts.append(n)

    return {
        "goals": float(c["goal"]),
        "shots": float(len(shots)),
        "shots_on_target": float(sum(1 for e in shots if e.get("outcome") in ("goal", "saved"))),
        "passes": float(len(passes)),
        "pass_completion": complete / max(1, len(passes)),
        "possession_share": share,
        "distance_km": float(np.mean(dist_starters)),
        "top_speed_kmh": top,
        "sprints_per_team": float(np.mean(sprint_counts)),
        "tackles": float(c["tackle"]),
        "interceptions": float(c["interception"]),
        "fouls": float(c["foul"]),
        "corners": float(c["corner"]),
        "throw_ins": float(c["throw_in"]),
        "goal_kicks": float(c["goal_kick"]),
        "clearances": float(c["clearance"]),
        "offsides": float(c["offside"]),
        "yellow_cards": float(cards["yellow"]),
        "pressures": float(c["pressure"]),
    }


def _worker(args: tuple[int, str, str, int]) -> dict[str, float]:
    i, home, away, seed = args
    clubs = generate_league()
    res = simulate(f"r{i:04d}", clubs[home], clubs[away], seed=seed)
    return match_stats(res)


def fixtures(n: int, seed0: int = 1000) -> list[tuple[int, str, str, int]]:
    clubs = list(generate_league())
    pairs = [(h, a) for h, a in itertools.product(clubs, clubs) if h != a]
    return [(i, *pairs[i % len(pairs)], seed0 + i) for i in range(n)]


def run_realism(n: int = 40, workers: int | None = None) -> dict[str, list[float]]:
    jobs = fixtures(n)
    if workers == 1:
        rows = [_worker(j) for j in jobs]
    else:
        with ProcessPoolExecutor(max_workers=workers) as ex:
            rows = list(ex.map(_worker, jobs))
    return {k: [r[k] for r in rows] for k in rows[0]}


@dataclass
class Row:
    name: str
    mean: float
    low: float
    high: float
    ok: bool
    desc: str


def evaluate(samples: dict[str, list[float]]) -> list[Row]:
    rows = []
    for name, (lo, hi, desc) in BANDS.items():
        mean = float(np.mean(samples[name]))
        rows.append(Row(name, mean, lo, hi, lo <= mean <= hi, desc))
    return rows


def format_report(rows: list[Row], n: int) -> str:
    out = [f"Realism report over {n} simulated matches", ""]
    out.append(f"{'metric':<18}{'mean':>10}   {'target band':<16}  ")
    for r in rows:
        band = f"{r.low:g}-{r.high:g}"
        flag = "ok" if r.ok else ("LOW" if r.mean < r.low else "HIGH")
        out.append(f"{r.name:<18}{r.mean:>10.2f}   {band:<16}  {flag:<5} {r.desc}")
    failing = [r.name for r in rows if not r.ok]
    out += ["", "all within bands" if not failing else f"outside bands: {', '.join(failing)}"]
    return "\n".join(out)


def _isfinite(x: float) -> bool:
    return not (math.isnan(x) or math.isinf(x))
