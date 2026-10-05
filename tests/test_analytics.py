"""Opta-style analytics: win probability, possession value, post-shot xG, tracking insights, the report."""

from __future__ import annotations

import json

import numpy as np
import pytest

from matchmind.analytics import load_models
from matchmind.analytics import vaep as V
from matchmind.analytics.measured_shape import measured_shapes, read_formation
from matchmind.analytics.networks import passing_network
from matchmind.analytics.report import MatchAnalytics
from matchmind.analytics.winprob import WinProbModel, outcome_probabilities
from matchmind.analytics.xgot import XGOT
from matchmind.core import geometry as G
from matchmind.core.paths import league_dir
from matchmind.intel.baselines import load_baselines
from matchmind.intel.pipeline import interpret_match
from matchmind.intel.xt import XTGrid
from matchmind.sim import tactics as TA
from matchmind.tracking.analyzer import PhysicalAnalyzer, analyze_match, packing
from matchmind.tracking.control import CELLS, NX, NY, home_control
from matchmind.tracking.frames import iter_chunks

MODELS = load_models()


@pytest.fixture(scope="module")
def ip(match):
    ip, _ = interpret_match(match, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"), models=MODELS)
    return ip


@pytest.fixture(scope="module")
def report(ip):
    return MatchAnalytics(ip).summary()


# ---------------------------------------------------------------------------------------------
# Win probability
# ---------------------------------------------------------------------------------------------


def test_outcome_probabilities_are_a_distribution_and_respect_the_score():
    p = outcome_probabilities(0, 1.2, 1.2)
    assert abs(sum(p.values()) - 1) < 1e-9 and abs(p["home"] - p["away"]) < 1e-9
    ahead = outcome_probabilities(1, 1.2, 1.2)
    assert ahead["home"] > p["home"] > ahead["away"]


def test_a_goal_matters_more_late_and_a_red_card_hurts():
    m = WinProbModel.from_dict(MODELS.get("winprob"))
    early = m.state_probabilities(10, (1, 0), (0.3, 0.3), (0, 0))["home"] - m.state_probabilities(10, (0, 0), (0.3, 0.3), (0, 0))["home"]
    late = m.state_probabilities(85, (1, 0), (0.3, 0.3), (0, 0))["home"] - m.state_probabilities(85, (0, 0), (0.3, 0.3), (0, 0))["home"]
    assert late > early > 0
    base = m.state_probabilities(30, (0, 0), (0.4, 0.4), (0, 0))
    sent_off = m.state_probabilities(30, (0, 0), (0.4, 0.4), (1, 0))
    assert sent_off["home"] < base["home"] and sent_off["away"] > base["away"]


def test_a_stronger_prior_and_more_xg_both_move_the_odds():
    m = WinProbModel.from_dict(MODELS.get("winprob"))
    assert m.state_probabilities(0, (0, 0), (0, 0), (0, 0), strength=(1.6, 1.0))["home"] > 0.45
    assert m.state_probabilities(60, (0, 0), (2.0, 0.2), (0, 0))["home"] > m.state_probabilities(60, (0, 0), (0.2, 0.2), (0, 0))["home"]


def test_the_series_ends_where_the_match_ended(ip, report):
    wp = report["winProbability"]
    clubs = ip.clubs
    final = {c: sum(1 for e in ip.events if e["type"] == "goal" and e["team"] == c) for c in clubs}
    last = wp["series"][-1]["p"]
    if final[clubs[0]] > final[clubs[1]]:
        assert last["home"] > 0.9
    elif final[clubs[0]] < final[clubs[1]]:
        assert last["away"] > 0.9
    assert all(abs(sum(p["p"].values()) - 1) < 1e-3 for p in wp["series"])
    goals = [s for s in wp["swings"] if s["kind"] == "goal"]
    assert len(goals) == sum(final.values()) and all(0 <= s["swing"] <= 1 for s in goals)


def test_goal_and_red_card_packs_carry_the_win_probability_change(ip):
    goals = [m for m in ip.all_moments if m["type"] == "goal"]
    assert goals
    for g in goals:
        wp = g["metrics"][f"{g['subjectTeam']}.win_prob"]
        assert wp["after"] >= wp["before"], "the scorer's chances cannot fall when they score"
        assert 0 <= g["facts"]["winProbSwing"] <= 1


# ---------------------------------------------------------------------------------------------
# Possession value and post-shot xG
# ---------------------------------------------------------------------------------------------


def test_the_feature_matrix_has_a_fixed_width(ip):
    acts = [e for e in ip.events if e["type"] in V.ACTIONS and "_ax" in e]
    x = V.featurize(acts, ip.clubs)
    assert x.shape == (len(acts), 1 + V.N_BASE + 2 * (V.N_BASE + 2))
    assert np.isfinite(x).all()


def test_the_value_model_ranks_actions_sensibly(ip):
    vals = MatchAnalytics(ip).action_values()
    assert vals, "models.json must exist (matchmind fit-models)"
    by_type: dict[str, list[float]] = {}
    for v in vals:
        by_type.setdefault(v.type, []).append(v.value)
    assert np.mean(by_type["shot"]) > np.mean(by_type["pass"]) > np.mean(by_type.get("foul", [0.0])) - 1
    goals = [v for v in vals if v.type == "shot"]
    assert max(v.value for v in goals) > 0.2
    failed = [v.value for v, e in zip(vals, [e for e in ip.events if e["type"] in V.ACTIONS and "_ax" in e], strict=True) if e["type"] == "pass" and e.get("outcome") == "incomplete"]
    done = [v.value for v, e in zip(vals, [e for e in ip.events if e["type"] in V.ACTIONS and "_ax" in e], strict=True) if e["type"] == "pass" and e.get("outcome") == "complete"]
    assert np.mean(failed) < 0 < np.mean(done) + 0.01, "losing the ball costs value, keeping it does not"


def test_fitted_diagnostics_are_recorded_and_good_enough():
    d = MODELS["diagnostics"]
    assert d["vaep"]["auc_score"] > 0.7 and d["vaep"]["auc_concede"] > 0.7
    assert d["winprob"]["brier_60"] < d["winprob"]["brier_prior_60"] - 0.15
    assert d["xgot"]["auc"] > 0.7


def test_post_shot_xg_rewards_corner_placement(ip):
    xgot = XGOT(MODELS["xgot"])
    shots = [e for e in ip.events if e["type"] == "shot"]
    off = next(e for e in shots if e["outcome"] == "off_target")
    assert xgot.value(off) == 0.0
    saved = [xgot.value(e) for e in shots if e["outcome"] == "saved"]
    goals = [xgot.value(e) for e in shots if e["outcome"] == "goal" and not e["attributes"].get("penalty")]
    assert saved and goals and np.mean(goals) > np.mean(saved)
    pen = {"type": "shot", "outcome": "goal", "attributes": {"penalty": True, "goalMouthY": 1.0, "goalMouthZ": 0.5}}
    assert xgot.value(pen) == 0.78


# ---------------------------------------------------------------------------------------------
# Tracking insights
# ---------------------------------------------------------------------------------------------


def test_pitch_control_follows_the_players():
    pos = np.full((22, 2), np.nan)
    pos[:11] = [[20.0, 34.0]] * 11
    pos[11:] = [[85.0, 34.0]] * 11
    grid = home_control(pos)
    assert grid.shape == (NY, NX)
    assert grid[:, 0].mean() > 0.95 and grid[:, -1].mean() < 0.05
    mid = home_control(np.vstack([np.full((11, 2), 52.0), np.full((11, 2), 53.0)]))
    assert 0.3 < mid.mean() < 0.7
    assert CELLS.shape == (NX * NY, 2)


def test_packing_counts_the_opponents_a_pass_goes_past():
    opp = np.full((11, 2), np.nan)
    opp[0] = [100.0, 34.0]  # the goalkeeper is never counted
    opp[1:4] = [[60.0, 20.0], [61.0, 34.0], [62.0, 48.0]]  # a back line
    opp[4:7] = [[48.0, 20.0], [49.0, 34.0], [50.0, 48.0]]  # a midfield line
    p = packing(np.array([40.0, 34.0]), np.array([70.0, 34.0]), opp, 1)
    assert p == {"bypassed": 6, "linesBroken": 2}
    assert packing(np.array([40.0, 34.0]), np.array([55.0, 34.0]), opp, 1)["linesBroken"] == 1
    assert packing(np.array([70.0, 34.0]), np.array([40.0, 34.0]), opp, 1) == {"bypassed": 0, "linesBroken": 0}


def test_tracking_insights_are_emitted_on_schedule(match):
    out = analyze_match(match)
    ctrl = [e for e in out.events if e["type"] == "space_control" and e["team"] == "HAR"]
    gaps = [b - a for a, b in zip((e["clock"]["matchMs"] for e in ctrl), (e["clock"]["matchMs"] for e in ctrl[1:]), strict=False)]
    assert gaps.count(30_000) >= len(gaps) - 2 and max(gaps) <= 30_000, "every 30 s, except the last partial window"
    shares = [e["attributes"]["controlShare"] for e in ctrl]
    assert 0.2 < np.mean(shares) < 0.8
    loads = [e for e in out.events if e["type"] == "player_load"]
    last = loads[-1]["attributes"]["players"]
    assert any(v["hsrM"] > 500 for v in last.values())
    first_hsr = {p: v["hsrM"] for p, v in loads[2]["attributes"]["players"].items()}
    assert all(last[p]["hsrM"] >= h for p, h in first_hsr.items() if p in last), "load is cumulative"
    assert all(v["acc"] < 400 for v in last.values()), "acceleration counts stay physical"


def test_off_ball_runs_reflect_how_a_team_plays(match):
    out = analyze_match(match)
    runs = [e for e in out.events if e["type"] == "off_ball_run"]
    assert runs
    kinds = {e["attributes"]["kind"] for e in runs}
    assert kinds <= {"in_behind", "overlap", "drop"}
    for e in runs:
        a = e["attributes"]
        assert a["distanceM"] >= 8 and a["durationMs"] >= 1200 and a["peakKmh"] < 40
        if a["kind"] == "in_behind":
            assert a["to"][0] > a["from"][0]
        if a["kind"] == "drop":
            assert a["to"][0] < a["from"][0]


def test_streaming_gives_the_same_tracking_insights_as_batch(match):
    batch = {e["id"]: e["attributes"] for e in analyze_match(match).events if e["type"] in ("off_ball_run", "space_control", "player_load", "shape_profile")}
    an = PhysicalAnalyzer(match.meta)
    an.add_events(match.events)
    got = {}
    for ch in iter_chunks(match):
        for e in an.process_chunk(ch).events:
            got[e["id"]] = e
    for e in an.flush().events:
        got[e["id"]] = e
    streamed = {i: e["attributes"] for i, e in got.items() if e["type"] in ("off_ball_run", "space_control", "player_load", "shape_profile")}
    assert streamed.keys() == batch.keys()
    assert all(streamed[i] == batch[i] for i in batch)


# ---------------------------------------------------------------------------------------------
# Measured shape and networks
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["4-4-2", "4-2-3-1", "3-5-2", "5-3-2", "4-3-3"])
def test_the_recogniser_names_a_clean_formation(name):
    lay = TA.layout(name, "base")
    pts = [(25.0 + d * 45.0, w * G.PITCH_W) for d, w in lay]
    roles = TA.roles(name)
    got = read_formation(pts, "def", roles)
    assert got is not None and got["label"] == name and got["from"] == name


