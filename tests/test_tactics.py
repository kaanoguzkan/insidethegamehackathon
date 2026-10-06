"""Formations, phase shapes, tactic tags and set-piece choreography."""

from __future__ import annotations

import numpy as np
import pytest

from matchmind.core import geometry as G
from matchmind.sim import tactics as TA
from matchmind.sim.engine import MatchSim
from matchmind.sim.scenarios import ScriptItem, parse_scenario
from matchmind.sim.teams import ROLE_COMPAT, Club, Style

# ---------------------------------------------------------------------------------------------
# The formation library
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", TA.formation_names())
def test_every_formation_is_well_formed(name):
    f = TA.FORMATIONS_FULL[name]
    assert len(f["base"]) == 11 and f["base"][0][0] == "GK"
    for phase in ("attack", "block"):
        assert len(f[phase]) == 10
    for role, depth, width in f["base"]:
        assert role in ROLE_COMPAT
        assert 0 <= depth <= 1 and 0 <= width <= 1
    for phase in ("attack", "block"):
        assert all(0 <= d <= 1 and 0 <= w <= 1 for d, w in f[phase]), (name, phase)
    assert name.count("-") >= 2 and sum(int(x) for x in name.split("-")) == 10


def test_the_library_covers_the_major_modern_shapes():
    assert {"4-3-3", "4-2-3-1", "4-4-2", "4-1-4-1", "3-5-2", "3-4-3", "3-4-2-1", "5-3-2", "4-3-1-2"} <= set(TA.formation_names())


@pytest.mark.parametrize(
    "name,block",
    [("4-3-3", "4-5-1"), ("4-2-3-1", "4-4-1-1"), ("4-4-2", "4-4-2"), ("3-5-2", "5-3-2"),
     ("3-4-3", "5-4-1"), ("3-4-2-1", "5-4-1"), ("5-3-2", "5-3-2")],
)
def test_out_of_possession_shapes_are_what_coaches_call_them(name, block):
    assert TA.describe_shapes(name, {})["block"] == block


def test_every_formation_has_an_analyst_name_for_its_attacking_shape():
    for name in TA.formation_names():
        assert TA.describe_shapes(name, {})["attack"] == TA.ATTACK_LABEL[name]
        assert sum(int(x) for x in TA.ATTACK_LABEL[name].split("-")) == 10
    assert TA.describe_shapes("4-3-3", {"pivot": "drop"})["attack"] == "3-2-5", "the pivot makes a back three in build-up"


def test_a_back_three_defends_as_a_back_five_and_attacks_with_wing_backs_high():
    f = TA.FORMATIONS_FULL["3-4-3"]
    rs = TA.roles("3-4-3")
    wb = [i for i, r in enumerate(rs) if r in ("LWB", "RWB")]
    cb = [i for i, r in enumerate(rs) if r == "CB"]
    cb_depth = max(f["block"][i][0] for i in cb)
    assert all(abs(f["block"][i][0] - cb_depth) <= 0.05 for i in wb), "wing-backs drop onto the back line"
    assert all(f["attack"][i][0] >= f["block"][i][0] + 0.4 for i in wb), "and push on when attacking"


def test_tags_reshape_the_attack_without_touching_the_formation():
    rs = TA.roles("4-3-3")
    base = TA.layout("4-3-3", "attack")
    inv = TA.apply_attack_tags("4-3-3", base, {"fullbacks": "inverted"})
    ovl = TA.apply_attack_tags("4-3-3", base, {"fullbacks": "overlap"})
    fb = [i for i, r in enumerate(rs) if r in ("LB", "RB")]
    for i in fb:
        assert abs(inv[i][1] - 0.5) < abs(ovl[i][1] - 0.5), "inverted fullbacks are narrower than overlapping ones"
        assert ovl[i][0] > inv[i][0], "overlapping fullbacks are higher"
    f9 = TA.apply_attack_tags("4-3-3", base, {"striker": "false9"})
    st = rs.index("ST")
    assert f9[st][0] < base[st][0] - 0.15, "a false nine drops into midfield"
    drop = TA.apply_attack_tags("4-3-3", base, {"pivot": "drop"})
    dm = rs.index("DM")
    assert drop[dm][0] <= 0.23, "the pivot drops between the centre-backs"


