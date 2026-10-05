"""Possession value: what every action did to the chance of scoring or conceding.

This is the VAEP idea (valuing actions by estimating their effect on scoring and conceding
probabilities), the family that StatsBomb's OBV and Opta's possession value belong to. Two logistic
models read the state *after* an action (where it started and ended, what kind it was, whether it
worked, and the two actions before it) and predict whether the acting team scores, or concedes,
within its next ten actions. An action's value is the change in (P(score) - P(concede)) it caused,
seen from the acting team.

Fitted from simulated matches (``matchmind fit-models``); the weights live in
``data/league/models.json``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core import geometry as G
from .common import (
    ACTIONS,
    auc,
    ball_actions,
    end_point,
    is_goal_shot,
    is_success,
    logistic_fit,
    logistic_predict,
    to_frame_of_opponent,
)

HORIZON = 10  # actions
TYPE_INDEX = {t: i for i, t in enumerate(ACTIONS)}
N_TYPES = len(ACTIONS)


def _base(e: dict, flip: bool) -> list[float]:
    """Features of one action, with coordinates in the frame of the team being valued."""
    sx, sy = e["_ax"], e["_ay"]
    ex, ey = end_point(e)
    if flip:
        sx, sy = to_frame_of_opponent(sx, sy)
        ex, ey = to_frame_of_opponent(ex, ey)
    onehot = [0.0] * N_TYPES
    onehot[TYPE_INDEX[e["type"]]] = 1.0
    gd_s, gd_e = G.goal_dist(sx, sy), G.goal_dist(ex, ey)
    return [
        *onehot,
        1.0 if is_success(e) else 0.0,
        sx / G.PITCH_L, abs(sy - G.CY) / G.CY, ex / G.PITCH_L, abs(ey - G.CY) / G.CY,
        gd_s / G.PITCH_L, gd_e / G.PITCH_L, G.shot_angle(ex, ey),
        1.0 if G.in_box(ex, ey) else 0.0,
        float(np.hypot(ex - sx, ey - sy)) / 50.0, (ex - sx) / 50.0,
        float(e.get("_xg", 0.0)) if e["type"] == "shot" else 0.0,
        1.0 if e.get("attributes", {}).get("restart") else 0.0,
    ]


N_BASE = N_TYPES + 13


def featurize(actions: list[dict], clubs: list[str]) -> np.ndarray:
    """One row per action: itself and the two before it, all in the acting team's frame."""
    rows = []
    for i, e in enumerate(actions):
        row = [1.0, *_base(e, False)]
        for k in (1, 2):
            if i - k >= 0:
                prev = actions[i - k]
                same = prev["team"] == e["team"]
                row += [*_base(prev, not same), 1.0 if same else 0.0, min((e["_ms"] - prev["_ms"]) / 10000.0, 1.0)]
            else:
                row += [0.0] * (N_BASE + 2)
        rows.append(row)
    return np.array(rows, dtype=float)


def labels(actions: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    """Did the acting team score / concede within the next ``HORIZON`` actions (itself included)?"""
    n = len(actions)
    scores = np.zeros(n)
    concedes = np.zeros(n)
    goal_idx = [(j, a["team"]) for j, a in enumerate(actions) if is_goal_shot(a)]
    for i, a in enumerate(actions):
        for j, team in goal_idx:
            if i <= j < i + HORIZON:
                if team == a["team"]:
                    scores[i] = 1.0
                else:
                    concedes[i] = 1.0
    return scores, concedes


def build_dataset(matches: list[tuple[list[dict], dict]]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    xs, ys, yc = [], [], []
    for events, meta in matches:
        acts = ball_actions(events)
        if len(acts) < 20:
            continue
        clubs = [meta["home"]["id"], meta["away"]["id"]]
        xs.append(featurize(acts, clubs))
        s, c = labels(acts)
        ys.append(s)
        yc.append(c)
    return np.vstack(xs), np.concatenate(ys), np.concatenate(yc)


def fit(matches: list[tuple[list[dict], dict]], l2: float = 5.0) -> tuple[dict, dict]:
    x, ys, yc = build_dataset(matches)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    mean[0], std[0] = 0.0, 1.0
    std = np.where(std < 1e-9, 1.0, std)
    xn = (x - mean) / std
    xn[:, 0] = 1.0
    ws = logistic_fit(xn, ys, l2=l2)
    wc = logistic_fit(xn, yc, l2=l2)
    ps, pc = logistic_predict(xn, ws), logistic_predict(xn, wc)
    model = {
        "mean": np.round(mean, 6).tolist(), "std": np.round(std, 6).tolist(),
        "w_score": np.round(ws, 5).tolist(), "w_concede": np.round(wc, 5).tolist(), "horizon": HORIZON,
    }
    diag = {
        "rows": int(len(ys)), "score_rate": round(float(ys.mean()), 4), "concede_rate": round(float(yc.mean()), 4),
        "auc_score": round(auc(ys, ps), 4), "auc_concede": round(auc(yc, pc), 4),
    }
    return model, diag


@dataclass
class ActionValue:
    id: str
    player: str | None
    team: str
    type: str
    ms: int
    value: float
    p_score: float
    p_concede: float


class ActionValuer:
    def __init__(self, model: dict | None) -> None:
        self.model = model

    @property
    def ready(self) -> bool:
        return bool(self.model)

    def values(self, events: list[dict], clubs: list[str]) -> list[ActionValue]:
        if not self.model:
            return []
        acts = ball_actions(events)
        if not acts:
            return []
        m = self.model
        x = (featurize(acts, clubs) - np.array(m["mean"])) / np.array(m["std"])
        x[:, 0] = 1.0
        ps = logistic_predict(x, np.array(m["w_score"]))
        pc = logistic_predict(x, np.array(m["w_concede"]))
        out: list[ActionValue] = []
        prev_v, prev_team = 0.0, None
        for a, s, c in zip(acts, ps, pc, strict=True):
            v_now = float(s - c)
            if prev_team is None:
                before = 0.0
            else:
                before = prev_v if prev_team == a["team"] else -prev_v
            out.append(ActionValue(a["id"], a.get("player"), a["team"], a["type"], a["_ms"], round(v_now - before, 5), round(float(s), 5), round(float(c), 5)))
            prev_v, prev_team = v_now, a["team"]
        return out

    @staticmethod
    def player_totals(vals: list[ActionValue]) -> dict[str, dict]:
        tot: dict[str, dict] = {}
        for v in vals:
            if not v.player:
                continue
            t = tot.setdefault(v.player, {"value": 0.0, "n": 0, "attacking": 0.0, "defending": 0.0})
            t["value"] += v.value
            t["n"] += 1
            if v.type in ("tackle", "interception", "clearance", "ball_recovery", "block", "save", "claim"):
                t["defending"] += v.value
            else:
                t["attacking"] += v.value
        return {k: {kk: round(vv, 4) if isinstance(vv, float) else vv for kk, vv in t.items()} for k, t in tot.items()}
