"""The managers: sides that react to the score, the clock and the numbers on the pitch, with nothing scripted."""

from __future__ import annotations

import pytest

from forced import Forced
from matchmind.sim.engine import MatchSim, simulate
from matchmind.sim.manager import LAST_CALL, attacking_weight


def sim_at(clubs, minute: float, *, score=(0, 0), seed: int = 3) -> MatchSim:
    """A match paused at a display minute of the second half, with both managers eager (so the test sees the rule, not the dice)."""
    m = MatchSim("mg", clubs["HAR"], clubs["NOR"], seed=seed)
    m.period = 2
    m.t = m.p1_len + (minute - 45.0) * 60.0
    m.score = list(score)
    for mg in m.mgr:
        mg.update(reactivity=1.0, chase_from=60.0, protect_from=70.0, next=0.0)
    return m


def test_a_side_that_is_losing_late_pushes_up_and_presses(clubs):
    m = sim_at(clubs, 72, score=(0, 1))  # HAR trail
    before = {k: getattr(m.style[0], k) for k in ("press_height", "line_height", "directness")}
    m._manager_review()
    after = m.style[0]
    assert after.press_height > before["press_height"] and after.line_height > before["line_height"] and after.directness > before["directness"]
    assert {c["team"]: c["reason"] for c in m.manager_log} == {"HAR": "chasing the game", "NOR": "protecting the lead"}


def test_a_side_that_is_winning_late_drops_deeper(clubs):
    m = sim_at(clubs, 78, score=(2, 1))
    before = m.style[0].line_height, m.style[0].press_height
    m._manager_review()
    assert (m.style[0].line_height, m.style[0].press_height) < before
    assert any(c["reason"] == "protecting the lead" and c["team"] == "HAR" for c in m.manager_log)


def test_nothing_changes_while_the_match_is_level_and_early(clubs):
    m = sim_at(clubs, 50)
    m._manager_review()
    assert m.manager_log == []


def test_managers_stop_changing_things_in_the_last_minutes(clubs):
    m = sim_at(clubs, LAST_CALL + 2, score=(0, 1))
    m._manager_review()
    assert m.manager_log == []


def test_a_sending_off_makes_one_side_compact_and_the_other_press(clubs):
    m = sim_at(clubs, 40)
    m.period, m.t = 1, 40 * 60.0
    m._manager_review()  # takes note of the eleven against eleven
    m._send_off(3, 0)  # a HAR defender
    m.t += 20.0
    m._manager_review()  # notices; the thinking time has not passed
    assert m.manager_log == []
    m.t += 200.0
    m._manager_review()
    m._manager_review()
    reasons = {c["team"]: c["reason"] for c in m.manager_log}
    assert reasons == {"HAR": "man down", "NOR": "extra man"}
    har = next(c for c in m.manager_log if c["team"] == "HAR")
    assert har["after"]["press_height"] < har["before"]["press_height"]


def test_a_manager_changes_shape_one_step_at_a_time(clubs):
    m = sim_at(clubs, 72, score=(0, 1))
    cur = m.formation_name[0]
    for _ in range(20):
        pick = m._shape_towards(0, +1, 1.0)
        assert pick is None or attacking_weight(pick) > attacking_weight(cur)
        pick = m._shape_towards(0, -1, 1.0)
        assert pick is None or attacking_weight(pick) < attacking_weight(cur)


def test_the_same_seed_gives_the_same_managers_and_the_same_match(clubs):
    a = simulate("d", clubs["HAR"], clubs["NOR"], seed=11)
    b = simulate("d", clubs["HAR"], clubs["NOR"], seed=11)
    assert a.stats["manager_changes"] == b.stats["manager_changes"]
    assert [e["type"] for e in a.events] == [e["type"] for e in b.events] and a.meta["score"] == b.meta["score"]


def test_managers_use_a_stream_of_their_own_so_a_match_is_unchanged_until_one_acts(clubs):
    for seed in range(1, 41):
        res = simulate("q", clubs["HAR"], clubs["NOR"], seed=seed)
        if res.stats["manager_changes"]:
            continue
        silent = Forced("q", clubs["HAR"], clubs["NOR"], seed=seed).run()  # the same match with the managers switched off
        assert [e["id"] for e in res.events] == [e["id"] for e in silent.events]
        return
    pytest.fail("no seed in 1..40 left both managers idle; the test needs one")


@pytest.mark.slow
def test_matches_differ_in_what_the_managers_do(clubs):
    seen = set()
    for seed in range(20, 32):
        seen |= {c["reason"] for c in simulate("v", clubs["KES"], clubs["ALD"], seed=seed).stats["manager_changes"]}
    assert {"chasing the game", "protecting the lead"} <= seen
