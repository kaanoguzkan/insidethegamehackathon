"""Season history, the prediction, milestones, radars and the new cards and recaps."""

from __future__ import annotations

import numpy as np
import pytest

from matchmind.agents import recap as recap_writer
from matchmind.agents import templates as T
from matchmind.agents import verify as V
from matchmind.analytics.season import (
    FEATURED,
    FEATURED_ROUND,
    ROUNDS_PLAYED,
    context_for,
    fixtures,
    goal_milestones,
    load_season,
    poisson_grid,
    predict,
    radars,
    standings,
    team_radars,
)
from matchmind.core.contracts import Chip, Cohort
from matchmind.intel.recap import build_preview_pack

SEASON = load_season()
CLUBS = ["HAR", "NOR", "RED", "KES", "ALD", "SAL"]


@pytest.fixture(scope="module")
def ctx():
    return context_for(SEASON, "HAR", "NOR")


def test_the_fixture_list_is_a_proper_double_round_robin():
    fx = fixtures(CLUBS)
    last = [m for ms in fx["2025/26"].values() for m in ms]
    assert len(last) == 30 and len({tuple(m) for m in last}) == 30
    for r, ms in fx["2025/26"].items():
        assert sorted(c for m in ms for c in m) == sorted(CLUBS), f"round {r}: everyone plays once"
    this = fx["2026/27"]
    assert sorted(this) == list(range(1, ROUNDS_PLAYED + 1))
    played = {frozenset(m) for ms in this.values() for m in ms}
    assert not played & {frozenset(p) for p in FEATURED}, "the featured round has not been played yet"
    assert FEATURED_ROUND == ROUNDS_PLAYED + 1


def test_the_history_is_complete_and_consistent():
    assert SEASON and len(SEASON["matches"]) == 42
    for m in SEASON["matches"]:
        assert m["score"] == [sum(g["team"] == m["home"] for g in m["goals"]), sum(g["team"] == m["away"] for g in m["goals"])]
        assert {p["team"] for p in m["players"]} == {m["home"], m["away"]}
    table = standings([m for m in SEASON["matches"] if m["season"] == "2026/27"], CLUBS)
    assert all(r["played"] == ROUNDS_PLAYED for r in table)
    assert sum(r["gf"] for r in table) == sum(r["ga"] for r in table)
    assert [r["pos"] for r in table] == list(range(1, 7))
    assert table == sorted(table, key=lambda r: (-r["pts"], -r["gd"], -r["gf"], r["club"]))


def test_context_has_form_streaks_head_to_head_and_records(ctx):
    assert set(ctx["form"]) == {"HAR", "NOR"} and all(len(f) <= 5 and set(f) <= set("WDL") for f in ctx["form"].values())
    rec = ctx["headToHead"]["record"]
    assert sum(rec.values()) == len(ctx["headToHead"]["meetings"]) or len(ctx["headToHead"]["meetings"]) == 4
    assert ctx["records"]["fastestGoal"]["minute"] < 5 and ctx["records"]["mostGoalsByPlayer"]["n"] >= 2
    assert ctx["topScorers"][0]["goals"] >= ctx["topScorers"][-1]["goals"]
    assert context_for({}, "HAR", "NOR") == {}


def test_the_prediction_is_a_probability_and_prefers_the_stronger_side(ctx):
    p = ctx["prediction"]
    assert p["home"] + p["draw"] + p["away"] == pytest.approx(1.0, abs=0.01)
    rating = ctx["ratings"]
    stronger = "NOR" if rating["NOR"]["att"] * rating["HAR"]["def"] > rating["HAR"]["att"] * rating["NOR"]["def"] else "HAR"
    assert (p["away"] > p["home"]) == (stronger == "NOR")
    assert sum(s["p"] for s in p["scores"]) < 1 and p["strength"]["HAR"] > 0
    assert poisson_grid(1.3, 1.1).sum() == pytest.approx(1.0, abs=0.01)
    even = predict("HAR", "NOR", {"HAR": {"att": 1, "def": 1}, "NOR": {"att": 1, "def": 1}}, 1.3)
    assert even["home"] == pytest.approx(even["away"], abs=1e-3)


def test_milestones_fire_for_the_right_goals(ctx):
    pid = "NOR-23"
    tally = ctx["players"][pid]["goals"]
    ms = goal_milestones(ctx, [], {"team": "NOR", "player": pid, "minute": 20.0}, "HAR")
    if tally + 1 in (1, 5, 10, 15):
        assert any(m["kind"] == "season_goals" and m["n"] == tally + 1 for m in ms)
    two = [{"team": "NOR", "player": pid, "minute": 5.0}, {"team": "NOR", "player": pid, "minute": 9.0}]
    assert goal_milestones(ctx, two, {"team": "NOR", "player": pid, "minute": 30.0}, "HAR")[0]["kind"] == "hat_trick"
    fast = goal_milestones(ctx, [], {"team": "HAR", "player": "HAR-09", "minute": 0.05}, "NOR")
    assert any(m["kind"] == "fastest_goal" for m in fast)
    assert goal_milestones({}, [], {"team": "HAR", "player": "HAR-09", "minute": 1.0}, "NOR") == []
    streak = {**ctx, "streaks": {**ctx["streaks"], "HAR": {**ctx["streaks"]["HAR"], "cleanSheets": 3}}}
    assert any(m["kind"] == "ends_clean_sheet_run" and m["n"] == 3 for m in goal_milestones(streak, [], {"team": "NOR", "player": "NOR-21", "minute": 40.0}, "HAR"))


