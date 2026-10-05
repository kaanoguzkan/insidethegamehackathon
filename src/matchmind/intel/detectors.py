"""Moment detectors and salience.

Window detectors compare the last five minutes (*now*) with the ten before them (*prev*) and
fire when something genuinely changed: a team stopped pressing, the momentum flipped, play
turned from controlled to chaotic, the tempo broke, a defensive line moved, legs went.
Each returns a candidate whose ``metrics`` are the evidence pack's numbers, with before,
after, delta and percentage change precomputed.

Single-event moments (goals, red cards, big chances, penalties, physical highlights) are
created directly by the interpreter as the events arrive.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from ..core.clock import clock_from_ms, label
from .evidence import annotate_consistency, change, value

if TYPE_CHECKING:
    from .interpreter import Interpreter

TYPE_WEIGHT = {
    "goal": 1.00,
    "red_card": 0.90,
    "penalty": 0.80,
    "big_chance": 0.55,
    "pressure_collapse": 0.62,
    "pressure_surge": 0.55,
    "momentum_swing": 0.55,
    "chaos_flip": 0.50,
    "rhythm_break": 0.40,
    "tactical_shift": 0.45,
    "fatigue_drop": 0.45,
    "physical_highlight": 0.30,
}
WINDOW_TYPES = {
    "pressure_collapse", "pressure_surge", "momentum_swing", "chaos_flip",
    "rhythm_break", "tactical_shift", "fatigue_drop",
}  # fmt: skip


def salience(ip: Interpreter, pack: dict, magnitude: float) -> float:
    """How much a moment deserves to be told: type, size, game context, novelty."""
    t = pack["type"]
    base = TYPE_WEIGHT.get(t, 0.3)
    if t in ("goal", "red_card"):  # a goal that swings the match matters more than one at 4-0
        base *= 0.72 + 0.28 * min(1.0, pack["facts"].get("winProbSwing", 0.25) / 0.25)
    if t in WINDOW_TYPES:
        base *= 0.7 + 0.3 * min(1.0, magnitude)
    if t == "big_chance":
        base = min(0.8, 0.35 + 1.2 * max(0.0, pack["facts"].get("xg", 0.3) - 0.30))
    clock = pack["detectedAt"]["clock"]
    score = list(pack["facts"]["score"].values())
    close = len(score) == 2 and abs(score[0] - score[1]) <= 1
    ctx = 1.0 + (0.15 if clock["minute"] >= 75 else 0.0) + (0.15 if close else 0.0)
    ms = pack["detectedAt"]["matchMs"]
    repeated = any(
        m["type"] == t and m["subjectTeam"] == pack["subjectTeam"] and ms - m["detectedAt"]["matchMs"] < 15 * 60000
        for m in ip.recent_moments
    )
    return round(min(1.0, base * ctx * (0.6 if repeated else 1.0)), 2)


def per5(x: float, minutes: float) -> float:
    return x * 5.0 / max(minutes, 1e-6)


def _span(ip: Interpreter, t0: int, t1: int) -> dict:
    return {
        "range": [int(t0), int(t1)],
        "label": f"{ip.minute_label(max(0, int(t0)))}-{ip.minute_label(int(t1))}",
    }


def _events_in(ip: Interpreter, t0: int, t1: int, team: str, kinds: tuple[str, ...]) -> list[dict]:
    return [e for e in ip.events if t0 < e["_ms"] <= t1 and e.get("team") == team and e["type"] in kinds]


def _top_threat_events(ip: Interpreter, team: str, t0: int, t1: int, n: int = 3) -> list[dict]:
    scored = []
    for e in _events_in(ip, t0, t1, team, ("pass", "carry", "dribble")):
        if e.get("outcome") == "complete" and "_eax" in e:
            scored.append((ip.xt.value(e["_eax"], e["_eay"]) - ip.xt.value(e["_ax"], e["_ay"]), e))
    scored.sort(key=lambda s: -s[0])
    return [e for g, e in scored[:n] if g > 0]


def _best_shot(ip: Interpreter, team: str, t0: int, t1: int) -> dict | None:
    shots = _events_in(ip, t0, t1, team, ("shot",))
    return max(shots, key=lambda e: e.get("_xg", 0.0)) if shots else None


def _contributors(ip: Interpreter, events: list[dict], n: int = 2) -> list[str]:
    seen: dict[str, int] = {}
    for e in events:
        if e.get("player"):
            seen[e["player"]] = seen.get(e["player"], 0) + 1
    return [p for p, _ in sorted(seen.items(), key=lambda kv: -kv[1])[:n]]


# ---------------------------------------------------------------------------------------------
# Detectors
# ---------------------------------------------------------------------------------------------


def detect_window_moments(ip: Interpreter, t: int, now: dict, prev: dict, idx_now: dict, idx_prev: dict) -> list[dict]:
    out: list[dict] = []
    out += _pressure_shift(ip, t, now, prev, idx_now, idx_prev)
    out += _momentum_swing(ip, t, now, prev)
    out += _chaos_flip(ip, t, now, prev, idx_now, idx_prev)
    out += _rhythm_break(ip, t, now, prev)
    out += _tactical_shift(ip, t)
    out += _fatigue_drop(ip, t, now)
    return out


def _windows(ip: Interpreter, t: int) -> dict:
    c = ip.cfg
    return {
        "before": _span(ip, t - c.window_ms - c.prev_window_ms, t - c.window_ms),
        "after": _span(ip, t - c.window_ms, t),
    }


def smoothed_ppda(ip: Interpreter, w: dict, club: str) -> float | None:
    """PPDA shrunk toward the league mean: (passes + k*P0) / (actions + k)."""
    base = ip.baselines.get("log_ppda")
    p0 = math.exp(base[0]) if base else 10.0
    k = ip.cfg.ppda_prior_actions
    if w[club]["opp_build_passes"] == 0 and w[club]["def_actions_build"] == 0:
        return None
    return (w[club]["opp_build_passes"] + k * p0) / (w[club]["def_actions_build"] + k)


def _press_stats(ip: Interpreter, club: str, t0: int, t1: int) -> dict | None:
    """Frame-weighted nearest-defender distance while out of possession, from tracking snapshots."""
    n = tot = near = 0.0
    for e in ip.events:
        if e["type"] == "team_shape" and e["team"] == club and t0 < e["_ms"] <= t1:
            a = e["attributes"]
            w = a.get("pressFrames", 0)
            if w and "pressDistM" in a:
                n += w
                tot += w * a["pressDistM"]
                near += w * a["pressNear8"]
    if n == 0:
        return None
    return {"frames": int(n), "dist": tot / n, "near8": near / n}


def _press_direction(ip: Interpreter, c: str, t: int) -> tuple[str | None, float, dict | None, dict | None]:
    """Is team ``c``'s pressing clearly different at time ``t``? Returns (kind, gap m, after, before).

    Two independent signals must agree: the nearest-defender distance in the opponent's half
    (tracking) moved by at least ``press_gap_m``, and the pressure-event rate (events) moved the
    same way by at least ``press_corroboration``.
    """
    cfg = ip.cfg
    t_a, t_b = t - cfg.press_now_ms, t - cfg.press_now_ms - cfg.press_prev_ms
    sa, sb = _press_stats(ip, c, t_a, t), _press_stats(ip, c, t_b, t_a)
    if sa is None or sb is None or min(sa["frames"], sb["frames"]) < cfg.press_min_frames:
        return None, 0.0, sa, sb
    gap = sa["dist"] - sb["dist"]
    if abs(gap) < cfg.press_gap_m:
        return None, gap, sa, sb
    wa, wb = ip.window(t_a, t), ip.window(t_b, t_a)
    ra, rb = wa[c]["pressures_per_min"], wb[c]["pressures_per_min"]
    rel = (ra - rb) / rb if rb > 0 else 0.0
    if gap > 0 and rel <= -cfg.press_corroboration:
        return "pressure_collapse", gap, sa, sb
    if gap < 0 and rel >= cfg.press_corroboration:
        return "pressure_surge", gap, sa, sb
    return None, gap, sa, sb


def _pressure_shift(ip, t, now5, prev10, idx_now, idx_prev) -> list[dict]:
    cfg = ip.cfg
    t_a, t_b = t - cfg.press_now_ms, t - cfg.press_now_ms - cfg.press_prev_ms
    now = ip.window(t_a, t)
    prev = ip.window(t_b, t_a)
    mb, ma = prev["minutes"], now["minutes"]
    res = []
    for c in ip.clubs:
        o = ip._other(c)
        kind, rel, sa, sb = _press_direction(ip, c, t)  # rel is the gap in metres
        if kind is None:
            continue
        # A one-minute spike is noise; the shift has to hold at the previous evaluation too.
        prev_kind, _, _, _ = _press_direction(ip, c, t - cfg.eval_every_ms)
        if prev_kind != kind:
            continue
        beneficiary = o if kind == "pressure_collapse" else c
        a, b = now[c], prev[c]
        metrics = {
            f"{c}.nearest_defender_m": change(sb["dist"], sa["dist"], 1),
            f"{c}.players_near_ball": change(sb["near8"], sa["near8"], 1),
            f"{c}.pressures_per_min": change(b["pressures_per_min"], a["pressures_per_min"], 1),
            f"{c}.ppda": change(smoothed_ppda(ip, prev, c), smoothed_ppda(ip, now, c), 1),
            f"{c}.front_sprints": change(per5(b["front_sprints"], mb), per5(a["front_sprints"], ma), 1),
            f"{c}.high_regains": change(per5(b["high_regains"], mb), per5(a["high_regains"], ma), 1),
            f"{o}.progressive_passes": change(per5(prev[o]["progressive_passes"], mb), per5(now[o]["progressive_passes"], ma), 1),
            f"{o}.final_third_entries": change(per5(prev[o]["final_third_entries"], mb), per5(now[o]["final_third_entries"], ma), 1),
            f"{o}.xt": change(per5(prev[o]["xt"], mb), per5(now[o]["xt"], ma), 2),
            f"{o}.possession_share": change(prev[o]["possession_share"], now[o]["possession_share"], 2),
            "match.chaos_index": change(idx_prev["chaos"], idx_now["chaos"], 0),
        }  # fmt: skip
        sign = 1 if kind == "pressure_collapse" else -1  # collapse: distance up, activity down
        annotate_consistency(metrics, {
            f"{c}.nearest_defender_m": sign, f"{c}.players_near_ball": -sign, f"{c}.pressures_per_min": -sign,
            f"{c}.ppda": sign, f"{c}.front_sprints": -sign, f"{c}.high_regains": -sign,
            f"{o}.progressive_passes": sign, f"{o}.final_third_entries": sign, f"{o}.xt": sign,
            f"{o}.possession_share": sign,
        })  # fmt: skip
        extra_events = _top_threat_events(ip, beneficiary, t_a, t, 3)
        shot = _best_shot(ip, beneficiary, t_a, t)
        facts = {}
        if shot:
            metrics[f"{shot['team']}.last_chance_xg"] = value(shot.get("_xg"), 2)
            facts["lastChance"] = {
                "team": shot["team"], "player": shot["player"],
                "xg": round(shot.get("_xg", 0), 2), "outcome": shot.get("outcome"),
            }  # fmt: skip
        res.append(dict(
            type_=kind, ms=t, subject=c, beneficiary=beneficiary, metrics=metrics,
            events=[e["id"] for e in extra_events] + ([shot["id"]] if shot else []),
            players=_contributors(ip, extra_events + ([shot] if shot else [])),
            windows={"before": _span(ip, t_b, t_a), "after": _span(ip, t_a, t)},
            extra=facts, magnitude=min(1.0, abs(rel) / 0.8),
        ))  # fmt: skip
    return res


def _momentum_swing(ip, t, now, prev) -> list[dict]:
    cfg = ip.cfg
    res = []
    mb, ma = prev["minutes"], now["minutes"]
    for c in ip.clubs:
        o = ip._other(c)
        gap_now = now[c]["xt"] - now[o]["xt"]
        gap_prev = per5(prev[c]["xt"], mb) - per5(prev[o]["xt"], mb)
        if gap_now >= cfg.momentum_swing_gap and gap_prev <= -cfg.momentum_swing_min_prev_gap:
            metrics = {
                f"{c}.xt": change(per5(prev[c]["xt"], mb), now[c]["xt"], 2),
                f"{o}.xt": change(per5(prev[o]["xt"], mb), now[o]["xt"], 2),
                f"{c}.shots": change(per5(prev[c]["shots"], mb), per5(now[c]["shots"], ma), 1),
                f"{c}.xg": change(per5(prev[c]["xg"], mb), per5(now[c]["xg"], ma), 2),
                f"{c}.possession_share": change(prev[c]["possession_share"], now[c]["possession_share"], 2),
                f"{c}.field_tilt": change(prev[c]["field_tilt"], now[c]["field_tilt"], 2),
                f"{c}.final_third_entries": change(per5(prev[c]["final_third_entries"], mb), per5(now[c]["final_third_entries"], ma), 1),
            }  # fmt: skip
            top = _top_threat_events(ip, c, t - cfg.window_ms, t, 3)
            shot = _best_shot(ip, c, t - cfg.window_ms, t)
            res.append(dict(
                type_="momentum_swing", ms=t, subject=c, beneficiary=c, metrics=metrics,
                events=[e["id"] for e in top] + ([shot["id"]] if shot else []),
                players=_contributors(ip, top + ([shot] if shot else [])),
                windows=_windows(ip, t), extra={}, magnitude=min(1.0, gap_now / 0.3),
            ))  # fmt: skip
    return res


def _chaos_flip(ip, t, now, prev, idx_now, idx_prev) -> list[dict]:
    cfg = ip.cfg
    hist = [h["chaos"] for h in ip.history]
    if len(hist) < cfg.chaos_smooth_now + cfg.chaos_smooth_prev:
        return []
    cur = sum(hist[-cfg.chaos_smooth_now :]) / cfg.chaos_smooth_now
    old_vals = hist[-(cfg.chaos_smooth_now + cfg.chaos_smooth_prev) : -cfg.chaos_smooth_now]
    old = sum(old_vals) / len(old_vals)
    d = cur - old
    lvl = cfg.chaos_flip_level
    if d >= cfg.chaos_flip_delta and cur >= lvl > old:
        kind = "control_to_chaos"
    elif d <= -cfg.chaos_flip_delta and cur <= lvl < old:
        kind = "chaos_to_control"
    else:
        return []
    m, p = now["match"], prev["match"]
    controller = idx_now["control"]["controller"]
    metrics = {
        "match.chaos_index": change(old, cur, 0),
        "match.turnovers_per_min": change(p["turnovers_per_min"], m["turnovers_per_min"], 1),
        "match.duels_per_min": change(p["duels_per_min"], m["duels_per_min"], 2),
        "match.avg_possession_s": change(p["avg_possession_s"], m["avg_possession_s"], 1),
        f"{controller}.possession_share": change(prev[controller]["possession_share"], now[controller]["possession_share"], 2),
    }  # fmt: skip
    turns = [e["id"] for e in ip.events if t - cfg.window_ms < e["_ms"] <= t and e["type"] == "possession_change"][-4:]
    return [dict(
        type_="chaos_flip", ms=t, subject=None, beneficiary=controller if kind == "chaos_to_control" else None,
        metrics=metrics, events=turns, players=[], windows=_windows(ip, t),
        extra={"direction": kind, "controller": controller}, magnitude=min(1.0, abs(d) / 40.0),
    )]  # fmt: skip


def _rhythm_break(ip, t, now, prev) -> list[dict]:
    cfg = ip.cfg
    res = []
    for c in ip.clubs:
        a, b = now[c]["tempo"], prev[c]["tempo"]
        if a is None or b is None or b <= 0:
            continue
        rel = (a - b) / b
        if abs(rel) < cfg.rhythm_change:
            continue
        trigger = next(
            (e for e in reversed(ip.events)
             if t - cfg.window_ms < e["_ms"] <= t and e["type"] in ("goal", "card", "substitution")),
            None,
        )  # fmt: skip
        metrics = {
            f"{c}.tempo": change(b, a, 1),
            "match.events_per_min": change(prev["match"]["events_per_min"], now["match"]["events_per_min"], 1),
            f"{c}.possession_share": change(prev[c]["possession_share"], now[c]["possession_share"], 2),
        }  # fmt: skip
        res.append(dict(
            type_="rhythm_break", ms=t, subject=c, beneficiary=None, metrics=metrics,
            events=[trigger["id"]] if trigger else [], players=[trigger["player"]] if trigger and trigger.get("player") else [],
            windows=_windows(ip, t),
            extra={"direction": "faster" if rel > 0 else "slower", "trigger": trigger["type"] if trigger else None},
            magnitude=min(1.0, abs(rel)),
        ))  # fmt: skip
    return res


def _shape_mean(ip: Interpreter, team: str, t0: int, t1: int) -> dict | None:
    """Defensive shape (line height and width while defending, ball in the middle zone) over a window.

    Teams change shape with the ball and the line follows it, so comparing windows with different
    possession or ball height would report a "tactical shift" every time the match tilted. Only
    frames where the opponent had the ball in the middle of the pitch count.
    """
    shapes = [e for e in ip.events if e["type"] == "team_shape" and e["team"] == team and t0 < e["_ms"] <= t1]
    n = line = width = 0.0
    ids = []
    for s in shapes:
        a = s["attributes"]
        w = a.get("defFrames", 0)
        if w >= 10 and "lineHeightDefM" in a:
            n += w
            line += w * a["lineHeightDefM"]
            width += w * a["widthDefM"]
            ids.append(s["id"])
    if n < ip.cfg.shift_min_frames:
        return None
    return {"line": line / n, "width": width / n, "ids": ids[-2:]}


def _space_mean(ip: Interpreter, team: str, t0: int, t1: int) -> float | None:
    """Mean space (m^2) the opposition controlled behind the team's defensive line over a window, from tracking."""
    n = tot = 0.0
    for e in ip.events:
        if e["type"] == "space_control" and e["team"] == team and t0 < e["_ms"] <= t1:
            a = e["attributes"]
            if a.get("spaceBehindM2") is not None and a.get("behindSamples"):
                n += a["behindSamples"]
                tot += a["behindSamples"] * a["spaceBehindM2"]
    return tot / n if n >= 20 else None


