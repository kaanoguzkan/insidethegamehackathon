"""Formation recognised from tracking: how a team actually lined up, not how the team sheet says.

A team's average positions (while defending with the ball in the middle of the pitch, and while in
possession) are matched against a library of formation templates by optimal assignment, the way tracking
providers detect formations: depth is rescaled to the team's own spread, each player is paired with the
template slot that fits best, and the template with the smallest total misfit names the shape. The
library holds the nominal formations and the shapes they turn into with and without the ball (a 4-3-3
that defends as a 4-5-1 and builds as a 3-2-5), so the output reads like an analyst's description.
"""

from __future__ import annotations

import numpy as np

from ..core import geometry as G
from ..sim import tactics as TA
from ..sim.teams import GROUP

W_DEPTH, W_WIDTH = 1.0, 0.8
ROLE_GROUP_PENALTY = 0.45
ROLE_NEAR_PENALTY = 0.12
MIN_FRAMES = 25


def _normalise_depth(depth: np.ndarray) -> np.ndarray:
    lo, hi = float(depth.min()), float(depth.max())
    return (depth - lo) / max(hi - lo, 1e-6)


def _library() -> list[tuple[str, str, str, np.ndarray, list[str]]]:
    """(label, source formation, phase, (10, 2) normalised depth and width, role of each slot)."""
    out: list[tuple[str, str, str, np.ndarray, list[str]]] = []

    def add(label: str, name: str, phase: str, lay: list[tuple[float, float]]) -> None:
        a = np.array(lay, dtype=float)
        a[:, 0] = _normalise_depth(a[:, 0])
        out.append((label, name, phase, a, TA.roles(name)))

    for name in TA.formation_names():
        add(name, name, "both", TA.layout(name, "base"))
        add(TA.describe_shapes(name, {})["block"], name, "def", TA.layout(name, "block"))
        add(TA.ATTACK_LABEL[name], name, "ip", TA.layout(name, "attack"))
        if name in TA.ATTACK_LABEL_PIVOT_DROP:
            add(TA.ATTACK_LABEL_PIVOT_DROP[name], name, "ip", TA.apply_attack_tags(name, TA.layout(name, "attack"), {"pivot": "drop"}))
    return out


_LIB: list[tuple[str, str, str, np.ndarray, list[str]]] | None = None


def library() -> list[tuple[str, str, str, np.ndarray, list[str]]]:
    global _LIB
    if _LIB is None:
        _LIB = _library()
    return _LIB


def _role_penalty(player_role: str, slot_role: str) -> float:
    """How badly a player of one position fits a slot meant for another (0 = same role)."""
    if player_role == slot_role:
        return 0.0
    if GROUP.get(player_role) != GROUP.get(slot_role):
        return ROLE_GROUP_PENALTY
    return ROLE_NEAR_PENALTY


def read_formation(points: list[tuple[float, float]], phase: str | None = None, roles: list[str] | None = None) -> dict | None:
    """Name the shape of ten outfield average positions in the team's attack frame.

    ``phase`` ("def" or "ip") restricts the library to the shapes that make sense for it: out of
    possession the nominal formations and their blocks, in possession the nominal formations and their
    attacking shapes.
    """
    if len(points) < 9:
        return None
    obs = np.array(points[:10], dtype=float)
    obs = np.column_stack([_normalise_depth(obs[:, 0]), obs[:, 1] / G.PITCH_W])
    best: tuple[float, str, str] | None = None
    second: float | None = None
    seen: dict[str, float] = {}
    for label, name, tphase, tpl, slot_roles in library():
        if len(obs) != len(tpl) or (phase is not None and tphase not in (phase, "both")):
            continue
        d = np.hypot(W_DEPTH * (obs[:, None, 0] - tpl[None, :, 0]), W_WIDTH * (obs[:, None, 1] - tpl[None, :, 1]))
        if roles is not None:  # the team sheet says who plays where: a centre-back is not a striker slot
            d = d + np.array([[_role_penalty(r, s) for s in slot_roles] for r in roles[: len(obs)]])
        cols = TA.assign(d.tolist())
        cost = float(sum(d[i, c] for i, c in enumerate(cols))) / len(obs)
        if label not in seen or cost < seen[label]:
            seen[label] = cost
        if best is None or cost < best[0]:
            best = (cost, label, name)
    if best is None:
        return None
    ranked = sorted(seen.items(), key=lambda kv: kv[1])
    second = ranked[1][1] if len(ranked) > 1 else None
    return {
        "label": best[1], "from": best[2], "misfit": round(best[0], 3),
        "margin": round((second - best[0]) if second is not None else 0.0, 3), "runnerUp": ranked[1][0] if len(ranked) > 1 else None,
    }


def measured_shapes(profile: dict[str, list], phase: str | None = None, positions: dict[str, str] | None = None) -> dict | None:
    """Label a ``{player: [x, y, frames]}`` profile, using the ten players seen the most (the XI, not the bench).

    ``positions`` (player id to listed position) lets the matcher use the team sheet's roles.
    """
    regulars = sorted(((pid, v) for pid, v in profile.items() if v[2] >= MIN_FRAMES), key=lambda kv: -kv[1][2])[:10]
    roles = [positions.get(pid, "CM") for pid, _ in regulars] if positions else None
    return read_formation([(v[0], v[1]) for _, v in regulars], phase, roles)
