import math

import pytest

from matchmind.core.paths import league_dir, scenarios_dir
from matchmind.intel.baselines import load_baselines
from matchmind.intel.evidence import numbers_in
from matchmind.intel.pipeline import interpret_match
from matchmind.intel.xt import XTGrid, fit_xt
from matchmind.sim.engine import simulate
from matchmind.sim.league import load_league
from matchmind.sim.scenarios import load_scenario

WINDOW_TYPES = {
    "pressure_collapse", "pressure_surge", "momentum_swing", "chaos_flip",
    "rhythm_break", "tactical_shift", "fatigue_drop",
}  # fmt: skip


@pytest.fixture(scope="module")
def league():
    return load_league(league_dir() / "league.json")


@pytest.fixture(scope="module")
def interpreted(match):
    return interpret_match(match, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"))


def test_every_goal_becomes_a_goal_moment(match, interpreted):
    _, out = interpreted
    goals = [e for e in match.events if e["type"] == "goal"]
    moments = [m for m in out.moments if m["type"] == "goal"]
    assert len(goals) == len(moments)
    for m in moments:
        assert m["salience"] >= 0.6
        assert m["facts"]["score"]


def test_moments_are_well_formed_evidence_packs(match, interpreted):
    ip, out = interpreted
    known = {e["id"] for e in match.events} | {e["id"] for e in ip.events}
    ids = [m["id"] for m in out.moments]
    assert len(ids) == len(set(ids))
    for m in out.moments:
        assert 0.0 <= m["salience"] <= 1.0
        assert m["detectedAt"]["label"]
        assert set(m["eventIds"]) <= known, "evidence must cite real events"
        assert all(math.isfinite(x) for x in numbers_in(m["metrics"]))
        for key in m["metrics"]:
            assert "." in key  # CLUB.metric or match.metric
        for p in m["players"]:
            assert p["name"] and p["team"] in m["teamNames"]


def test_window_moments_carry_before_and_after(interpreted):
    _, out = interpreted
    windowed = [m for m in out.moments if m["type"] in WINDOW_TYPES]
    assert windowed
    for m in windowed:
        assert "before" in m["windows"] and "after" in m["windows"]
        changes = [v for v in m["metrics"].values() if "before" in v]
        assert changes, "a window moment needs at least one before/after metric"
        for v in changes:
            if v["before"] is not None and v["after"] is not None:
                assert v["delta"] == pytest.approx(v["after"] - v["before"], abs=1e-9)


def test_snapshots_every_minute_with_valid_indices(interpreted):
    ip, out = interpreted
    snaps = out.snapshots
    assert len(snaps) >= 85
    gaps = {b["matchMs"] - a["matchMs"] for a, b in zip(snaps, snaps[1:], strict=False)}
    assert gaps == {60_000}
    for s in snaps:
        assert 0 <= s["chaos"] <= 100
        assert sum(s["momentum"].values()) == pytest.approx(1.0, abs=0.01)
        assert all(0 <= v <= 100 for v in s["pressure"].values())
        assert s["control"]["controller"] in ip.clubs


def test_indices_are_not_pinned_to_the_ends(interpreted):
    """Baselines must make the scales usable: chaos should spread, not sit at 0 or 100."""
    _, out = interpreted
    chaos = [s["chaos"] for s in out.snapshots[10:]]
    assert 15 < sum(chaos) / len(chaos) < 85
    assert max(chaos) - min(chaos) > 15


def test_facts_cover_the_template_overlays(interpreted):
    _, out = interpreted
    kinds = {f["type"] for f in out.facts}
    assert {"shot_card", "speed_badge"} <= kinds
    assert all(f["priority"] in (1, 2, 3, 4, 5) for f in out.facts)
    for f in out.facts:
        assert f["clock"]["matchMs"] == f["matchMs"]


def test_pass_cards_only_for_hard_completed_passes(interpreted):
    ip, out = interpreted
    for f in out.facts:
        if f["type"] == "pass_card":
            assert f["values"]["difficulty"] >= ip.cfg.key_pass_difficulty


def test_interpretation_is_deterministic(match, interpreted):
    _, out = interpreted
    again = interpret_match(match, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"))[1]
    assert [m["id"] for m in again.moments] == [m["id"] for m in out.moments]
    assert [m["salience"] for m in again.moments] == [m["salience"] for m in out.moments]


def test_xt_grid_values_rise_toward_goal(league):
    runs = [simulate(f"x{i}", league["HAR"], league["ALD"], seed=500 + i) for i in range(3)]
    grid = fit_xt([(r.events, r.meta) for r in runs])
    assert grid.value(95, 34) > grid.value(70, 34) > grid.value(30, 34)
    assert 0 < grid.value(95, 34) < 0.6


def test_scripted_pressing_collapse_is_detected_without_being_told(league):
    """The scenario script is hidden from the pipeline; it must notice and explain the change."""
    sc = load_scenario(scenarios_dir() / "pressing-collapse.yaml")
    res = simulate("m", league[sc.home], league[sc.away], seed=sc.seed, scenario=sc)
    _, out = interpret_match(res, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"))
    hits = [m for m in out.moments if m["type"] == "pressure_collapse" and m["subjectTeam"] == "NOR"]
    assert hits, "NOR stop pressing at 55:00 and the interpreter should notice"
    first = hits[0]
    assert first["detectedAt"]["clock"]["period"] == 2
    assert 56 <= first["detectedAt"]["clock"]["minute"] <= 75
    assert first["beneficiaryTeam"] == "HAR"
    m = first["metrics"]
    assert m["NOR.nearest_defender_m"]["delta"] > 2.0
    assert m["NOR.pressures_per_min"]["delta"] < 0
    assert m["NOR.nearest_defender_m"]["consistent"] is True
    # Nothing about pressing should have been flagged before the change.
    early = [m for m in out.moments if m["type"].startswith("pressure_") and m["detectedAt"]["clock"]["minute"] < 55]
    assert not early
    assert "nearest_defender_m" in first["glossary"]


def test_hand_built_packs_match_the_interpreters_shape(interpreted):
    """tests/packs.py stands in for moment types a given match may not contain; keep it faithful."""
    from packs import packs

    _, out = interpreted
    real = set(out.moments[0])
    for mtype, pack in packs().items():
        assert set(pack) == real, (mtype, set(pack) ^ real)
        assert set(pack["detectedAt"]) == set(out.moments[0]["detectedAt"])
