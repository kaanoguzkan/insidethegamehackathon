"""Helpers shared by the analytics modules.

Analytics read the interpreter's *normalised* events: every event has ``_ms`` and, when it has a
location, ``_ax``/``_ay`` in the acting team's attack frame (x grows toward the goal it attacks).
"""

from __future__ import annotations

import numpy as np

from ..core import geometry as G

ACTIONS = (
    "pass", "carry", "dribble", "shot", "tackle", "interception", "clearance",
    "ball_recovery", "foul", "block", "save", "claim",
)  # fmt: skip
SUCCESS_OUTCOMES = {"pass": "complete", "carry": "complete", "dribble": "complete", "tackle": "won"}
RESTARTS = ("throw_in", "goal_kick", "corner", "free_kick", "kickoff")


def ball_actions(events: list[dict]) -> list[dict]:
    """The on-ball and defensive actions, in time order, that have a location."""
    return [e for e in events if e["type"] in ACTIONS and "_ax" in e]


def is_success(e: dict) -> bool:
    want = SUCCESS_OUTCOMES.get(e["type"])
    if want is not None:
        return e.get("outcome") == want
    if e["type"] == "shot":
        return e.get("outcome") in ("goal", "saved", "post")
    return True


def is_goal_shot(e: dict) -> bool:
    return e["type"] == "shot" and e.get("outcome") == "goal"


def to_frame_of_opponent(ax: float, ay: float) -> tuple[float, float]:
    """A point in one team's attack frame, expressed in the opposing team's frame."""
    return G.PITCH_L - ax, G.PITCH_W - ay


def end_point(e: dict) -> tuple[float, float]:
    """Where the action ended (attack frame of the acting team), or where it happened."""
    if "_eax" in e:
        return e["_eax"], e["_eay"]
    return e["_ax"], e["_ay"]


def logistic_fit(x: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 30) -> np.ndarray:
    """L2-regularised logistic regression by Newton's method. ``x`` must include a bias column."""
    w = np.zeros(x.shape[1])
    reg = l2 * np.eye(x.shape[1])
    reg[0, 0] = 0.0  # never shrink the bias
    for _ in range(iters):
        z = np.clip(x @ w, -30, 30)
        p = 1.0 / (1.0 + np.exp(-z))
        grad = x.T @ (p - y) + reg @ w
        s = p * (1.0 - p)
        hess = (x * s[:, None]).T @ x + reg + 1e-6 * np.eye(x.shape[1])
        step = np.linalg.solve(hess, grad)
        w -= step
        if float(np.abs(step).max()) < 1e-6:
            break
    return w


def logistic_predict(x: np.ndarray, w: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x @ w, -30, 30)))


def auc(y: np.ndarray, p: np.ndarray) -> float:
    """Area under the ROC curve by rank statistics (ties get the average rank)."""
    y = np.asarray(y).astype(bool)
    n1, n0 = int(y.sum()), int((~y).sum())
    if n1 == 0 or n0 == 0:
        return float("nan")
    order = np.argsort(p, kind="mergesort")
    ranks = np.empty(len(p))
    sp = p[order]
    i = 0
    r = np.empty(len(p))
    while i < len(p):
        j = i
        while j + 1 < len(p) and sp[j + 1] == sp[i]:
            j += 1
        r[i : j + 1] = (i + j) / 2.0 + 1.0
        i = j + 1
    ranks[order] = r
    return float((ranks[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))
