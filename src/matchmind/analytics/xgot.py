"""Post-shot xG and goalkeeper value.

xG says how good a chance was before the shot. Post-shot xG (xGOT, Opta's name; PSxG at StatsBomb)
says how likely an *on-target* shot was to beat the keeper, from where in the goal mouth it went. The
gap between the xGOT a keeper faced and the goals he conceded is the usual measure of shot-stopping.
"""

from __future__ import annotations

import numpy as np

from ..core import geometry as G
from .common import auc, logistic_fit, logistic_predict


def _row(xg_v: float, y_off: float, z: float) -> list[float]:
    half = G.GOAL_W / 2.0
    side = min(abs(y_off) / half, 1.0)
    height = min(max(z, 0.0), 2.44) / 2.44
    return [1.0, side, side * side, height, abs(height - 0.35), xg_v]


def on_target(e: dict) -> bool:
    return e["type"] == "shot" and e.get("outcome") in ("goal", "saved") and e.get("attributes", {}).get("goalMouthY") is not None


def shot_features(e: dict) -> list[float]:
    a = e["attributes"]
    return _row(float(e.get("_xg", 0.1)), float(a["goalMouthY"]), float(a.get("goalMouthZ") or 0.8))


def fit(matches: list[tuple[list[dict], dict]]) -> tuple[dict, dict]:
    rows, ys = [], []
    for events, _ in matches:
        for e in events:
            if on_target(e) and not e["attributes"].get("penalty"):
                rows.append(shot_features(e))
                ys.append(1.0 if e["outcome"] == "goal" else 0.0)
    x, y = np.array(rows), np.array(ys)
    w = logistic_fit(x, y, l2=1.0)
    p = logistic_predict(x, w)
    return {"w": np.round(w, 5).tolist()}, {"rows": int(len(y)), "goal_rate": round(float(y.mean()), 4), "auc": round(auc(y, p), 4)}


class XGOT:
    def __init__(self, model: dict | None) -> None:
        self.w = np.array(model["w"]) if model else None

    @property
    def ready(self) -> bool:
        return self.w is not None

    def value(self, e: dict) -> float | None:
        """xGOT of one shot: 0 if off target or blocked, the model's probability otherwise."""
        if e["type"] != "shot":
            return None
        if not on_target(e):
            return 0.0
        if e["attributes"].get("penalty"):
            return 0.78
        if self.w is None:
            return float(e.get("_xg", 0.1))
        return float(logistic_predict(np.array([shot_features(e)]), self.w)[0])