def test_the_recogniser_survives_noise_and_ignores_the_bench():
    rng = np.random.default_rng(3)
    lay = TA.layout("3-4-3", "base")
    prof = {f"P{i}": [25.0 + d * 45.0 + rng.normal(0, 2.0), w * G.PITCH_W + rng.normal(0, 2.0), 500] for i, (d, w) in enumerate(lay)}
    prof["BENCH"] = [60.0, 30.0, 30]
    pos = {f"P{i}": r for i, r in enumerate(TA.roles("3-4-3"))}
    got = measured_shapes(prof, "def", pos)
    assert got["from"] == "3-4-3"
    assert measured_shapes({"a": [1, 1, 3]}) is None


def test_the_report_names_a_shape_for_each_team_and_phase(report):
    for s in report["shapes"].values():
        assert s["def"]["measured"] and s["ip"]["measured"]
        assert len(s["def"]["players"]) == 10 and s["blocks"]


def test_passing_networks_are_built_from_completed_passes(ip):
    net = passing_network(ip.events, ip.clubs[0], ip.players)
    assert net["nodes"] and net["edges"]
    ids = {n["id"] for n in net["nodes"]}
    assert all(e["a"] in ids and e["b"] in ids and e["n"] >= 2 for e in net["edges"])
    assert sum(n["passes"] for n in net["nodes"]) >= net["stats"]["completedPasses"]
    half = passing_network(ip.events, ip.clubs[0], ip.players, 0, 45 * 60_000)
    assert half["stats"]["completedPasses"] < net["stats"]["completedPasses"]


