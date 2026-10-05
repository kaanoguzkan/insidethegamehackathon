"""Pressing and defensive-block report built from events: where the team presses and what triggers it."""

from __future__ import annotations

from ..core import geometry as G

TRIGGER_MS = 2_000


def pressing_report(events: list[dict], clubs: list[str]) -> dict:
    out = {}
    passes = [e for e in events if e["type"] == "pass"]
    for c in clubs:
        opp = clubs[1 - clubs.index(c)]
        pressures = [e for e in events if e["type"] == "pressure" and e["team"] == c and "_ax" in e]
        zones = {"high": 0, "middle": 0, "low": 0}
        for p in pressures:
            ax = p["_ax"]
            zones["high" if ax >= G.FINAL_THIRD_X else "low" if ax < G.PITCH_L / 3 else "middle"] += 1
        triggers = {"backPass": 0, "badPass": 0, "other": 0}
        for p in pressures:
            prior = [q for q in passes if q["team"] == opp and 0 <= p["_ms"] - q["_ms"] <= TRIGGER_MS]
            q = prior[-1] if prior else None
            kind = "other"
            if q is not None:
                if q.get("attributes", {}).get("passType") == "back":
                    kind = "backPass"
                elif q.get("outcome") != "complete" or (q.get("_diff") or 0) >= 6.5:
                    kind = "badPass"
            triggers[kind] += 1
        # PPDA by zone: opponent passes in a zone per defensive action of ours in the same zone, zones
        # measured from the pressing team's goal (high = the opponent's own third).
        def zone(x_from_own_goal: float) -> str:
            return "high" if x_from_own_goal >= G.FINAL_THIRD_X else "low" if x_from_own_goal < G.PITCH_L / 3 else "middle"

        opp_passes = {"high": 0, "middle": 0, "low": 0}
        actions = {"high": 0, "middle": 0, "low": 0}
        for e in events:
            if "_ax" not in e:
                continue
            if e["type"] == "pass" and e["team"] == opp:
                opp_passes[zone(G.PITCH_L - e["_ax"])] += 1
            elif e["type"] in ("tackle", "interception", "foul") and e["team"] == c:
                actions[zone(e["_ax"])] += 1
        ppda_zone = {z: (round(opp_passes[z] / actions[z], 1) if actions[z] >= 3 else None) for z in opp_passes}
        n = len(pressures) or 1
        out[c] = {
            "ppdaByZone": ppda_zone,
            "pressures": len(pressures),
            "zoneShare": {k: round(v / n, 3) for k, v in zones.items()},
            "triggerShare": {k: round(v / n, 3) for k, v in triggers.items()},
        }
    return out
