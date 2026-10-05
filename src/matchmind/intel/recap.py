"""Recap evidence: everything a preview, half-time or full-time recap may say.

A recap is built like a moment: a *pack* of numbers and names that the writers draw on and the
Verifier checks against, so a recap cannot claim a stat, a scorer or a result the data does not
contain. Team statistics come from the same window metrics the interpreter uses live.
"""

from __future__ import annotations

import re
from collections import Counter

from ..core.clock import clock_from_ms, label
from .evidence import glossary_for

KINDS = ("preview", "half_time", "full_time")
STORY_TYPES = {
    "goal", "red_card", "penalty", "big_chance", "pressure_collapse", "pressure_surge",
    "momentum_swing", "fatigue_drop", "tactical_shift",
}  # fmt: skip

# Style dials -> short descriptors, strongest first. Used in previews.
STYLE_TAGS = (
    ("press_high", lambda s: s["press_intensity"] >= 0.7 and s["press_height"] >= 0.65),
    ("counter", lambda s: s["counter_bias"] >= 0.7),
    ("direct", lambda s: s["directness"] >= 0.65),
    ("patient", lambda s: s["directness"] <= 0.3),
    ("deep", lambda s: s["line_height"] <= 0.3),
    ("wide", lambda s: s["width"] >= 0.8),
)


def style_tags(style: dict, limit: int = 2) -> list[str]:
    return [name for name, test in STYLE_TAGS if test(style)][:limit]


def _round(v: float | None, d: int) -> float | None:
    return None if v is None else round(float(v), d)


def team_stats(win: dict, club: str) -> dict:
    w = win[club]
    return {
        "possession_share": _round(w["possession_share"], 2),
        "shots": int(w["shots"]),
        "xg": _round(w["xg"], 1),
        "passes": int(w["passes"]),
        "pass_acc": _round(w["pass_acc"], 2) if w["pass_acc"] is not None else None,
        "big_chances": int(w["big_chances"]),
        "goals": int(w["goals"]),
    }


def player_ratings(ip, t0: int, t1: int) -> list[dict]:
    """A simple, transparent contribution score; the player of the match is the top of this list."""
    c: dict[str, Counter] = {}
    for e in ip.events:
        if not (t0 <= e["_ms"] <= t1) or not e.get("player"):
            continue
        k = c.setdefault(e["player"], Counter())
        t = e["type"]
        if t == "goal":
            k["goals"] += 1
            a = e["attributes"].get("assist")
            if a:
                c.setdefault(a, Counter())["assists"] += 1
        elif t == "shot":
            k["shots"] += 1
        elif t in ("tackle", "interception"):
            k["defensive"] += 1
        elif t == "pass" and e.get("outcome") == "complete" and e.get("_diff", 0) >= ip.cfg.key_pass_difficulty:
            k["hard_passes"] += 1
        elif t == "sprint":
            k["sprints"] += 1
    out = []
    for pid, k in c.items():
        if pid not in ip.players:
            continue
        score = 3.0 * k["goals"] + 2.0 * k["assists"] + 0.4 * k["shots"] + 0.25 * k["defensive"] + 0.5 * k["hard_passes"] + 0.05 * k["sprints"]
        out.append({"id": pid, "score": round(score, 2), **{n: int(k[n]) for n in ("goals", "assists", "shots", "defensive", "hard_passes", "sprints")}})
    return sorted(out, key=lambda r: -r["score"])


def _score_path(ip, t_end: int) -> list[tuple[int, dict]]:
    path = [(0, {c: 0 for c in ip.clubs})]
    cur = dict(path[0][1])
    for e in ip.events:
        if e["type"] == "goal" and e["_ms"] <= t_end:
            cur = {**cur, e["team"]: cur[e["team"]] + 1}
            path.append((e["_ms"], cur))
    return path