def _shift_at(ip: Interpreter, c: str, t: int) -> tuple[dict, dict] | None:
    cfg = ip.cfg
    after = _shape_mean(ip, c, t - cfg.shift_after_ms, t)
    before = _shape_mean(ip, c, t - cfg.shift_after_ms - cfg.shift_before_ms, t - cfg.shift_after_ms)
    if after is None or before is None:
        return None
    return before, after


def _tactical_shift(ip, t) -> list[dict]:
    cfg = ip.cfg
    res = []
    for c in ip.clubs:
        now_ba = _shift_at(ip, c, t)
        prev_ba = _shift_at(ip, c, t - cfg.eval_every_ms)
        if now_ba is None or prev_ba is None:
            continue
        before, after = now_ba
        dl, dw = after["line"] - before["line"], after["width"] - before["width"]
        pl = prev_ba[1]["line"] - prev_ba[0]["line"]
        pw = prev_ba[1]["width"] - prev_ba[0]["width"]
        line_shift = abs(dl) >= cfg.shift_line_m and abs(pl) >= cfg.shift_line_m and dl * pl > 0
        width_shift = abs(dw) >= cfg.shift_width_m and abs(pw) >= cfg.shift_width_m and dw * pw > 0
        if not (line_shift or width_shift):
            continue
        metrics = {
            f"{c}.line_height_m": change(before["line"], after["line"], 1),
            f"{c}.width_m": change(before["width"], after["width"], 1),
        }
        sp0 = _space_mean(ip, c, t - cfg.shift_after_ms - cfg.shift_before_ms, t - cfg.shift_after_ms)
        sp1 = _space_mean(ip, c, t - cfg.shift_after_ms, t)
        if sp0 is not None and sp1 is not None:
            metrics[f"{c}.space_behind_m2"] = change(sp0, sp1, 0)
        res.append(dict(
            type_="tactical_shift", ms=t, subject=c, beneficiary=None, metrics=metrics, events=after["ids"],
            players=[],
            windows={
                "before": _span(ip, t - cfg.shift_after_ms - cfg.shift_before_ms, t - cfg.shift_after_ms),
                "after": _span(ip, t - cfg.shift_after_ms, t),
            },
            extra={
                "line": "higher" if dl > 0 else "deeper" if dl < 0 else "unchanged",
                "width": "wider" if dw > 0 else "narrower" if dw < 0 else "unchanged",
                "lineShifted": line_shift, "widthShifted": width_shift,
            },
            magnitude=min(1.0, max(abs(dl) / 14.0, abs(dw) / 16.0)),
        ))  # fmt: skip
    return res


