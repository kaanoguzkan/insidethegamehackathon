"""Does the interpreter still find the scripted stories now that teams change shape with the ball?

Slow: each case simulates and interprets whole matches. The thresholds behind these numbers come from
the studies in docs/metrics.md.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from matchmind.core.paths import league_dir, scenarios_dir
from matchmind.intel.baselines import load_baselines
from matchmind.intel.pipeline import interpret_match
from matchmind.intel.xt import XTGrid
from matchmind.sim.engine import simulate
from matchmind.sim.league import load_league
from matchmind.sim.scenarios import load_scenario

pytestmark = pytest.mark.slow

MIN = 60_000


def _moments(scenario: str, seed: int, *, scripted: bool = True) -> list[dict]:
    clubs = load_league(league_dir() / "league.json")
    sc = load_scenario(scenarios_dir() / f"{scenario}.yaml")
    if not scripted:
        sc = replace(sc, script=[])
    res = simulate("d", clubs[sc.home], clubs[sc.away], seed=seed, scenario=sc)
    _, out = interpret_match(res, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"))
    return out.moments


def test_the_pressing_collapse_is_found_and_never_invented():
    found = false_alarms = 0
    for seed in range(100, 108):
        scripted = [m for m in _moments("pressing-collapse", seed) if m["type"] == "pressure_collapse" and m["subjectTeam"] == "NOR"]
        found += any(m["detectedAt"]["matchMs"] >= 55 * MIN for m in scripted)
        controls = _moments("pressing-collapse", seed, scripted=False)
        false_alarms += any(m["type"] == "pressure_collapse" and m["subjectTeam"] == "NOR" for m in controls)
    assert found >= 6, f"found the collapse in only {found}/8 seeds"
    assert false_alarms == 0


def test_a_shape_change_is_found_and_possession_swings_are_not_mistaken_for_one():
    # The scripted line change by ALD at 60:00 ...
    found = 0
    for seed in range(300, 306):
        ms = _moments("high-line-gamble", seed)
        found += any(m["type"] == "tactical_shift" and m["subjectTeam"] == "ALD" and 60 * MIN <= m["detectedAt"]["matchMs"] <= 78 * MIN for m in ms)
    assert found >= 4, f"found the shift in only {found}/6 seeds"
    # ... while ordinary matches, where the teams breathe in and out with the ball, stay quiet.
    clubs = load_league(league_dir() / "league.json")
    per_match = []
    for seed, (h, a) in zip(range(200, 206), (("HAR", "NOR"), ("RED", "KES"), ("ALD", "SAL"), ("NOR", "ALD"), ("KES", "HAR"), ("SAL", "RED")), strict=True):
        res = simulate("q", clubs[h], clubs[a], seed=seed)
        _, out = interpret_match(res, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"))
        per_match.append(sum(m["type"] == "tactical_shift" for m in out.moments))
    assert sum(per_match) / len(per_match) <= 2.0, per_match