def test_style_tags_are_validated():
    assert Style.from_dict({**Style().to_dict(), "fullbacks": "overlap"}).fullbacks == "overlap"
    with pytest.raises(ValueError, match="fullbacks"):
        Style.from_dict({**Style().to_dict(), "fullbacks": "sideways"})
    # Leagues written before tags existed still load.
    old = {k: v for k, v in Style().to_dict().items() if k not in TA.TAGS and k != "long_throws"}
    assert Style.from_dict(old).corners == "mixed"


def test_assignment_finds_the_cheapest_matching():
    cost = [[4, 1, 3], [2, 0, 5], [3, 2, 2]]
    cols = TA.assign(cost)
    assert sorted(cols) == [0, 1, 2]
    assert sum(cost[i][c] for i, c in enumerate(cols)) == 5


# ---------------------------------------------------------------------------------------------
# Scenario scripting
# ---------------------------------------------------------------------------------------------


def test_scenarios_validate_formations_and_tags():
    base = {"id": "x", "home": "HAR", "away": "NOR"}
    ok = parse_scenario({**base, "script": [{"at": "60:00", "team": "NOR", "formation": "5-3-2", "tags": {"build_up": "long"}}]})
    assert ok.script[0].formation == "5-3-2"
    with pytest.raises(ValueError, match="formation"):
        parse_scenario({**base, "script": [{"at": "60:00", "team": "NOR", "formation": "9-0-1"}]})
    with pytest.raises(ValueError, match="tag"):
        parse_scenario({**base, "script": [{"at": "60:00", "team": "NOR", "tags": {"corners": "sideways"}}]})


# ---------------------------------------------------------------------------------------------
# What the players actually do: probes over simulated matches
# ---------------------------------------------------------------------------------------------