def _fatigue_drop(ip, t, now) -> list[dict]:
    cfg = ip.cfg
    clock = clock_from_ms(t, ip.p2_start_ms)
    if clock["period"] != 2 or clock["minute"] < cfg.fatigue_min_minute:
        return []
    p1_end = ip.p2_start_ms or 45 * 60000
    wf = ip.window(t - cfg.fatigue_window_ms, t)
    res = []
    for c in ip.clubs:
        first_half = [e for e in ip.events if e["type"] == "sprint" and e["team"] == c and 5 * 60000 < e["_ms"] <= p1_end]
        base_rate = len(first_half) / max(1e-6, (p1_end - 5 * 60000) / 60000.0) * 5.0
        now_rate = per5(wf[c]["sprints"], wf["minutes"])
        if base_rate < 4.0 or now_rate > (1.0 - cfg.fatigue_drop) * base_rate:
            continue
        metrics = {
            f"{c}.sprint_rate": change(base_rate, now_rate, 1),
            f"{c}.pressures_per_min": {"value": round(wf[c]["pressures_per_min"], 1)},
        }
        windows = {"before": {"range": [5 * 60000, p1_end], "label": "first half"}, "after": _span(ip, t - cfg.fatigue_window_ms, t)}
        recent = _events_in(ip, t - cfg.fatigue_window_ms, t, c, ("sprint",))
        res.append(dict(
            type_="fatigue_drop", ms=t, subject=c, beneficiary=ip._other(c), metrics=metrics,
            events=[e["id"] for e in recent[-3:]], players=[], windows=windows, extra={},
            magnitude=min(1.0, 1.0 - now_rate / base_rate),
        ))  # fmt: skip
    return res


def window_label(ip: Interpreter, t0: int, t1: int) -> str:
    return f"{label(clock_from_ms(max(0, t0), ip.p2_start_ms))}-{label(clock_from_ms(t1, ip.p2_start_ms))}"