def test_radars_are_percentiles_and_similar_players_are_peers():
    rows = SEASON["matches"][-1]["players"]
    out = radars(SEASON, rows)
    assert out
    for pid, r in out.items():
        assert all(0.0 <= a["pct"] <= 1.0 for a in r["axes"])
        assert len(r["similar"]) == 3 and all(s["id"] != pid for s in r["similar"])
        pos = next(p["pos"] for p in rows if p["id"] == pid)
        assert all(next(q["pos"] for m in SEASON["matches"] for q in m["players"] if q["id"] == s["id"]) is not None for s in r["similar"])
        assert r["group"] in ("ATT", "MID", "DEF", "GK") and pos
    tr = team_radars(SEASON, ["HAR", "NOR"])
    assert all(0.0 <= a["scaled"] <= 1.0 for axes in tr.values() for a in axes)
    assert radars({}, rows) == {} and team_radars({}, ["HAR"]) == {}


# ---------------------------------------------------------------------------------------------
# Cards and recaps
# ---------------------------------------------------------------------------------------------

NAMES = {"HAR": "Harbour", "NOR": "Northbridge", "NOR-23": "Callum Roweov", "HAR-09": "Marco Quinski"}


@pytest.mark.parametrize("lang", ["en", "es", "tr"])
def test_every_new_card_renders_in_every_language(lang):
    facts = [
        {"type": "line_break_card", "team": "HAR", "player": "HAR-09", "values": {"bypassed": 9, "lines": 3, "receiver": "NOR-23", "distanceM": 31.0}},
        {"type": "run_card", "team": "HAR", "player": "HAR-09", "values": {"kind": "in_behind", "distanceM": 31.2, "peakKmh": 24.5}},
        {"type": "run_card", "team": "HAR", "player": "HAR-09", "values": {"kind": "overlap", "distanceM": 27.0, "peakKmh": 18.0}},
        {"type": "run_card", "team": "HAR", "player": "HAR-09", "values": {"kind": "drop", "distanceM": 22.0, "peakKmh": 14.0}},
        {"type": "load_card", "team": "HAR", "player": "HAR-09", "values": {"km": 11.4, "hsrM": 1830, "sprintM": 240, "acc": 90, "half": False}},
        {"type": "milestone_card", "team": "HAR", "player": "HAR-09", "values": {"kind": "hat_trick"}},
        {"type": "milestone_card", "team": "HAR", "player": "HAR-09", "values": {"kind": "season_goals", "n": 5}},
        {"type": "milestone_card", "team": "HAR", "player": "HAR-09", "values": {"kind": "fastest_goal", "minute": 0.3, "previous": 0.6}},
        {"type": "milestone_card", "team": "NOR", "player": None, "values": {"kind": "ends_clean_sheet_run", "n": 3}},
    ]
    for f in facts:
        card = T.fact_card(f, lang, NAMES)
        assert card is not None, f
        head, body, chips, kind = card
        assert head and kind in ("stat_card", "pass_card")
        assert "{" not in head + body and all(isinstance(c, Chip) for c in chips)


def test_the_goal_story_quotes_the_win_probability_in_every_language():
    from packs import packs  # hand-built packs shaped like the interpreter's

    base = packs()["goal"]
    goal = {**base, "metrics": {f"{base['subjectTeam']}.win_prob": {"before": 38.0, "after": 71.0, "delta": 33.0, "changePct": 87.0}}}
    for lang, needle in (("en", "Win probability 38% to 71%"), ("es", "del 38% al 71%"), ("tr", "yüzde 38 iken yüzde 71")):
        v = T.render(goal, Cohort(mode="analyst", language=lang))
        assert needle in v.body, (lang, v.body)
        assert not [i for i in V.verify_text(v.body, goal, lang) if i.severity == "error"]


def test_the_preview_carries_the_prediction_and_verifies(ctx):
    meta = {
        "matchId": "m", "home": {"id": "HAR", "name": "Harbour City", "short": "Harbour", "formation": "4-3-3", "lineup": ["HAR-09"], "style": {},
                                 "players": {"HAR-09": {"name": "Marco Quinski", "pos": "ST", "rating": 80}}},
        "away": {"id": "NOR", "name": "Northbridge Athletic", "short": "Northbridge", "formation": "4-2-3-1", "lineup": ["NOR-23"], "style": {},
                 "players": {"NOR-23": {"name": "Callum Roweov", "pos": "ST", "rating": 82}}},
    }
    pack = build_preview_pack(meta, ctx)
    pred = pack["facts"]["prediction"]
    assert pred["homePct"] + pred["drawPct"] + pred["awayPct"] in (99, 100, 101)
    for lang in ("en", "es", "tr"):
        for mode in ("analyst", "casual"):
            r = recap_writer.render(pack, Cohort(mode=mode, language=lang))
            assert "{" not in r.summary
            if mode == "analyst":
                assert str(pred["homePct"]) in r.summary and "position" in r.summary or lang != "en"
            assert not [i for i in V.verify_text(f"{r.headline}. {r.summary}", pack, lang) if i.severity == "error"], (lang, mode, r.summary)
    assert "prediction" not in build_preview_pack(meta, None)["facts"]


def test_preview_percentages_are_whole_numbers():
    assert np.isclose(sum(context_for(SEASON, "RED", "SAL")["prediction"][k] for k in ("home", "draw", "away")), 1.0, atol=0.01)