class Probe(MatchSim):
    """Records shape samples while the ball is live and snapshots every restart as it is taken."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.shape = {t: {True: [np.zeros((10, 2)), 0], False: [np.zeros((10, 2)), 0]} for t in (0, 1)}
        self.restarts: list[dict] = []

    def _record(self):
        super()._record()
        if self.mode == "dead" or self.t < 120:
            return
        for t in (0, 1):
            ip = self.team_in_possession(t)
            pts = np.array([G.to_att(*self.pos[t * 11 + i], self.dir[t]) for i in range(1, 11)])
            a = self.shape[t][ip]
            a[0] += pts
            a[1] += 1

    def _execute_restart(self):
        r = self.restart
        ready = r is not None and not (self.t < r["at"] + 9.0 and float(np.hypot(*(self.pos[r["taker"]] - r["spot"]))) > 2.0)
        if ready:
            att, de = r["team"], 1 - r["team"]
            frame = lambda team: [G.to_att(*self.pos[team * 11 + i], self.dir[att]) for i in range(11)]  # noqa: E731
            self.restarts.append({
                "kind": r["kind"], "routine": dict(r.get("routine") or {}), "taker": r["taker"], "team": att,
                "att": frame(att), "def": frame(de), "spot": G.to_att(*r["spot"], self.dir[att]),
                "roles": {att: list(self.slot_role[att]), de: list(self.slot_role[de])},
            })
        super()._execute_restart()

    def mean_shape(self, team: int, in_possession: bool) -> np.ndarray:
        acc, n = self.shape[team][in_possession]
        return acc / max(n, 1)


def _club_with(club: Club, **style) -> Club:
    d = club.to_dict()
    d["style"].update(style)
    return Club.from_dict(d)


@pytest.fixture(scope="module")
def kes(clubs):
    m = Probe("bt", clubs["KES"], clubs["RED"], seed=7)
    m.run()
    return m


def test_a_back_three_team_really_changes_shape_with_the_ball(kes):
    roles = kes.slot_role[0]
    out, inn = kes.mean_shape(0, False), kes.mean_shape(0, True)
    wb = [i for i, r in enumerate(roles) if r in ("LWB", "RWB")]
    cb = [i for i, r in enumerate(roles) if r == "CB"]
    cb_x_out = out[cb, 0].mean()
    # Out of possession the wing-backs are close to the centre-backs' line: a back five ...
    assert all(out[i, 0] - cb_x_out < 16.0 for i in wb), (out[wb, 0], cb_x_out)
    # ... and in possession they are much higher up the pitch, and wide.
    assert all(inn[i, 0] - out[i, 0] > 12.0 for i in wb)
    assert all(abs(inn[i, 1] - G.CY) > 22.0 for i in wb)


def test_teams_with_different_tags_move_differently(clubs):
    base = clubs["HAR"]
    inv = Probe("a", _club_with(base, fullbacks="inverted", striker="target"), clubs["RED"], seed=3)
    ovl = Probe("a", _club_with(base, fullbacks="overlap", striker="target"), clubs["RED"], seed=3)
    f9 = Probe("a", _club_with(base, fullbacks="hold", striker="false9"), clubs["RED"], seed=3)
    tgt = Probe("a", _club_with(base, fullbacks="hold", striker="target"), clubs["RED"], seed=3)
    for m in (inv, ovl, f9, tgt):
        m.run()
    fb = [i for i, r in enumerate(inv.slot_role[0]) if r in ("LB", "RB")]
    width = lambda m: float(np.abs(m.mean_shape(0, True)[fb, 1] - G.CY).mean())  # noqa: E731
    height = lambda m: float(m.mean_shape(0, True)[fb, 0].mean())  # noqa: E731
    assert width(inv) < width(ovl) - 8.0, "inverted fullbacks work narrower than overlapping ones"
    assert height(ovl) > height(inv) + 4.0
    st = inv.slot_role[0].index("ST")
    assert f9.mean_shape(0, True)[st, 0] < tgt.mean_shape(0, True)[st, 0] - 6.0, "a false nine drops off the line"


@pytest.fixture(scope="module")
def restarts(clubs):
    """Several matches' worth of restarts, snapshotted at the moment each is taken."""
    out: list[dict] = []
    for h, a, seed in (("RED", "ALD", 1), ("HAR", "KES", 2), ("NOR", "SAL", 3), ("RED", "HAR", 4)):
        m = Probe("sp", clubs[h], clubs[a], seed=seed)
        m.run()
        out += m.restarts
    return out


def _in_box(p):
    return p[0] >= G.PITCH_L - G.BOX_DEPTH and abs(p[1] - G.CY) <= G.BOX_HALF_W


def _at_box(p):
    """In the box or on its edge (an edge-of-box corner routine puts the shooters just outside)."""
    return p[0] >= G.PITCH_L - G.BOX_DEPTH - 4.0 and abs(p[1] - G.CY) <= G.BOX_HALF_W + 2.0


def test_corners_fill_the_box_and_keep_a_counter_attack_screen(restarts):
    cs = [r for r in restarts if r["kind"] == "corner" and r["routine"]["delivery"] != "short"]
    assert len(cs) >= 10
    for r in cs:
        attackers = sum(_at_box(p) for p in r["att"][1:])
        defenders = sum(_at_box(p) for p in r["def"][1:])
        # An edge-of-box routine puts three of its six shooters on the edge, and a runner can still be on the way.
        assert attackers >= (3 if r["routine"]["delivery"] == "edge" else 4), r["routine"]
        assert defenders >= 6, r["routine"]
        # Two or three players stay upfield so the corner cannot be countered into an open goal.
        assert sum(p[0] < 75.0 for p in r["att"][1:]) >= 2


def test_corner_routines_and_defences_are_varied(restarts):
    cs = [r for r in restarts if r["kind"] == "corner"]
    assert {r["routine"]["delivery"] for r in cs} >= {"near", "far"}
    assert {r["routine"]["defence"] for r in cs} == {"zonal", "man"}


def test_a_direct_free_kick_has_a_wall_at_the_right_distance(restarts):
    fks = [r for r in restarts if r["kind"] == "free_kick" and r["routine"].get("type") == "direct"]
    assert fks, "expected at least one direct free kick"
    for r in fks:
        wall = [p for p in r["def"][1:] if 8.0 <= float(np.hypot(p[0] - r["spot"][0], p[1] - r["spot"][1])) <= 11.5]
        assert len(wall) >= r["routine"]["wall"] - 1, (r["routine"], len(wall))


