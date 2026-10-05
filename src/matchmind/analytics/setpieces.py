"""Set-piece report: what each routine produced, and how each defence coped.

For every corner, dangerous free kick, long throw and goal kick we know the routine the team chose.
The report counts them, adds the shots and expected goals that followed within twelve seconds, and
splits what a team *conceded* by how it defends corners (zonal, man or mixed). It is the sort of
set-piece review Opta publishes, built on the routines the data feed tags.
"""

from __future__ import annotations

from collections import defaultdict

FOLLOW_MS = 12_000
KINDS = ("corner", "free_kick", "throw_in", "goal_kick")


def _blank() -> dict:
    return {"n": 0, "shots": 0, "xg": 0.0, "goals": 0}


def set_piece_report(events: list[dict], meta: dict) -> dict:
    clubs = [meta["home"]["id"], meta["away"]["id"]]
    style = {meta[s]["id"]: meta[s].get("style", {}) for s in ("home", "away")}
    shots = [e for e in events if e["type"] == "shot"]
    passes = [e for e in events if e["type"] == "pass"]
    taken = {c: defaultdict(lambda: defaultdict(_blank)) for c in clubs}
    conceded = {c: defaultdict(_blank) for c in clubs}
    goal_kick_first_pass = {c: defaultdict(lambda: [0, 0]) for c in clubs}
    for e in events:
        r = (e.get("attributes") or {}).get("routine")
        if e["type"] not in KINDS or not r:
            continue
        if e["type"] == "free_kick" and r == "quick":
            continue
        if e["type"] == "throw_in" and r != "long":
            continue
        team = e["team"]
        slot = taken[team][e["type"]][r]
        slot["n"] += 1
        if e["type"] == "goal_kick":
            nxt = next((p for p in passes if p["_ms"] > e["_ms"] and p["team"] == team and p["_ms"] - e["_ms"] < 4000), None)
            if nxt is not None:
                goal_kick_first_pass[team][r][0] += 1
                goal_kick_first_pass[team][r][1] += nxt.get("outcome") == "complete"
            continue
        follow = [s for s in shots if s["team"] == team and 0 <= s["_ms"] - e["_ms"] <= FOLLOW_MS]
        slot["shots"] += len(follow)
        slot["xg"] += sum(float(s.get("_xg", 0.0)) for s in follow)
        slot["goals"] += sum(s.get("outcome") == "goal" for s in follow)
        if e["type"] == "corner":
            opp = clubs[1 - clubs.index(team)]
            defence = style[opp].get("corner_defence", "zonal")
            c = conceded[opp][defence]
            c["n"] += 1
            c["shots"] += len(follow)
            c["xg"] += sum(float(s.get("_xg", 0.0)) for s in follow)
            c["goals"] += sum(s.get("outcome") == "goal" for s in follow)

    def clean(d: dict) -> dict:
        return {k: ({kk: (round(vv, 3) if isinstance(vv, float) else vv) for kk, vv in v.items()} if isinstance(v, dict) else v) for k, v in d.items()}

    out: dict = {"teams": {}}
    for c in clubs:
        out["teams"][c] = {
            "taken": {k: {r: clean(v) for r, v in rs.items()} for k, rs in taken[c].items()},
            "conceded": {k: clean(v) for k, v in conceded[c].items()},
            "defence": style[c].get("corner_defence", "zonal"),
            "goalKickFirstPass": {r: {"n": n, "complete": ok, "rate": round(ok / n, 2) if n else None} for r, (n, ok) in goal_kick_first_pass[c].items()},
        }
    return out
