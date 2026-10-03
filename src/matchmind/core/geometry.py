"""Pitch geometry.

Absolute coordinates are metres on a 105 x 68 m pitch, x along the length and y across.
The home team attacks +x in the first half and -x in the second; the away team the reverse.

Most football logic is easier in a team's *attack frame*: x grows toward the goal the team
is attacking, so ``ax == 105`` is the opponent's goal line whichever way the team faces.
The frame is a 180 degree rotation, so left and right keep their meaning.
"""

from __future__ import annotations

import math

PITCH_L = 105.0
PITCH_W = 68.0
CX = PITCH_L / 2
CY = PITCH_W / 2

GOAL_W = 7.32
POST_LO = CY - GOAL_W / 2
POST_HI = CY + GOAL_W / 2

BOX_DEPTH = 16.5
BOX_HALF_W = 20.16
SIX_DEPTH = 5.5
SIX_HALF_W = 9.16
PENALTY_SPOT = 11.0

FINAL_THIRD_X = PITCH_L * 2 / 3


def to_att(x: float, y: float, direction: int) -> tuple[float, float]:
    """Absolute -> attack frame (and back: the transform is its own inverse)."""
    if direction == 1:
        return x, y
    return PITCH_L - x, PITCH_W - y


from_att = to_att


def dist(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def goal_dist(ax: float, ay: float) -> float:
    """Distance to the centre of the goal being attacked, in the attack frame."""
    return math.hypot(PITCH_L - ax, ay - CY)


def shot_angle(ax: float, ay: float) -> float:
    """Angle (radians) subtended by the goalposts from a point in the attack frame."""
    dx = max(PITCH_L - ax, 0.3)
    return abs(math.atan2(POST_HI - ay, dx) - math.atan2(POST_LO - ay, dx))


def in_box(ax: float, ay: float) -> bool:
    return ax >= PITCH_L - BOX_DEPTH and abs(ay - CY) <= BOX_HALF_W


def in_six_yard_box(ax: float, ay: float) -> bool:
    return ax >= PITCH_L - SIX_DEPTH and abs(ay - CY) <= SIX_HALF_W


def in_final_third(ax: float) -> bool:
    return ax >= FINAL_THIRD_X


def third(ax: float) -> int:
    """0 = defensive, 1 = middle, 2 = final third."""
    return 0 if ax < PITCH_L / 3 else (1 if ax < FINAL_THIRD_X else 2)


def zone(ax: float, ay: float, nx: int = 12, ny: int = 8) -> tuple[int, int]:
    ix = min(nx - 1, max(0, int(ax / PITCH_L * nx)))
    iy = min(ny - 1, max(0, int(ay / PITCH_W * ny)))
    return ix, iy


def clamp_pitch(x: float, y: float, margin: float = 0.0) -> tuple[float, float]:
    return (
        min(PITCH_L - margin, max(margin, x)),
        min(PITCH_W - margin, max(margin, y)),
    )


def segment_distance(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> tuple[float, float]:
    """Distance from point P to segment AB and the projection parameter t in [0, 1]."""
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 < 1e-9:
        return math.hypot(px - ax, py - ay), 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def clock_label(minute: int, period: int) -> str:
    """Display label for a match minute: ``63'`` or ``45+2'`` in stoppage time."""
    if period == 1 and minute >= 45:
        return f"45+{minute - 45}'" if minute > 45 else "45'"
    if period == 2 and minute >= 90:
        return f"90+{minute - 90}'" if minute > 90 else "90'"
    return f"{minute}'"