def test_goal_kicks_build_short_or_go_long_and_the_press_stays_out_of_the_box(restarts):
    gks = [r for r in restarts if r["kind"] == "goal_kick"]
    modes = {r["routine"]["mode"] for r in gks}
    assert modes == {"short", "long"}
    for r in gks:
        assert not any(_in_box_own(p) for p in r["def"][1:]), "the opposition waits outside the penalty area"
    short = [np.mean([p[0] for p in r["att"][1:]]) for r in gks if r["routine"]["mode"] == "short"]
    long_ = [np.mean([p[0] for p in r["att"][1:]]) for r in gks if r["routine"]["mode"] == "long"]
    assert np.mean(long_) > np.mean(short) + 5.0, "a long goal kick pushes the team up"


def _in_box_own(p):
    return p[0] < G.BOX_DEPTH - 0.5 and abs(p[1] - G.CY) < G.BOX_HALF_W - 0.5


def test_penalties_are_taken_with_everyone_else_outside_the_box(restarts):
    pens = [r for r in restarts if r["kind"] == "penalty"]
    for r in pens:
        inside = [p for p in (*r["att"][1:], *r["def"][1:]) if _in_box(p) and p != r["att"][r["taker"] % 11]]
        assert len(inside) <= 2, "at most a straggler or two still in the box"


def test_throw_ins_have_outlets_and_kick_offs_stay_in_their_own_halves(restarts):
    tis = [r for r in restarts if r["kind"] == "throw_in" and r["routine"]["mode"] == "short"]
    assert tis
    near = [sum(float(np.hypot(p[0] - r["spot"][0], p[1] - r["spot"][1])) < 16.0 for p in r["att"][1:]) for r in tis]
    assert np.mean(near) >= 2.5, "the thrower has several options within reach"
    for r in (r for r in restarts if r["kind"] == "kickoff"):
        assert all(p[0] <= 54.0 for p in r["att"][1:]), "kick-off team in its own half"


def test_events_record_the_routine_for_downstream_analysis(clubs):
    m = Probe("ev", clubs["RED"], clubs["HAR"], seed=11)
    res = m.run()
    corners = [e for e in res.events if e["type"] == "corner"]
    assert corners and all(e["attributes"]["routine"] in ("near", "far", "short", "edge") for e in corners)
    gks = [e for e in res.events if e["type"] == "goal_kick"]
    assert all(e["attributes"]["routine"] in ("short", "long") for e in gks)
    fks = [e for e in res.events if e["type"] == "free_kick" and e["attributes"].get("routine") == "direct"]
    assert all(e["attributes"]["wall"] in (3, 4, 5) for e in fks)


def test_a_scripted_formation_change_reassigns_players_and_is_recorded(clubs):
    from matchmind.sim.scenarios import Scenario

    sc = Scenario(
        id="sw", home="HAR", away="NOR", seed=5,
        script=[ScriptItem(at="60:00", team="NOR", formation="5-3-2"), ScriptItem(at="70:00", team="HAR", tags={"fullbacks": "overlap"})],
    )
    res = MatchSim("sw", clubs["HAR"], clubs["NOR"], seed=5, scenario=sc).run()
    fc = [e for e in res.events if e["type"] == "formation_change"]
    shapes = TA.describe_shapes("5-3-2", clubs["NOR"].style.tags)
    assert len(fc) == 1
    assert fc[0]["attributes"] == {"formation": "5-3-2", "previous": "4-2-3-1", "attack": shapes["attack"], "block": "5-3-2"}
    assert res.meta["away"]["formation"] == "5-3-2" and res.meta["away"]["startFormation"] == "4-2-3-1"
    assert res.meta["away"]["shapes"]["block"] == "4-4-1-1"  # the start formation's shapes are kept for the team sheet


