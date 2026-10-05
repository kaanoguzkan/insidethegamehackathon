"""Fit the analytics models from simulated matches: ``matchmind fit-models``.

Matches are simulated and interpreted exactly as in production, so the models see the same normalised
events (with measured xG) that they will score. Everything fitted is written to
``data/league/models.json`` together with in-sample diagnostics, which ``docs/analytics.md`` quotes.
"""

from __future__ import annotations

import itertools
from concurrent.futures import ProcessPoolExecutor

from ..core.paths import league_dir
from ..intel.baselines import load_baselines
from ..intel.pipeline import interpret_match
from ..intel.xt import XTGrid
from ..sim.engine import simulate
from ..sim.league import load_league
from . import vaep, xgot
from .store import load_models, save_models
from .winprob import DEFAULTS, WinProbModel

SEED0 = 20000


def _simulate(args: tuple[int, str, str, int]) -> tuple[list[dict], dict]:
    i, home, away, seed = args
    clubs = load_league(league_dir() / "league.json")
    res = simulate(f"f{i:04d}", clubs[home], clubs[away], seed=seed)
    ip, _ = interpret_match(res, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"))
    return ip.events, res.meta


def simulate_matches(n: int, workers: int | None = None, seed0: int = SEED0) -> list[tuple[list[dict], dict]]:
    ids = list(load_league(league_dir() / "league.json"))
    pairs = [(h, a) for h, a in itertools.product(ids, ids) if h != a]
    jobs = [(i, *pairs[i % len(pairs)], seed0 + i) for i in range(n)]
    if workers == 1:
        return [_simulate(j) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(_simulate, jobs))


def fit_winprob(matches: list[tuple[list[dict], dict]]) -> tuple[dict, dict]:
    goals = minutes = 0.0
    for events, _meta in matches:
        goals += sum(1 for e in events if e["type"] == "goal")
        minutes += 2 * max(e["_ms"] for e in events) / 60000.0
    params = dict(DEFAULTS)
    params["goal_rate"] = round(goals / minutes, 5)
    params["match_minutes"] = round(minutes / (2 * len(matches)), 2)
    model = WinProbModel(params)

    # Brier score at 60 and 75 minutes against always predicting the pre-match odds.
    diag: dict = {"matches": len(matches), "goal_rate": params["goal_rate"], "match_minutes": params["match_minutes"]}
    for minute in (30, 60, 75):
        brier = base = 0.0
        for events, meta in matches:
            clubs = [meta["home"]["id"], meta["away"]["id"]]
            ser = model.series(events, clubs, max(e["_ms"] for e in events), step_ms=60_000)
            pt = next(p for p in ser if p["tag"] == "tick" and p["matchMs"] == minute * 60_000)
            final = [0, 0]
            for e in events:
                if e["type"] == "goal":
                    final[clubs.index(e["team"])] += 1
            actual = {"home": final[0] > final[1], "draw": final[0] == final[1], "away": final[0] < final[1]}
            prior = model.state_probabilities(0.0, (0, 0), (0.0, 0.0), (0, 0))
            brier += sum((pt["p"][k] - float(actual[k])) ** 2 for k in actual)
            base += sum((prior[k] - float(actual[k])) ** 2 for k in actual)
        n = len(matches)
        diag[f"brier_{minute}"] = round(brier / n, 4)
        diag[f"brier_prior_{minute}"] = round(base / n, 4)
    return params, diag


def fit_models(n_matches: int = 60, workers: int | None = None, seed0: int = SEED0, matches: list | None = None) -> dict:
    matches = matches if matches is not None else simulate_matches(n_matches, workers, seed0)
    n_matches = len(matches)
    wp, wp_diag = fit_winprob(matches)
    vp, vp_diag = vaep.fit(matches)
    xg, xg_diag = xgot.fit(matches)
    return {
        "version": 1,
        "fittedOn": n_matches,
        "winprob": wp,
        "vaep": vp,
        "xgot": xg,
        "diagnostics": {"winprob": wp_diag, "vaep": vp_diag, "xgot": xg_diag},
    }


__all__ = ["fit_models", "save_models", "load_models", "simulate_matches"]
