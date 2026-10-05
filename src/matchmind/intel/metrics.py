"""Window metrics and the three explainability indices.

``compute_window`` turns the events inside a time window into per-team and match-level
numbers (PPDA, pressures, field tilt, possession, tempo, sprint counts, turnovers ...).
``indices`` turns those into the scores a viewer actually reads:

* **Control vs Chaos** (0-100, match level) and who is in control
* **Pressure index** (per team)
* **Rhythm** (tempo, event rate, stoppages)

Chaos and pressure are z-scored against league baselines so "62" means "more chaotic than a
typical five minutes of this league", not an arbitrary scale.
"""

from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Callable

from ..core import geometry as G

BALL_TYPES = ("pass", "carry", "shot", "dribble", "clearance")
DEF_ACTIONS = ("tackle", "interception", "foul")
STOPPAGE_TYPES = ("throw_in", "goal_kick", "corner", "free_kick", "offside", "kickoff")
LONG_KINDS = ("long", "switch", "goal_kick")
BUILD_ZONE_OPP_X = 0.60 * G.PITCH_L  # the opponent's own 60% of the pitch, in *their* attack frame
ATTACKING_GROUPS = ("ATT",)


def window_slice(events: list[dict], times: list[int], t0: int, t1: int) -> list[dict]:
    return events[bisect_left(times, t0) : bisect_right(times, t1)]


def compute_window(
    events: list[dict],
    t0: int,
    t1: int,
    clubs: list[str],
    players: dict[str, dict],
    xt: Callable[[float, float], float],
    big_chance_xg: float = 0.30,
) -> dict:
    """Metrics for events with ``t0 < _ms <= t1``. Events must be normalised (``_ms``, ``_ax`` ...)."""
    minutes = max((t1 - t0) / 60000.0, 1e-6)
    per = {c: Counter() for c in clubs}
    match = Counter()
    possessions: dict[str, list] = {}
    poss_ms = Counter()
    last_ball: dict | None = None

    for e in events:
        t = e["type"]
        c = e.get("team")
        if t in BALL_TYPES and c in per:
            pid = e.get("possessionId")
            if pid:
                s = possessions.setdefault(pid, [c, e["_ms"], e["_ms"]])
                s[2] = e["_ms"]
            if last_ball is not None:
                same = last_ball.get("possessionId") == pid
                gap = e["_ms"] - last_ball["_ms"]
                poss_ms[last_ball["team"]] += min(6000 if same else 2000, gap)
            last_ball = e

        if c in per:
            p = per[c]
            if t == "pass":
                p["passes"] += 1
                done = e.get("outcome") == "complete"
                p["pass_complete"] += done
                kind = e["attributes"].get("passType")
                match["passes"] += 1
                match["long_balls"] += kind in LONG_KINDS
                if e.get("_ax", 99) < BUILD_ZONE_OPP_X:
                    p["build_passes"] += 1  # passes in our own 60%: the *opponent's* PPDA numerator
                if done and "_eax" in e:
                    fwd = e["_eax"] - e["_ax"]
                    if fwd >= 10.0 and e["_eax"] >= 35.0:
                        p["progressive_passes"] += 1
                    if e["_eax"] >= G.FINAL_THIRD_X:
                        p["final_third_passes"] += 1
                        if e["_ax"] < G.FINAL_THIRD_X:
                            p["final_third_entries"] += 1
                    p["xt_gain"] += max(0.0, xt(e["_eax"], e["_eay"]) - xt(e["_ax"], e["_ay"]))
                if "_diff" in e:
                    p["difficulty_sum"] += e["_diff"]
                    p["difficulty_n"] += 1
                if done and "_bypassed" in e:
                    p["packing"] += e["_bypassed"]
                    p["line_breaks"] += e["_lines"] >= 1
            elif t in ("carry", "dribble") and e.get("outcome") == "complete" and "_eax" in e:
                p["carries"] += t == "carry"
                p["dribbles"] += t == "dribble"
                p["xt_gain"] += max(0.0, xt(e["_eax"], e["_eay"]) - xt(e["_ax"], e["_ay"]))
                if e["_eax"] >= G.FINAL_THIRD_X and e["_ax"] < G.FINAL_THIRD_X:
                    p["final_third_entries"] += 1
            elif t == "shot":
                p["shots"] += 1
                xg_v = e.get("_xg", 0.0)
                p["xg"] += xg_v
                p["xt_gain"] += xg_v
                p["big_chances"] += xg_v >= big_chance_xg
                p["on_target"] += e.get("outcome") in ("goal", "saved")
                p["goals"] += e.get("outcome") == "goal"
            elif t == "pressure":
                p["pressures"] += 1
            elif t == "tackle":
                p["tackles"] += 1
                match["duels"] += 1
            elif t == "interception":
                p["interceptions"] += 1
            elif t == "foul":
                p["fouls"] += 1
                match["duels"] += 1
            elif t == "sprint":
                p["sprints"] += 1
                if players.get(e["player"], {}).get("group") in ATTACKING_GROUPS:
                    p["front_sprints"] += 1
            if t in DEF_ACTIONS and e.get("_ax", 0.0) >= G.PITCH_L - BUILD_ZONE_OPP_X:
                p["def_actions_build"] += 1  # PPDA denominator: our defensive actions in their build-up
            if t in ("ball_recovery", "interception") or (t == "tackle" and e.get("outcome") == "won"):
                p["recoveries"] += 1
                if e.get("_ax", 0.0) >= 70.0:
                    p["high_regains"] += 1
        if t == "possession_change" and e.get("attributes", {}).get("cause") not in ("kickoff", None):
            match["turnovers"] += 1
        if t in STOPPAGE_TYPES:
            match["stoppages"] += 1
        match["events"] += 1

    durations = [(b - a) / 1000.0 for _, a, b in possessions.values()]
    total_poss = sum(poss_ms.values()) or 1

    out: dict = {"t0": t0, "t1": t1, "minutes": minutes}
    for i, c in enumerate(clubs):
        o = clubs[1 - i]
        p, q = per[c], per[o]
        passes = p["passes"]
        poss_s = poss_ms[c] / 1000.0
        ppda = q["build_passes"] / p["def_actions_build"] if p["def_actions_build"] else None
        out[c] = {
            "passes": passes,
            "pass_complete": p["pass_complete"],
            "pass_acc": p["pass_complete"] / passes if passes else None,
            "possession_share": poss_ms[c] / total_poss,
            "possession_s": poss_s,
            "tempo": passes / (poss_s / 60.0) if poss_s >= 20 else None,
            "ppda": ppda,
            "opp_build_passes": q["build_passes"],
            "def_actions_build": p["def_actions_build"],
            "pressures": p["pressures"],
            "pressures_per_min": p["pressures"] / minutes,
            "high_regains": p["high_regains"],
            "recoveries": p["recoveries"],
            "tackles": p["tackles"],
            "interceptions": p["interceptions"],
            "fouls": p["fouls"],
            "progressive_passes": p["progressive_passes"],
            "final_third_entries": p["final_third_entries"],
            "field_tilt": (
                p["final_third_passes"] / (p["final_third_passes"] + q["final_third_passes"])
                if (p["final_third_passes"] + q["final_third_passes"]) else 0.5
            ),
            "shots": p["shots"],
            "xg": p["xg"],
            "big_chances": p["big_chances"],
            "goals": p["goals"],
            "xt": p["xt_gain"],
            "sprints": p["sprints"],
            "front_sprints": p["front_sprints"],
            "carries": p["carries"],
            "packing": p["packing"],
            "line_breaks": p["line_breaks"],
            "avg_pass_difficulty": p["difficulty_sum"] / p["difficulty_n"] if p["difficulty_n"] else None,
        }  # fmt: skip
    out["match"] = {
        "turnovers_per_min": match["turnovers"] / minutes,
        "duels_per_min": match["duels"] / minutes,
        "long_ball_share": match["long_balls"] / match["passes"] if match["passes"] else None,
        "avg_possession_s": sum(durations) / len(durations) if durations else None,
        "events_per_min": match["events"] / minutes,
        "stoppages_per_min": match["stoppages"] / minutes,
        "passes": match["passes"],
    }
    return out