def test_formation_change_keeps_every_player_on_a_distinct_slot(clubs):
    m = MatchSim("fc", clubs["HAR"], clubs["NOR"], seed=1)
    m._change_formation(1, "3-4-3")
    assert sorted(m.slot_idx[1]) == list(range(10))
    assert [r for r in m.slot_role[1]].count("CB") == 3
    assert m.formation_name[1] == "3-4-3"


# ----- phases of play: build-up, attack, press, mid block and low block, and the tactics that play them ---------------


def test_every_formation_has_a_build_up_and_a_press_shape():
    from matchmind.sim import tactics as TA

    for name in TA.formation_names():
        for ph in ("build", "press", "low"):
            lay = TA.layout(name, ph)
            assert len(lay) == 10 and all(0.0 <= d <= 1.0 and 0.0 <= w <= 1.0 for d, w in lay), (name, ph)
        shapes = TA.describe_shapes(name, {})
        assert shapes["build"] and shapes["press"] and shapes["rest"].startswith("CB"), name
        # The low block is the block squeezed: never deeper-to-higher than the block it comes from.
        assert max(d for d, _ in TA.layout(name, "low")) <= max(d for d, _ in TA.layout(name, "block"))
    # A lone pivot dropping into the back line changes the first phase of build-up (a back three).
    assert TA.describe_shapes("4-3-3", {"pivot": "drop"})["build"] == "3-2-2-3"
    assert TA.describe_shapes("4-2-3-1", {})["press"] == "4-4-2", "the ten joins the striker in a 4-2-3-1 press"


@pytest.fixture(scope="module")
def phase_match(clubs):
    """A high-pressing side against a back five that sits deep."""
    from matchmind.sim.engine import simulate

    return simulate("ph", clubs["NOR"], clubs["ALD"], seed=5)


def test_a_pressing_team_and_a_low_block_spend_their_time_differently(phase_match):
    nor, ald = phase_match.meta["home"]["phases"], phase_match.meta["away"]["phases"]
    sec = lambda ph, k: ph.get(k, {"seconds": 0.0})["seconds"]  # noqa: E731
    assert sec(nor, "press") > 2 * sec(ald, "press"), "the gegenpress side presses far more"
    assert sec(nor, "press") > sec(nor, "low"), "and presses more than it sits"
    assert sec(ald, "low") > 3 * sec(ald, "press"), "the back five defends low far more than it presses"
    for ph in (nor, ald):
        assert ph["low"]["lineHeightM"] < ph["attack"]["lineHeightM"] - 10.0, "a low block really is lower than a settled attack"
        assert ph["build"]["lineHeightM"] < ph["attack"]["lineHeightM"] - 10.0, "build-up starts deeper than the settled attack"
    assert nor["press"]["lineHeightM"] > nor["low"]["lineHeightM"] + 3.0, "a press holds a higher line than a low block"


def test_phase_changes_are_announced_with_the_reason(phase_match):
    pcs = [e for e in phase_match.events if e["type"] == "phase_change"]
    assert len(pcs) > 100
    allowed = {"own_third", "settled", "counterpress", "regroup", "protecting_lead", "deep_line", "wide_carrier", "press_zone", "ball_beyond_press_line"}
    assert {e["attributes"]["cause"] for e in pcs} <= allowed
    for e in pcs:
        assert e["attributes"]["phase"] != e["attributes"]["previous"]
    # A team that counter-presses on losing the ball does it often; ALD regroup instead.
    count = lambda club: sum(1 for e in pcs if e["team"] == club and e["attributes"]["cause"] == "counterpress")  # noqa: E731
    assert count("NOR") > count("ALD")


def test_a_team_that_regroups_does_not_counter_press(clubs):
    from matchmind.sim.engine import MatchSim

    keep = _club_with(clubs["HAR"], on_loss="regroup")
    press = _club_with(clubs["HAR"], on_loss="counterpress")
    a = MatchSim("a", keep, clubs["RED"], seed=9)
    b = MatchSim("b", press, clubs["RED"], seed=9)
    ra, rb = a.run(), b.run()
    n = lambda r: sum(1 for e in r.events if e["type"] == "phase_change" and e["team"] == "HAR" and e["attributes"]["cause"] == "counterpress")  # noqa: E731
    assert n(rb) > 2 * n(ra), (n(ra), n(rb))