def build_pack(ip, kind: str) -> dict:
    """Evidence pack for a recap of ``kind`` (half_time / full_time) from the interpreter's state."""
    meta = ip.meta
    if kind == "half_time":
        t_end = meta["periods"][0].get("endMs") or ip.p2_start_ms or 45 * 60000
    else:
        t_end = meta["periods"][-1].get("endMs") or int(meta["frames"] * 1000 / meta["hz"])
    clubs = ip.clubs
    win = ip.window(0, t_end)
    path = _score_path(ip, t_end)
    final = path[-1][1]
    worst = {c: max((p[1][ip._other(c)] - p[1][c]) for p in path) for c in clubs}  # biggest deficit faced
    winner = max(clubs, key=lambda c: final[c]) if final[clubs[0]] != final[clubs[1]] else None
    comeback = None
    for c in clubs:
        if worst[c] >= 2 and final[c] >= final[ip._other(c)]:
            comeback = c
    moments = [m for m in ip.all_moments if m["detectedAt"]["matchMs"] <= t_end and m["type"] in STORY_TYPES]
    top = sorted(moments, key=lambda m: -m["salience"])[:5]
    top.sort(key=lambda m: m["detectedAt"]["matchMs"])
    ratings = player_ratings(ip, 0, t_end)
    potm = ratings[0] if ratings and ratings[0]["score"] > 0 else None
    swing = None
    if kind == "full_time":
        from ..analytics.report import (
            MatchAnalytics,  # imported here: analytics depends on the interpreter
        )

        an = MatchAnalytics(ip)
        best = an.player_of_the_match()
        if best is not None and an.valuer.ready and (best["goals"] or best["value"]):
            counts = next((r for r in ratings if r["id"] == best["id"]), {"shots": best["shots"], "goals": best["goals"], "assists": best["assists"]})
            potm = {"id": best["id"], "score": best["impact"], "goals": best["goals"], "assists": best["assists"], "shots": best["shots"], **{k: counts.get(k, 0) for k in ("defensive", "hard_passes", "sprints")}}
        sw = max((x for x in an.win_probability()["swings"] if x["kind"] == "goal"), key=lambda x: x["swing"], default=None)
        if sw and sw["swing"] >= 0.1:
            goal = next((e for e in ip.events if e["type"] == "goal" and e["_ms"] == sw["matchMs"]), None)
            if goal is not None:
                side = "home" if goal["team"] == ip.clubs[0] else "away"
                swing = {"team": goal["team"], "label": ip.minute_label(sw["matchMs"]), "before": round(100 * sw["before"][side]), "after": round(100 * sw["after"][side])}

    metrics: dict[str, dict] = {}
    for c in clubs:
        for k, v in team_stats(win, c).items():
            if v is not None:
                metrics[f"{c}.{k}"] = {"value": v}
    clock = clock_from_ms(t_end, ip.p2_start_ms)
    # The turning point is the story that changed the match, not just the loudest moment.
    decisive = {"pressure_collapse": 3, "pressure_surge": 3, "red_card": 3, "penalty": 2, "tactical_shift": 2, "momentum_swing": 1}
    turning = max((m for m in top if m["type"] in decisive), key=lambda m: (decisive[m["type"]], m["salience"]), default=None)
    players = []
    for pid in dict.fromkeys([*(r["id"] for r in ratings[:1]), *(p["id"] for m in top for p in m["players"])]):
        if pid in ip.players:
            players.append({"id": pid, "name": ip.players[pid]["name"], "team": ip.players[pid]["team"], "pos": ip.players[pid]["pos"]})
    return {
        "id": f"{ip.match_id}-recap-{kind}",
        "matchId": ip.match_id,
        "type": f"recap_{kind}",
        "detectedAt": {"matchMs": t_end, "clock": clock, "label": label(clock)},
        "salience": 1.0,
        "subjectTeam": winner,
        "beneficiaryTeam": winner,
        "teamNames": dict(ip.club_names),
        "teamShort": dict(ip.club_short),
        "windows": {"after": {"range": [0, t_end], "label": f"0'-{label(clock)}"}},
        "metrics": metrics,
        "facts": {
            "score": final,
            "winner": winner,
            "comeback": comeback,
            "deficit": worst[comeback] if comeback else 0,
            "halfTimeScore": next((p[1] for p in reversed(path) if p[0] <= (ip.p2_start_ms or t_end)), path[0][1]),
            "keyMinutes": [int(x) for m in top for x in re.findall(r"\d+", m["detectedAt"]["label"])],
            "potm": potm,
            "swing": swing,
            "turningMoment": turning["id"] if turning else None,
        },
        "eventIds": [e for m in top for e in m["eventIds"][:1]],
        "players": players,
        "keyMoments": [m["id"] for m in top],
        "glossary": glossary_for(metrics),
        "status": "detected",
    }


def build_preview_pack(meta: dict, season: dict | None = None) -> dict:
    home, away = meta["home"], meta["away"]

    def star(team: dict) -> dict:
        lineup = [pid for pid in team["lineup"] if team["players"][pid]["pos"] != "GK"]
        best = max(lineup, key=lambda pid: team["players"][pid].get("rating", 0))
        return {"id": best, "name": team["players"][best]["name"], "team": team["id"], "pos": team["players"][best]["pos"]}

    stars = [star(home), star(away)]
    facts_extra: dict = {}
    pred = (season or {}).get("prediction")
    if pred:
        h, a = home["id"], away["id"]
        table = {r["club"]: r for r in season["standings"]}
        facts_extra = {
            "prediction": {"homePct": round(100 * pred["home"]), "drawPct": round(100 * pred["draw"]), "awayPct": round(100 * pred["away"]),
                           "favourite": h if pred["home"] - pred["away"] >= 0.08 else a if pred["away"] - pred["home"] >= 0.08 else None},
            "table": {c: {"pos": table[c]["pos"], "pts": table[c]["pts"]} for c in (h, a) if c in table},
        }
    start = {t["id"]: t.get("startFormation", t["formation"]) for t in (home, away)}  # not the post-change shape
    clock = {"period": 1, "minute": 0, "second": 0, "matchMs": 0}
    return {
        "id": f"{meta['matchId']}-recap-preview",
        "matchId": meta["matchId"],
        "type": "recap_preview",
        "detectedAt": {"matchMs": 0, "clock": clock, "label": "0'"},
        "salience": 1.0,
        "subjectTeam": home["id"],
        "beneficiaryTeam": None,
        "teamNames": {home["id"]: home["name"], away["id"]: away["name"]},
        "teamShort": {home["id"]: home["short"], away["id"]: away["short"]},
        "windows": {},
        "metrics": {},
        "facts": {
            "score": {home["id"]: 0, away["id"]: 0},
            "formations": start,
            "formationNumbers": sorted({int(x) for f in start.values() for x in re.findall(r"\d", f)}),
            "styles": {home["id"]: style_tags(home.get("style", {}) or _NEUTRAL), away["id"]: style_tags(away.get("style", {}) or _NEUTRAL)},
            **facts_extra,
        },
        "eventIds": [],
        "players": stars,
        "keyMoments": [],
        "glossary": {},
        "status": "detected",
    }


_NEUTRAL = {"press_intensity": 0.5, "press_height": 0.5, "directness": 0.5, "tempo": 0.5, "width": 0.5, "line_height": 0.5, "counter_bias": 0.5}