# ---------------------------------------------------------------------------------------------
# Indices
# ---------------------------------------------------------------------------------------------

DEFAULT_BASELINES = {
    # Mean / std over five-minute windows of the simulated league. ``matchmind baselines``
    # regenerates data/league/baselines.json; these are only the fallback.
    "turnovers_per_min": (4.1, 1.0),
    "duels_per_min": (0.95, 0.4),
    "long_ball_share": (0.12, 0.05),
    "avg_possession_s": (13.0, 3.0),
    "log_ppda": (math.log(9.0), 0.35),
    "pressures_per_min": (3.2, 1.0),
    "high_regains": (1.5, 1.2),
    "tempo": (14.0, 3.0),
}


def _z(value: float | None, name: str, baselines: dict, invert: bool = False) -> float | None:
    if value is None:
        return None
    mean, std = baselines.get(name) or DEFAULT_BASELINES[name]
    z = (value - mean) / max(std, 1e-6)
    return -z if invert else z


def _logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def indices(win: dict, clubs: list[str], baselines: dict | None = None) -> dict:
    """Control-vs-chaos, pressure and rhythm indices for a window."""
    b = baselines or {}
    m = win["match"]
    parts = [
        _z(m["turnovers_per_min"], "turnovers_per_min", b),
        _z(m["duels_per_min"], "duels_per_min", b),
        _z(m["long_ball_share"], "long_ball_share", b),
        _z(m["avg_possession_s"], "avg_possession_s", b, invert=True),
    ]
    parts = [p for p in parts if p is not None]
    z_chaos = sum(parts) / len(parts) if parts else 0.0
    chaos = round(100.0 * _logistic(1.2 * z_chaos), 1)

    shares = {}
    for c in clubs:
        w = win[c]
        shares[c] = 0.6 * w["possession_share"] + 0.4 * w["field_tilt"]
    controller = max(clubs, key=lambda c: shares[c])

    pressure = {}
    for c in clubs:
        w = win[c]
        zs = []
        if w["ppda"] is not None and w["opp_build_passes"] >= 6:
            zs.append(_z(math.log(max(w["ppda"], 0.5)), "log_ppda", b, invert=True))
        zs.append(_z(w["pressures_per_min"], "pressures_per_min", b))
        zs.append(_z(w["high_regains"], "high_regains", b))
        zs = [z for z in zs if z is not None]
        z = sum(zs) / len(zs) if zs else 0.0
        pressure[c] = round(100.0 * _logistic(1.2 * z), 1)

    rhythm = {}
    for c in clubs:
        w = win[c]
        rhythm[c] = {"tempo": w["tempo"]}
    return {
        "chaos": chaos,
        "control": {"controller": controller, "share": {c: round(shares[c], 3) for c in clubs}},
        "pressure": pressure,
        "rhythm": {
            "events_per_min": round(m["events_per_min"], 2),
            "stoppages_per_min": round(m["stoppages_per_min"], 2),
            "tempo": {c: (round(rhythm[c]["tempo"], 1) if rhythm[c]["tempo"] else None) for c in clubs},
        },
    }
