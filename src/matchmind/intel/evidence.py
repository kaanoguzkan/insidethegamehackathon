"""Evidence packs: the only facts the language agents are allowed to use.

An evidence pack is a flat, self-describing record of one moment: what happened, which
metrics moved and by how much, which events and players are involved, and a glossary of
the metrics it mentions. Agents cite its keys; the Verifier checks every number and name in
their output against it. Derived values (change, percentage change) are precomputed here so
no model ever has to do arithmetic.
"""

from __future__ import annotations

from typing import Any

# Metric key (the part after "CLUB.") -> plain-language definition and which direction is "more".
GLOSSARY: dict[str, str] = {
    "ppda": "Passes allowed per defensive action in the opponent's build-up zone. Lower means more aggressive pressing; higher means the team has stopped pressing.",
    "nearest_defender_m": "Average distance in metres from the ball to the nearest defender while the team does not have it. Smaller means the team closes the ball down quickly; larger means it has stopped pressing.",
    "players_near_ball": "Average number of the team's outfield players within 8 metres of the ball while out of possession.",
    "pressures_per_min": "Pressure events per minute: how often defenders close down the ball carrier.",
    "front_sprints": "Sprints (25 km/h or faster for at least one second) by the front-line attackers in the window.",
    "sprints": "Sprints (25 km/h or faster for at least one second) by outfield players in the window.",
    "high_regains": "Times the team won the ball back in the opposition's final third in the window.",
    "progressive_passes": "Completed passes that move the ball at least 10 metres toward goal.",
    "final_third_entries": "Times the team moved the ball into the final third by pass or carry.",
    "field_tilt": "Share of all final-third passes made by this team: who is pinning whom back.",
    "possession_share": "Share of the ball in the window.",
    "xt": "Expected threat added: the value gained by moving the ball into more dangerous areas, plus shot quality.",
    "xg": "Expected goals: the summed quality of the team's shots.",
    "shots": "Shots taken.",
    "big_chances": "Shots worth at least 0.30 xG.",
    "chaos_index": "0-100 score for how chaotic play is: many turnovers and duels, short possessions, long balls. 50 is a typical five minutes of this league; low means orderly control.",
    "turnovers_per_min": "Changes of possession per minute.",
    "duels_per_min": "Tackles and fouls per minute.",
    "avg_possession_s": "Average length of a possession in seconds.",
    "tempo": "Passes per minute of possession.",
    "events_per_min": "Match events per minute: the overall rhythm of play.",
    "line_height_m": "Average distance from own goal of the four deepest outfield players while the team is defending with the ball in the middle of the pitch, in metres: how high the defensive line sits.",
    "width_m": "Distance between the widest outfield players while the team is defending with the ball in the middle of the pitch, in metres.",
    "sprint_rate": "Sprints per five minutes.",
    "peak_kmh": "Peak speed in kilometres per hour.",
    "xg_shot": "Expected goals of this single shot.",
    "shot_speed_kmh": "Measured speed of the shot in kilometres per hour.",
    "distance_m": "Distance in metres.",
    "pass_difficulty": "0-10 rating of how hard a pass was to complete, from distance, pressure and the passing lane.",
}


def change(before: float | None, after: float | None, digits: int = 1) -> dict[str, Any]:
    """A before/after metric with its delta and percentage change precomputed.

    Everything is derived from the *rounded* values, so a reader who subtracts the numbers in
    the pack gets exactly the delta in the pack.
    """
    b, a = _r(before, digits), _r(after, digits)
    out: dict[str, Any] = {"before": b, "after": a}
    if b is not None and a is not None:
        out["delta"] = round(a - b, digits)
        if abs(b) > 1e-9:
            out["changePct"] = round(100.0 * (a - b) / abs(b), 0)
    return out


def annotate_consistency(metrics: dict[str, Any], expected: dict[str, int]) -> None:
    """Mark each metric ``consistent`` (or not) with the story the detector is telling.

    ``expected`` maps a metric key to +1 (should rise) or -1 (should fall) if the story is true.
    A metric that moved the other way is kept in the pack but flagged, so a narrator cannot
    quietly cherry-pick the numbers that fit and has to be honest about mixed evidence.
    """
    for key, sign in expected.items():
        m = metrics.get(key)
        if not m or "delta" not in m:
            continue
        if m["delta"] == 0:
            m["consistent"] = None
        else:
            m["consistent"] = (m["delta"] > 0) == (sign > 0)


def value(v: float | None, digits: int = 1) -> dict[str, Any]:
    return {"value": _r(v, digits)}


def _r(v: float | None, digits: int) -> float | None:
    return None if v is None else round(float(v), digits)


def glossary_for(metrics: dict[str, Any]) -> dict[str, str]:
    """Glossary entries for the metric names present in ``metrics`` (keys like ``NOR.ppda``)."""
    out = {}
    for key in metrics:
        base = key.split(".", 1)[-1]
        if base in GLOSSARY:
            out[base] = GLOSSARY[base]
    return out


def numbers_in(obj: Any) -> list[float]:
    """Every number in an evidence pack, for the Verifier's numeric check."""
    found: list[float] = []

    def walk(x: Any) -> None:
        if isinstance(x, bool):
            return
        if isinstance(x, (int, float)):
            found.append(float(x))
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    walk(obj)
    return found
