"""Goalkeeper report: shot-stopping against post-shot xG, and distribution."""

from __future__ import annotations

import numpy as np

from .xgot import XGOT


def goalkeeper_report(events: list[dict], clubs: list[str], players: dict[str, dict], xgot: XGOT) -> dict:
    out: dict[str, dict] = {}
    for c in clubs:
        gks = [pid for pid, p in players.items() if p["team"] == c and p["pos"] == "GK"]
        keeper = next((g for g in gks if any(e.get("player") == g for e in events)), gks[0] if gks else None)
        if keeper is None:
            continue
        faced = [e for e in events if e["type"] == "shot" and e["team"] != c]
        on_target = [e for e in faced if e.get("outcome") in ("goal", "saved")]
        pso = sum(xgot.value(e) or 0.0 for e in on_target)
        conceded = sum(e.get("outcome") == "goal" for e in on_target)
        saves = [e for e in events if e["type"] == "save" and e.get("player") == keeper]
        claims = [e for e in events if e["type"] == "claim" and e.get("player") == keeper]
        sweeping = [e for e in events if e.get("player") == keeper and e["type"] in ("clearance", "interception", "ball_recovery") and e.get("_ax", 0) > 16.5]
        dist = [e for e in events if e["type"] == "pass" and e.get("player") == keeper and "_eax" in e]
        lengths = [float(np.hypot(e["_eax"] - e["_ax"], e["_eay"] - e["_ay"])) for e in dist]
        out[c] = {
            "player": keeper, "name": players[keeper]["name"],
            "shotsFaced": len(faced), "onTarget": len(on_target), "saves": len(saves), "goalsConceded": conceded,
            "xgotFaced": round(pso, 2), "goalsPrevented": round(pso - conceded, 2), "claims": len(claims), "sweeperActions": len(sweeping),
            "passes": len(dist), "passCompletion": round(sum(e.get("outcome") == "complete" for e in dist) / len(dist), 2) if dist else None,
            "avgPassLengthM": round(float(np.mean(lengths)), 1) if lengths else None,
            "longShare": round(sum(L >= 35 for L in lengths) / len(lengths), 2) if lengths else None,
        }
    return out
