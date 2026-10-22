"""Does the interpreter find a change it was not told about, now that teams change shape with the ball?

Slow: each case simulates and interprets whole matches. The thresholds behind these numbers come from
the studies in docs/metrics.md.
"""

from __future__ import annotations

import pytest

from forced import LINE_UP, PRESS_OFF, Forced
from matchmind.core.paths import league_dir
from matchmind.intel.baselines import load_baselines
from matchmind.intel.pipeline import interpret_match
from matchmind.intel.xt import XTGrid
from matchmind.sim.league import load_league

pytestmark = pytest.mark.slow

MIN = 60_000


def _moments(home: str, away: str, seed: int, changes: list) -> list[dict]:
    """The moments found in a match in which the managers are off and exactly ``changes`` happen (none: the control)."""
    clubs = load_league(league_dir() / "league.json")
    res = Forced("d", clubs[home], clubs[away], seed=seed, changes=changes).run()
    _, out = interpret_match(res, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"))
    return out.moments


def test_the_pressing_collapse_is_found_and_never_invented():
    found = false_alarms = 0
    for seed in range(100, 108):
        forced = [m for m in _moments("HAR", "NOR", seed, [(55, 1, PRESS_OFF, None)]) if m["type"] == "pressure_collapse" and m["subjectTeam"] == "NOR"]
        found += any(m["detectedAt"]["matchMs"] >= 55 * MIN for m in forced)
        controls = _moments("HAR", "NOR", seed, [])
        false_alarms += any(m["type"] == "pressure_collapse" and m["subjectTeam"] == "NOR" for m in controls)
    assert found >= 6, f"found the collapse in only {found}/8 seeds"
    assert false_alarms == 0


def test_a_shape_change_is_found_and_possession_swings_are_not_mistaken_for_one():
    # The line change ALD make at 60:00 ...
    found = 0
    for seed in range(300, 306):
        ms = _moments("KES", "ALD", seed, [(60, 1, LINE_UP, "3-4-3")])
        found += any(m["type"] == "tactical_shift" and m["subjectTeam"] == "ALD" and 60 * MIN <= m["detectedAt"]["matchMs"] <= 78 * MIN for m in ms)
    assert found >= 4, f"found the shift in only {found}/6 seeds"
    # ... while ordinary matches, where the teams breathe in and out with the ball, stay quiet.
    clubs = load_league(league_dir() / "league.json")
    per_match = []
    for seed, (h, a) in zip(range(200, 206), (("HAR", "NOR"), ("RED", "KES"), ("ALD", "SAL"), ("NOR", "ALD"), ("KES", "HAR"), ("SAL", "RED")), strict=True):
        res = Forced("q", clubs[h], clubs[a], seed=seed).run()  # the managers off: this control is about how the teams breathe with the ball, not about what a manager does
        _, out = interpret_match(res, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"))
        per_match.append(sum(m["type"] == "tactical_shift" for m in out.moments))
    assert sum(per_match) / len(per_match) <= 2.0, per_match
