"""Pitch control: who would get to each part of the pitch first.

A simplified time-to-reach model in the spirit of Fernandez and Bornn's pitch control (and the space
metrics Second Spectrum and SkillCorner publish): a cell belongs to the team whose nearest player
could reach it sooner, with a logistic blend so that contested cells are neither team's. The web app
implements the *same formula* (``web/src/lib/control.ts``) and a test keeps the two in step.
"""

from __future__ import annotations

import numpy as np

from ..core import geometry as G

NX, NY = 21, 14  # 5 m x 4.86 m cells
VMAX = 7.0  # m/s a player is assumed able to reach
K = 2.2  # logistic sharpness per second of arrival-time difference

_cx = (np.arange(NX) + 0.5) * G.PITCH_L / NX
_cy = (np.arange(NY) + 0.5) * G.PITCH_W / NY
CELLS = np.stack(np.meshgrid(_cx, _cy), axis=-1).reshape(-1, 2)  # (NY*NX, 2), row-major: iy then ix
CELL_AREA = (G.PITCH_L / NX) * (G.PITCH_W / NY)


def home_control(pos: np.ndarray) -> np.ndarray:
    """P(home team controls the cell) for the 22 players in ``pos`` (home 0-10, away 11-21), shape (NY, NX)."""
    d = np.hypot(CELLS[:, None, 0] - pos[None, :, 0], CELLS[:, None, 1] - pos[None, :, 1])
    d = np.where(np.isnan(d), np.inf, d)
    t = d / VMAX
    ta, tb = t[:, :11].min(axis=1), t[:, 11:].min(axis=1)
    z = np.clip(K * (tb - ta), -30, 30)
    return (1.0 / (1.0 + np.exp(-z))).reshape(NY, NX)


def attack_x_grid(direction: int) -> np.ndarray:
    """x of every cell in a team's attack frame, shape (NY, NX)."""
    x = np.tile(_cx, (NY, 1))
    return x if direction == 1 else G.PITCH_L - x


def team_control(pos: np.ndarray, team_index: int) -> np.ndarray:
    p = home_control(pos)
    return p if team_index == 0 else 1.0 - p
