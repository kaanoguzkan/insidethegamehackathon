"""Hand-built evidence packs, one per moment type, shaped like the interpreter's output.

The simulated match does not contain every moment type, so tests that must cover all of them
(templates, verifier, workflow) use these. ``test_packs_match_interpreter_shape`` keeps them
honest against real packs.
"""

from __future__ import annotations

import copy

TEAMS = {"HAR": "Harbour City", "NOR": "Northbridge Athletic"}
SHORT = {"HAR": "Harbour", "NOR": "Northbridge"}
PLAYERS = [
    {"id": "HAR-09", "name": "Marco Quinski", "team": "HAR", "pos": "ST"},
    {"id": "NOR-07", "name": "Zane Pelandal", "team": "NOR", "pos": "RW"},
    {"id": "HAR-08", "name": "Adrian Yararsen", "team": "HAR", "pos": "CM"},
]


def _base(type_: str, **kw) -> dict:
    pack = {
        "id": f"t-mo-{type_}",
        "matchId": "t",
        "type": type_,
        "detectedAt": {"matchMs": 3_600_000, "clock": {"period": 2, "minute": 60, "second": 0, "matchMs": 3_600_000}, "label": "60'"},
        "salience": 0.6,
        "subjectTeam": "NOR",
        "beneficiaryTeam": "HAR",
        "teamNames": dict(TEAMS),
        "teamShort": dict(SHORT),
        "windows": {
            "before": {"range": [1_800_000, 2_700_000], "label": "45'-55'"},
            "after": {"range": [3_120_000, 3_600_000], "label": "52'-60'"},
        },
        "metrics": {},
        "facts": {"score": {"HAR": 2, "NOR": 1}},
        "eventIds": ["t-e00010"],
        "players": copy.deepcopy(PLAYERS),
        "glossary": {},
        "status": "detected",
    }
    pack.update(kw)
    return pack


def _chg(before, after, digits=1, consistent=None):
    d = round(after - before, digits)
    out = {"before": before, "after": after, "delta": d}
    if before:
        out["changePct"] = round(100 * d / abs(before))
    if consistent is not None:
        out["consistent"] = consistent
    return out


def packs() -> dict[str, dict]:
    out = {}
    out["goal"] = _base(
        "goal", subjectTeam="HAR", beneficiaryTeam="HAR", metrics={"HAR.xg_shot": {"value": 0.31}},
        facts={"score": {"HAR": 2, "NOR": 1}, "assist": "HAR-08", "xg": 0.31, "bodyPart": "foot", "situation": "open_play"},
        players=[PLAYERS[0], PLAYERS[2]],
    )
    out["red_card"] = _base("red_card", subjectTeam="NOR", beneficiaryTeam="HAR", facts={"score": {"HAR": 1, "NOR": 1}, "secondYellow": True}, players=[PLAYERS[1]])
    out["penalty"] = _base("penalty", subjectTeam="NOR", beneficiaryTeam="HAR", facts={"score": {"HAR": 1, "NOR": 1}, "fouled": "HAR-09"}, players=[PLAYERS[1], PLAYERS[0]])
    out["big_chance"] = _base(
        "big_chance", subjectTeam="HAR", beneficiaryTeam=None,
        metrics={"HAR.xg_shot": {"value": 0.42}}, facts={"score": {"HAR": 0, "NOR": 0}, "xg": 0.42, "outcome": "saved"},
        players=[PLAYERS[0]],
    )
    press = {
        "NOR.nearest_defender_m": _chg(5.6, 9.7, consistent=True),
        "NOR.players_near_ball": _chg(1.4, 0.7, consistent=True),
        "NOR.pressures_per_min": _chg(1.7, 0.9, consistent=True),
        "NOR.ppda": _chg(34.1, 15.4, consistent=False),
        "NOR.front_sprints": _chg(1.3, 0.6, consistent=True),
        "HAR.progressive_passes": _chg(7.7, 10.6, consistent=True),
        "HAR.xt": _chg(0.2, 0.09, 2, consistent=False),
        "match.chaos_index": _chg(44, 31, 0),
    }
    out["pressure_collapse"] = _base("pressure_collapse", metrics=press)
    surge = {k.replace("NOR", "HAR") if "NOR" in k else k.replace("HAR", "NOR"): v for k, v in press.items()}
    out["pressure_surge"] = _base("pressure_surge", subjectTeam="HAR", beneficiaryTeam="HAR", metrics=surge)
    out["momentum_swing"] = _base(
        "momentum_swing", subjectTeam="HAR", beneficiaryTeam="HAR",
        metrics={"HAR.xt": _chg(0.05, 0.3, 2), "NOR.xt": _chg(0.2, 0.1, 2)},
    )
    out["chaos_flip"] = _base(
        "chaos_flip", subjectTeam=None, beneficiaryTeam=None,
        metrics={"match.chaos_index": _chg(32, 61, 0), "match.turnovers_per_min": _chg(2.1, 4.4)},
        facts={"score": {"HAR": 1, "NOR": 1}, "direction": "control_to_chaos", "controller": "HAR"},
    )
    out["rhythm_break"] = _base(
        "rhythm_break", subjectTeam="HAR", beneficiaryTeam=None, metrics={"HAR.tempo": _chg(15.2, 22.0)},
        facts={"score": {"HAR": 1, "NOR": 1}, "direction": "faster", "trigger": "goal"},
    )
    out["tactical_shift"] = _base(
        "tactical_shift", subjectTeam="NOR", beneficiaryTeam=None,
        metrics={"NOR.line_height_m": _chg(31.2, 48.6), "NOR.width_m": _chg(44.0, 47.5)},
        facts={"score": {"HAR": 1, "NOR": 1}, "line": "higher", "width": "wider", "lineShifted": True, "widthShifted": False},
    )
    out["fatigue_drop"] = _base("fatigue_drop", subjectTeam="NOR", beneficiaryTeam="HAR", metrics={"NOR.sprint_rate": _chg(5.8, 2.1)})
    out["physical_highlight"] = _base(
        "physical_highlight", subjectTeam="HAR", beneficiaryTeam=None,
        metrics={"HAR.peak_kmh": {"value": 34.1}}, facts={"score": {"HAR": 1, "NOR": 0}, "kind": "top_speed"},
        players=[PLAYERS[0]],
    )
    return out
