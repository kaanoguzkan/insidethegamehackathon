"""Transitions: what happens in the seconds after the ball changes hands.

Counter-pressing (did the team that lost the ball win it back within five seconds?), fast breaks
(from winning the ball to a shot or the final third inside ten seconds, in a handful of passes) and
high turnovers that produce a shot, the three transition measures Opta and StatsBomb publish.
"""

from __future__ import annotations

from ..core import geometry as G

OPEN_PLAY_CAUSES = ("tackle", "interception", "loose_ball")
COUNTERPRESS_MS = 5_000
FAST_BREAK_MS = 12_000
QUICK_ENTRY_MS = 10_000
FAST_BREAK_PASSES = 6
HIGH_TURNOVER_X = 70.0


def transition_report(events: list[dict], clubs: list[str], names: dict[str, str] | None = None) -> dict:
    changes = [e for e in events if e["type"] == "possession_change"]
    shots = [e for e in events if e["type"] == "shot"]
    passes = [e for e in events if e["type"] == "pass"]
    res = {c: {"lost": 0, "regained5s": 0, "wonOpenPlay": 0, "fastBreaks": [], "quickEntries": 0, "highTurnovers": 0, "highTurnoverShots": 0} for c in clubs}
    for i, ch in enumerate(changes):
        if ch.get("attributes", {}).get("cause") not in OPEN_PLAY_CAUSES or i == 0:
            continue
        winner = ch["team"]
        loser = clubs[1 - clubs.index(winner)]
        t0 = ch["_ms"]
        res[loser]["lost"] += 1
        res[winner]["wonOpenPlay"] += 1
        if any(c2["team"] == loser and 0 < c2["_ms"] - t0 <= COUNTERPRESS_MS for c2 in changes[i + 1 : i + 6]):
            res[loser]["regained5s"] += 1
        ax = ch.get("_ax", 0.0)
        if ax >= HIGH_TURNOVER_X:
            res[winner]["highTurnovers"] += 1
            if any(s["team"] == winner and 0 < s["_ms"] - t0 <= 15_000 for s in shots):
                res[winner]["highTurnoverShots"] += 1
        # A fast break ends in a shot inside twelve seconds and a handful of passes; reaching the final third
        # inside ten seconds is counted separately as a quick entry.
        if ax < 0.7 * G.PITCH_L:
            mine = [p for p in passes if p["team"] == winner and t0 < p["_ms"] <= t0 + FAST_BREAK_MS]
            lost_ball = next((c2 for c2 in changes[i + 1 :] if c2["_ms"] > t0 and c2["team"] != winner), None)
            until = min(t0 + FAST_BREAK_MS, lost_ball["_ms"] if lost_ball else 10**12)
            mine = [p for p in mine if p["_ms"] <= until]
            shot = next((s for s in shots if s["team"] == winner and t0 < s["_ms"] <= until), None)
            quick = any(p.get("_eax", 0.0) >= G.FINAL_THIRD_X and p["_ms"] - t0 <= QUICK_ENTRY_MS for p in mine) or (
                shot is not None and shot["_ms"] - t0 <= QUICK_ENTRY_MS
            )
            if quick and len(mine) <= FAST_BREAK_PASSES:
                res[winner]["quickEntries"] += 1
            if shot is not None and len(mine) <= FAST_BREAK_PASSES:
                res[winner]["fastBreaks"].append({
                    "ms": t0, "player": ch.get("player"), "fromX": round(ax, 1), "passes": len(mine),
                    "secondsToShot": round((shot["_ms"] - t0) / 1000.0, 1), "xg": round(float(shot.get("_xg", 0.0)), 3),
                    "goal": shot.get("outcome") == "goal",
                })
    out = {}
    for c, r in res.items():
        fb = r["fastBreaks"]
        out[c] = {
            "lost": r["lost"], "regained5s": r["regained5s"],
            "counterpressRate": round(r["regained5s"] / r["lost"], 3) if r["lost"] else None,
            "highTurnovers": r["highTurnovers"], "highTurnoverShots": r["highTurnoverShots"],
            "fastBreaks": len(fb), "fastBreakGoals": sum(x["goal"] for x in fb), "fastBreakXg": round(sum(x["xg"] for x in fb), 3),
            "quickEntries": r["quickEntries"],
            "fastBreakList": fb,
        }
    return out
