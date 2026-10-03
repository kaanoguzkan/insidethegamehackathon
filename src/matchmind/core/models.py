"""Shared football models used by both the simulator and the interpreter.

Keeping one definition of xG, xPass and zone threat means the numbers the simulator
*generates* from and the numbers the interpreter *reports* are the same function, so an
"explanation" built from them is consistent with how the match actually unfolded.
"""

from __future__ import annotations

import math

from .geometry import goal_dist, shot_angle

# Calibration constants. The realism report (``matchmind report-realism``) checks the
# resulting league averages against target bands; adjust here, not in call sites.
XG_INTERCEPT = -0.95
XPASS_INTERCEPT = 3.25


def sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def threat(ax: float, ay: float) -> float:
    """Analytic zone threat in the attack frame (a smooth stand-in for xT).

    About 0.006 at midfield, 0.03 at 30 m from goal, 0.17 on the penalty spot and
    0.24 in the six-yard box. The fitted xT grid in ``intel.xt`` replaces this for
    reporting; the simulator uses this one for decisions.
    """
    d = goal_dist(ax, ay)
    return 0.004 + 0.30 * math.exp(-((d / 16.0) ** 1.35))


_ASSIST_LOGIT = {
    "open": 0.0,
    "through": 0.60,
    "cutback": 0.40,
    "cross": -0.15,
    "corner": -0.10,
    "rebound": 0.15,
    "dribble": -0.05,
    "free_kick": -0.10,
}


def xg(
    ax: float,
    ay: float,
    *,
    body: str = "foot",
    assist: str = "open",
    pressure: float = 0.0,
    penalty: bool = False,
    direct_free_kick: bool = False,
) -> float:
    """Expected goals for a shot taken from (ax, ay) in the attack frame."""
    if penalty:
        return 0.78
    d = goal_dist(ax, ay)
    angle = shot_angle(ax, ay)
    z = XG_INTERCEPT + 1.15 * angle - 0.115 * d
    if direct_free_kick:
        z = -3.05 + 1.0 * angle - 0.045 * d
    if body == "head":
        z -= 0.65
    z += _ASSIST_LOGIT.get(assist, 0.0)
    z -= 0.9 * pressure
    return sigmoid(z)


_PASS_KIND_LOGIT = {
    "short": 0.20,
    "medium": 0.0,
    "long": -0.55,
    "through": -0.80,
    "cross": -1.35,
    "switch": -0.40,
    "back": 0.50,
    "throw_in": 0.55,
    "goal_kick": -0.15,
    "free_kick": -0.20,
    "corner": -0.70,
}


def xpass(
    distance: float,
    *,
    kind: str = "medium",
    pressure_receiver: float = 0.0,
    pressure_passer: float = 0.0,
    lane_block: float = 0.0,
    skill: float = 70.0,
    forward: float = 0.0,
) -> float:
    """Probability that a pass is completed."""
    z = XPASS_INTERCEPT - 0.032 * distance
    z -= 1.10 * pressure_receiver + 0.6 * pressure_passer + 0.8 * lane_block
    z += (skill - 70.0) * 0.02
    z += _PASS_KIND_LOGIT.get(kind, 0.0)
    z -= 0.025 * max(forward, 0.0)
    return sigmoid(z)


def pass_difficulty(p_complete: float) -> float:
    """Pass difficulty rating from 0 (trivial) to 10 (almost never completed)."""
    return round(10.0 * (1.0 - p_complete), 1)
