"""The detector: find the players and the ball in a frame, from the pixels alone.

Colour segmentation per team and for the ball, connected components, a centroid for each blob. Two players who overlap make one big blob, which is
split by its area (how many players' worth of pixels it holds) with a few rounds of k-means. The ball's apparent size gives its height.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from .render import AWAY, BALL_R_M, HOME, PLAYER_R_M, PX, to_m

PLAYER_AREA = np.pi * (PLAYER_R_M * PX) ** 2  # pixels
BALL_AREA = np.pi * (BALL_R_M * PX) ** 2
MIN_BLOB = 0.35 * PLAYER_AREA


@dataclass
class Detections:
    home: np.ndarray  # (k, 2) metres
    away: np.ndarray
    ball: np.ndarray | None  # (3,) metres x, y, height; None when not seen
    blobs: list[tuple[str, float, float, float]] = field(default_factory=list)  # (kind, px, py, radius px) for drawing


def _close(img: np.ndarray, colour: np.ndarray, tol: int) -> np.ndarray:
    d = np.abs(img - colour.astype(np.int16)).sum(axis=2)  # city-block distance in colour space: cheaper than a norm, as good for flat team colours
    return d < tol


def _split(coords: np.ndarray, k: int) -> list[np.ndarray]:
    """k centres for the pixels of a merged blob (k-means from spread-out starting points)."""
    c = coords[np.linspace(0, len(coords) - 1, k).astype(int)].astype(np.float64)
    order = np.argsort(coords[:, 0] + coords[:, 1])
    c = coords[order[np.linspace(0, len(order) - 1, k).astype(int)]].astype(np.float64)
    for _ in range(6):
        lab = np.argmin(((coords[:, None, :] - c[None]) ** 2).sum(-1), axis=1)
        for j in range(k):
            if (lab == j).any():
                c[j] = coords[lab == j].mean(0)
    return list(c)


def _blobs(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Connected blobs of a mask: (label of each true pixel, its x, its y, area per label, number of labels). Counting with bincount is much faster than
    asking scipy for a statistic per blob."""
    lab, n = ndimage.label(mask)
    ys, xs = np.nonzero(mask)
    return lab[ys, xs], xs + 0.5, ys + 0.5, np.bincount(lab[ys, xs], minlength=n + 1), n


def _team_points(mask: np.ndarray) -> list[tuple[float, float]]:
    lab, xs, ys, area, n = _blobs(mask)
    out: list[tuple[float, float]] = []
    if n == 0:
        return out
    sx, sy = np.bincount(lab, xs, minlength=n + 1), np.bincount(lab, ys, minlength=n + 1)
    for i in range(1, n + 1):
        if area[i] < MIN_BLOB:
            continue
        k = int(np.clip(round(area[i] / PLAYER_AREA), 1, 4))
        if k == 1:
            out.append((sx[i] / area[i], sy[i] / area[i]))
        else:
            sel = lab == i
            pts = np.stack([xs[sel], ys[sel]], axis=1)
            out.extend((float(p[0]), float(p[1])) for p in _split(pts, k))
    return out


def detect(img: np.ndarray) -> Detections:
    px = img.astype(np.int16)
    teams = []
    blobs: list[tuple[str, float, float, float]] = []
    for kind, col in (("home", HOME), ("away", AWAY)):
        pts = _team_points(_close(px, col, 110))
        blobs += [(kind, x, y, PLAYER_R_M * PX) for x, y in pts]
        xs, ys = (np.array([p[0] for p in pts]), np.array([p[1] for p in pts])) if pts else (np.zeros(0), np.zeros(0))
        mx, my = to_m(xs, ys)
        teams.append(np.stack([mx, my], axis=1) if len(pts) else np.zeros((0, 2)))
    # The ball is the white blob that is not a line: lines are long and thin, so keep compact blobs of about a ball's size
    lab, xs, ys, area, n = _blobs(np.min(px, axis=2) > 222)
    ball = None
    best = 1e9
    for i in range(1, n + 1):
        if not (0.5 * BALL_AREA <= area[i] <= 6.0 * BALL_AREA):
            continue
        score = abs(area[i] - BALL_AREA)
        if score < best:
            best = score
            sel = lab == i
            cx, cy, r_px = float(xs[sel].mean()), float(ys[sel].mean()), float(np.sqrt(area[i] / np.pi))
            bx, by = to_m(cx, cy)
            height = max(0.0, (r_px / (BALL_R_M * PX) - 1.0) * 5.0)  # the apparent size says how high the ball is
            ball = np.array([float(bx), float(by), min(height, 25.0)])
            ball_px = (cx, cy, r_px)
    if ball is not None:
        blobs.append(("ball", ball_px[0], ball_px[1], ball_px[2]))
    return Detections(home=teams[0], away=teams[1], ball=ball, blobs=blobs)
