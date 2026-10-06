"""Phases of play: how long each team spent building, attacking, pressing and defending, and what each looked like.

The simulator announces a ``phase_change`` event whenever a team settles into a new working shape (build-up
in its own third, the settled attack, a high press, the mid block, the low block), with the reason. This
turns those events into a timeline, shares of the match and, with the shape measured in each phase
(defensive-line height, team length and width in metres), shows that a press, a block and a build-up really
are different shapes, and which cues set each one off.
"""

from __future__ import annotations

from ..sim.tactics import PHASES


def phases_report(events: list[dict], meta: dict, clubs: list[str], end_ms: int) -> dict:
    out: dict[str, dict] = {}
    for side, club in zip(("home", "away"), clubs, strict=True):
        mine = [e for e in events if e["type"] == "phase_change" and e["team"] == club]
        mine.sort(key=lambda e: e["_ms"])
        segments: list[list] = []  # [start ms, phase index]
        if mine:
            segments.append([0, PHASES.index(mine[0]["attributes"]["previous"])])
        entries = {p: 0 for p in PHASES}
        causes: dict[str, dict[str, int]] = {p: {} for p in PHASES}
        for e in mine:
            a = e["attributes"]
            segments.append([int(e["_ms"]), PHASES.index(a["phase"])])
            entries[a["phase"]] += 1
            c = a.get("cause") or "other"
            causes[a["phase"]][c] = causes[a["phase"]].get(c, 0) + 1
        ms_in = {p: 0 for p in PHASES}
        for i, (start, idx) in enumerate(segments):
            stop = segments[i + 1][0] if i + 1 < len(segments) else end_ms
            ms_in[PHASES[idx]] += max(0, stop - start)
        total = sum(ms_in.values()) or 1
        measured = meta[side].get("phases", {})
        out[club] = {
            "segments": segments,
            "share": {p: round(ms_in[p] / total, 3) for p in PHASES},
            "entries": entries,
            "causes": {p: c for p, c in causes.items() if c},
            "measured": {p: measured[p] for p in PHASES if p in measured},
        }
    return out
