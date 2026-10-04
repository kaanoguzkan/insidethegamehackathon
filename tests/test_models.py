import math

from matchmind.core import geometry as G
from matchmind.core.clock import clock_from_ms, label
from matchmind.core.models import pass_difficulty, threat, xg, xpass


def test_attack_frame_is_an_involution():
    for d in (1, -1):
        x, y = G.to_att(30.0, 20.0, d)
        assert G.from_att(x, y, d) == (30.0, 20.0)


def test_shot_angle_is_widest_in_front_of_goal():
    near = G.shot_angle(100, G.CY)
    wide = G.shot_angle(100, G.CY + 25)
    far = G.shot_angle(70, G.CY)
    assert near > wide and near > far


def test_xg_falls_with_distance_and_pressure():
    close = xg(98, G.CY)
    mid = xg(88, G.CY)
    far = xg(75, G.CY)
    assert close > mid > far > 0
    assert xg(95, G.CY, pressure=0.9) < xg(95, G.CY)
    assert xg(95, G.CY, body="head") < xg(95, G.CY)
    assert xg(95, G.CY, assist="through") > xg(95, G.CY)
    assert xg(0, 0, penalty=True) == 0.78


def test_xg_is_a_probability_everywhere():
    for x in range(0, 106, 7):
        for y in range(0, 69, 7):
            assert 0.0 < xg(x, y) < 1.0


def test_xpass_falls_with_distance_pressure_and_blocked_lanes():
    base = xpass(15)
    assert xpass(40) < base
    assert xpass(15, pressure_receiver=0.8) < base
    assert xpass(15, lane_block=0.9) < base
    assert xpass(15, kind="through") < xpass(15, kind="short")
    assert 0.0 < xpass(60, kind="long", pressure_receiver=1, pressure_passer=1, lane_block=1) < 0.5


def test_pass_difficulty_scale():
    assert pass_difficulty(1.0) == 0.0
    assert pass_difficulty(0.0) == 10.0
    assert pass_difficulty(0.82) == 1.8


def test_threat_rises_toward_goal():
    assert threat(50, G.CY) < threat(80, G.CY) < threat(95, G.CY)
    assert math.isfinite(threat(105, G.CY))


def test_clock_second_half_restarts_at_45():
    p2 = 48 * 60_000  # first half ran 3 minutes long
    assert clock_from_ms(60_000, p2)["minute"] == 1
    c = clock_from_ms(p2 + 10_000, p2)
    assert (c["period"], c["minute"], c["second"]) == (2, 45, 10)
    assert label(clock_from_ms(46 * 60_000, p2)) == "45+1'"
    assert label(clock_from_ms(p2 + 20 * 60_000, p2)) == "65'"