# ---------------------------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------------------------


def test_the_report_is_json_and_complete(report):
    json.dumps(report)
    for key in ("winProbability", "shots", "possessionValue", "networks", "shapes", "space", "lineBreaks", "runs", "load", "setPieces", "transitions", "goalkeepers", "pressing", "players", "playerOfTheMatch"):
        assert key in report, key
    assert report["possessionValue"]["available"]


def test_player_numbers_add_up_to_the_match(ip, report):
    goals = sum(p["goals"] for p in report["players"])
    assert goals == sum(1 for e in ip.events if e["type"] == "goal")
    shots = report["shots"]["teams"]
    assert sum(s["shots"] for s in shots.values()) == sum(p["shots"] for p in report["players"])
    assert report["playerOfTheMatch"]["pos"] != "GK"


def test_xg_race_ends_at_the_team_xg(report):
    for club, series in report["shots"]["race"].items():
        assert series[-1][1] == pytest.approx(report["shots"]["teams"][club]["xg"], abs=0.02)
        assert [p[1] for p in series] == sorted(p[1] for p in series), "cumulative xG never falls"


def test_goalkeeper_shot_stopping_uses_post_shot_xg(report):
    for g in report["goalkeepers"].values():
        assert g["goalsPrevented"] == pytest.approx(g["xgotFaced"] - g["goalsConceded"], abs=0.01)
        assert g["onTarget"] >= g["goalsConceded"]


