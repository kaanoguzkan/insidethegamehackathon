import numpy as np
import pytest

from matchmind.core import geometry as G
from matchmind.sim import realism
from matchmind.sim.engine import simulate
from matchmind.sim.league import generate_league


def test_league_is_deterministic_and_fictional(clubs):
    again = generate_league()
    assert [p.name for p in clubs["HAR"].squad] == [p.name for p in again["HAR"].squad]
    names = [p.name for c in clubs.values() for p in c.squad]
    assert len(names) == len(set(names)) == 150
    assert len(clubs) == 6
    assert all(len(c.squad) == 25 for c in clubs.values())


def test_same_seed_same_match(clubs, match):
    again = simulate("t0001", clubs["HAR"], clubs["NOR"], seed=42)
    assert again.events == match.events
    assert np.array_equal(again.frames, match.frames, equal_nan=True)


def test_different_seed_different_match(clubs, match):
    other = simulate("t0002", clubs["HAR"], clubs["NOR"], seed=43)
    assert [e["type"] for e in other.events] != [e["type"] for e in match.events]


def test_event_stream_is_ordered_and_unique(match):
    seqs = [e["seq"] for e in match.events]
    assert seqs == list(range(1, len(seqs) + 1))
    assert len({e["id"] for e in match.events}) == len(match.events)
    ms = [e["clock"]["matchMs"] for e in match.events]
    assert ms == sorted(ms)


def test_score_matches_goal_events(match):
    goals = [e for e in match.events if e["type"] == "goal"]
    final = match.meta["score"]
    for club, n in final.items():
        assert n == sum(1 for g in goals if g["team"] == club)
    if goals:
        last = goals[-1]["attributes"]["score"]
        assert last == final


def test_match_has_two_periods_and_realistic_length(match):
    kinds = [e["type"] for e in match.events if e["type"] in ("period_start", "period_end")]
    assert kinds == ["period_start", "period_end", "period_start", "period_end"]
    minutes = match.meta["frames"] * 0.2 / 60
    assert 92 <= minutes <= 106


def test_attack_direction_flips_at_half_time(match):
    p1, p2 = match.meta["periods"]
    assert p1["attackDirection"]["HAR"] == -p2["attackDirection"]["HAR"]


def test_tracking_stays_on_pitch(match):
    f = match.frames[~np.isnan(match.frames)].reshape(-1, 2)
    assert f[:, 0].min() >= -1.5 and f[:, 0].max() <= G.PITCH_L + 1.5
    assert f[:, 1].min() >= -1.5 and f[:, 1].max() <= G.PITCH_W + 1.5
    ball = match.ball
    assert ball[:, 0].min() >= -1.5 and ball[:, 0].max() <= G.PITCH_L + 1.5


def test_nobody_teleports(match):
    step = np.diff(match.frames.astype(float), axis=0)
    speed = np.hypot(step[..., 0], step[..., 1]) / 0.2
    for p in match.meta["periods"]:
        if p["period"] > 1:
            speed[p["startFrame"] - 1] = np.nan  # repositioning at the break
    assert np.nanmax(speed) < 11.5  # m/s, about 41 km/h


def test_chunks_are_complete(match):
    n = match.meta["frames"]
    assert n % match.meta["chunkTicks"] == 0
    assert len(match.chunk_slots) == n // match.meta["chunkTicks"]
    assert all(len(s) == 22 for s in match.chunk_slots)


def test_passes_have_consistent_geometry(match):
    for e in match.events:
        if e["type"] == "pass":
            assert "location" in e and "end" in e
            assert e["attributes"]["passType"]
            assert e["outcome"] in ("complete", "incomplete", "offside")


def test_substitutions_swap_players(match):
    subs = [e for e in match.events if e["type"] == "substitution"]
    assert subs, "a full match should include substitutions"
    for s in subs:
        assert s["attributes"]["off"] != s["player"]


def test_style_dials_change_how_teams_play(clubs):
    """A pressing side concedes fewer passes per defensive action than a low block."""

    def ppda(home, away, seed):
        res = simulate(f"s{seed}", clubs[home], clubs[away], seed=seed)
        dirs = {m["period"]: m["attackDirection"] for m in res.meta["periods"]}
        out = {}
        for team in (home, away):
            opp = away if team == home else home
            passes = actions = 0
            for e in res.events:
                d = dirs[e["clock"]["period"]]
                if e["type"] == "pass" and e["team"] == opp:
                    ax = e["location"]["x"] if d[opp] == 1 else G.PITCH_L - e["location"]["x"]
                    passes += ax < G.PITCH_L * 0.6
                elif e["type"] in ("tackle", "interception", "foul") and e["team"] == team:
                    ax = e["location"]["x"] if d[opp] == 1 else G.PITCH_L - e["location"]["x"]
                    actions += ax < G.PITCH_L * 0.6
            out[team] = passes / max(1, actions)
        return out

    results = [ppda("HAR", "ALD", s) for s in (11, 12, 13)]
    har = np.mean([r["HAR"] for r in results])  # high press
    ald = np.mean([r["ALD"] for r in results])  # low block
    assert har < ald


@pytest.mark.slow
def test_league_averages_are_realistic():
    samples = realism.run_realism(48)
    rows = realism.evaluate(samples)
    failing = [f"{r.name}={r.mean:.2f} (target {r.low}-{r.high})" for r in rows if not r.ok]
    assert not failing, "outside realism bands: " + "; ".join(failing)
