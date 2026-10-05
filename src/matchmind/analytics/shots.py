"""Shots: the shot map, the xG race and post-shot xG."""

from __future__ import annotations

from .xgot import XGOT


def shot_list(events: list[dict], xgot: XGOT) -> list[dict]:
    out = []
    for e in events:
        if e["type"] != "shot" or "_ax" not in e:
            continue
        a = e.get("attributes", {})
        out.append({
            "id": e["id"], "team": e["team"], "player": e["player"], "ms": e["_ms"],
            "x": round(e["_ax"], 1), "y": round(e["_ay"], 1), "xg": round(float(e.get("_xg", 0.0)), 3),
            "xgot": None if (v := xgot.value(e)) is None else round(v, 3), "outcome": e.get("outcome"),
            "situation": a.get("situation"), "bodyPart": a.get("bodyPart"),
            "goalMouthY": a.get("goalMouthY"), "goalMouthZ": a.get("goalMouthZ"),
        })
    return out


def xg_race(shots: list[dict], clubs: list[str], end_ms: int) -> dict:
    """Cumulative xG and goals per team as step series: [(ms, xG, goals)]."""
    series = {c: [(0, 0.0, 0)] for c in clubs}
    for s in sorted(shots, key=lambda s: s["ms"]):
        _, xg, g = series[s["team"]][-1]
        series[s["team"]].append((s["ms"], round(xg + s["xg"], 3), g + (s["outcome"] == "goal")))
    for c in clubs:
        _, xg, g = series[c][-1]
        series[c].append((end_ms, xg, g))
    return {c: [list(p) for p in v] for c, v in series.items()}