def test_transitions_are_bounded_and_fast_breaks_end_in_shots(report):
    for t in report["transitions"].values():
        assert 0 <= (t["counterpressRate"] or 0) <= 1
        assert all(fb["secondsToShot"] <= 12 and fb["passes"] <= 6 for fb in t["fastBreakList"])


def test_set_piece_report_covers_the_routines_taken(ip, report):
    taken = sum(r["n"] for t in report["setPieces"]["teams"].values() for kind in t["taken"].values() for r in kind.values())
    routines = sum(1 for e in ip.events if (e.get("attributes") or {}).get("routine") and e["type"] in ("corner", "goal_kick") or (e["type"] == "free_kick" and (e.get("attributes") or {}).get("routine") in ("direct", "cross")))
    assert taken >= routines - 1


def test_pitch_control_matches_the_browser_fixture():
    """web/src/lib/control.ts implements the same formula; both are checked against this fixture."""
    fx = json.loads((league_dir().parents[1] / "tests" / "fixtures" / "pitch_control.json").read_text())
    assert (fx["nx"], fx["ny"]) == (NX, NY)
    for f in fx["frames"]:
        got = home_control(np.array(f["players"]))
        assert np.allclose(got.reshape(-1), np.array(f["grid"]), atol=1e-4)


def test_hull_area_and_the_defensive_block(match):
    from matchmind.tracking.insights import hull_area

    assert hull_area(np.array([[0, 0], [10, 0], [10, 10], [0, 10], [5, 5]])) == pytest.approx(100.0)
    assert hull_area(np.array([[0, 0], [4, 0], [0, 3]])) == pytest.approx(6.0)
    assert hull_area(np.array([[0, 0], [1, 1]])) == 0.0
    blocks = [e["attributes"]["blockAreaM2"] for e in analyze_match(match).events if e["type"] == "space_control" and e["attributes"].get("blockAreaM2")]
    assert blocks and 300 < float(np.median(blocks)) < 2500, "a defending block covers hundreds to a couple of thousand square metres"


def test_a_tactical_shift_carries_the_space_behind_the_line():
    pkg = league_dir().parents[0] / "replays" / "high-line-gamble" / "moments.json"
    shifts = [m for m in json.loads(pkg.read_text()) if m["type"] == "tactical_shift" and m["subjectTeam"] == "ALD"]
    assert shifts, "the scripted line change is detected"
    with_space = [m for m in shifts if "ALD.space_behind_m2" in m["metrics"]]
    assert with_space
    m = with_space[0]["metrics"]["ALD.space_behind_m2"]
    assert m["before"] > 0 and m["after"] > 0
    assert "space_behind_m2" in with_space[0]["glossary"]


def test_every_metric_in_every_committed_pack_has_a_definition():
    from matchmind.intel.evidence import GLOSSARY

    root = league_dir().parents[0] / "replays"
    seen = set()
    for pkg in root.iterdir():
        for m in json.loads((pkg / "moments.json").read_text()):
            for key in m["metrics"]:
                base = key.split(".", 1)[-1]
                seen.add(base)
                assert base in GLOSSARY, f"{key} (in {m['id']}) has no glossary entry"
                assert base in m["glossary"], f"{base} missing from the pack's own glossary"
    assert {"win_prob", "space_behind_m2"} <= seen, "the new evidence reaches the packs"
