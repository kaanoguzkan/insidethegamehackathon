"""The managers: each side reacts to the match, so tactical stories happen by themselves.

Nothing here is scripted. Every manager has a temperament drawn once from a stream of its own (how
readily it acts, and when it starts to chase or protect a result) and then reviews the match every
twenty seconds, using only what a touchline sees: the score, the clock, the numbers on the pitch and
how tired the team looks. The reactions are the ones a coach makes:

* a side with a man down drops into a more compact shape and eases off its press;
* the side with the extra man pushes up, presses and stretches the pitch;
* a side that is losing late throws the line up, presses harder, goes more direct and adds a forward;
* a side that is winning late drops deeper, presses less and breaks on the counter;
* a side whose legs have gone stops pressing high.

The manager stream is separate from the one the match is played with, so a match is identical to
what it would have been without managers until the first reaction. The pipeline is never told about
any of it; it has to *detect* the consequences from events and tracking and explain them.
"""

from __future__ import annotations

import random

import numpy as np

from .tactics import FORMATIONS_FULL

REVIEW_EVERY = 20.0  # seconds of match time between a manager's looks at the game
COOLDOWN = 480.0  # seconds before a manager makes another change of his own accord
MAX_CHANGES = 3  # reactions per manager per match
LAST_CALL = 86.0  # minute after which a manager no longer makes a change
TIRED_FROM = 55.0  # minute from which a manager looks at his players' legs
STYLE_FIELDS = (
    "press_intensity", "press_height", "directness", "tempo", "width", "line_height", "counter_bias"
)  # fmt: skip

# Style deltas for each reaction. They are relative and clamped to 0..1 like any other style change.
COMPACT = {"press_intensity": -0.15, "press_height": -0.20, "line_height": -0.15, "tempo": -0.05, "counter_bias": 0.10}
EXTRA_MAN = {"press_intensity": 0.20, "press_height": 0.15, "line_height": 0.15, "width": 0.05, "tempo": 0.05}
CHASE = {"press_intensity": 0.20, "press_height": 0.20, "line_height": 0.25, "directness": 0.12, "tempo": 0.08}
PROTECT = {"press_intensity": -0.05, "press_height": -0.15, "line_height": -0.15, "tempo": -0.05, "counter_bias": 0.15}
TIRED = {"press_intensity": -0.35, "press_height": -0.25, "line_height": -0.15}


def attacking_weight(name: str) -> float:
    """How far up the pitch a formation puts its ten outfield players, summed (bigger is more attacking)."""
    return sum(d for _, d, _ in FORMATIONS_FULL[name]["base"][1:])


class ManagerMixin:
    """Per-team managers that adjust style and shape during the match (see the module docstring)."""

    def _init_managers(self) -> None:
        self.mrng = random.Random(self.seed * 1_000_003 + 17)
        self.manager_log: list[dict] = []
        self.mgr = [
            {
                "reactivity": self.mrng.uniform(0.55, 1.0),  # the chance he acts when a trigger comes
                "chase_from": self.mrng.uniform(58.0, 74.0),  # the minute from which he will chase a deficit
                "protect_from": self.mrng.uniform(66.0, 80.0),  # the minute from which he will protect a lead
                "tired_below": self.mrng.uniform(0.62, 0.72),  # how drained the four most tired outfield players must be before he eases the press
                "next": 90.0, "last": -1e9, "changes": 0,
                "men": 11, "opp_men": 11, "alert": None, "alert_t": 0.0, "alert_delay": 0.0,
                "chase_done": False, "protect_done": False, "tired_done": False,
            }
            for _ in range(2)
        ]

    def _display_minute(self) -> float:
        return self.t / 60.0 if self.period == 1 else 45.0 + (self.t - self.p1_len) / 60.0

    def _manager_review(self) -> None:
        if self.t < 90.0:
            return
        minute = self._display_minute()
        if minute > LAST_CALL:
            return
        for team in (0, 1):
            mg = self.mgr[team]
            if self.t < mg["next"]:
                continue
            mg["next"] = self.t + REVIEW_EVERY
            opp = 1 - team
            men = int(self.active[team * 11 : team * 11 + 11].sum())
            opp_men = int(self.active[opp * 11 : opp * 11 + 11].sum())
            if men < mg["men"] or opp_men < mg["opp_men"]:  # a dismissal: he reacts after a minute or two of thinking
                mg["alert"] = "down" if men < mg["men"] else "up"
                mg["alert_t"], mg["alert_delay"] = self.t, self.mrng.uniform(40.0, 150.0)
            mg["men"], mg["opp_men"] = men, opp_men
            if mg["changes"] >= MAX_CHANGES:
                continue
            lead = self.score[team] - self.score[opp]

            if mg["alert"] and self.t - mg["alert_t"] >= mg["alert_delay"]:
                kind, mg["alert"] = mg["alert"], None
                if kind == "down":
                    self._manager_act(team, "man down", COMPACT, self._shape_towards(team, -1, 0.9))
                elif self.mrng.random() < mg["reactivity"]:
                    self._manager_act(team, "extra man", EXTRA_MAN, self._shape_towards(team, +1, 0.5))
                continue
            if self.t - mg["last"] < COOLDOWN:
                continue

            if not mg["chase_done"] and minute >= mg["chase_from"] and lead < 0:
                mg["chase_done"] = True
                if self.mrng.random() < mg["reactivity"]:
                    self._manager_act(team, "chasing the game", CHASE, self._shape_towards(team, +1, 0.8))
                    continue
            if not mg["protect_done"] and minute >= mg["protect_from"] and lead > 0:
                mg["protect_done"] = True
                if self.mrng.random() < mg["reactivity"]:
                    self._manager_act(team, "protecting the lead", PROTECT, self._shape_towards(team, -1, 0.7))
                    continue
            if not mg["tired_done"] and minute >= TIRED_FROM and self._legs_gone(team):
                mg["tired_done"] = True
                self._manager_act(team, "tired legs", TIRED, None)

    def _legs_gone(self, team: int) -> bool:
        """The side presses hard and its most tired outfield players are running on empty."""
        sl = slice(team * 11 + 1, team * 11 + 11)
        act = self.active[sl]
        if self.style[team].press_intensity < 0.5 or act.sum() < 6:
            return False
        return float(np.sort(self.stamina[sl][act])[:4].mean()) < self.mgr[team]["tired_below"]

    def _shape_towards(self, team: int, direction: int, chance: float) -> str | None:
        """A formation one step more attacking (+1) or more defensive (-1) than the current one, or None to keep it."""
        if self.mrng.random() >= chance:
            return None
        cur = self.formation_name[team]
        w = attacking_weight(cur)
        cands = sorted(
            (abs(attacking_weight(n) - w), n) for n in FORMATIONS_FULL
            if n != cur and (attacking_weight(n) - w) * direction > 0.25
        )  # fmt: skip
        if not cands:
            return None
        return self.mrng.choice([n for _, n in cands[:2]])

    def _manager_act(self, team: int, reason: str, deltas: dict[str, float], formation: str | None) -> None:
        st = self.style[team]
        before = {k: round(getattr(st, k), 2) for k in STYLE_FIELDS}
        for k, dv in deltas.items():
            setattr(st, k, float(np.clip(getattr(st, k) + dv, 0.0, 1.0)))
        if formation and formation != self.formation_name[team]:
            self._change_formation(team, formation)
        mg = self.mgr[team]
        mg["last"], mg["changes"] = self.t, mg["changes"] + 1
        self.manager_log.append({
            "ms": int(round(self.t * 1000)), "minute": round(self._display_minute(), 1), "team": self.club_id[team], "reason": reason,
            "before": before, "after": {k: round(getattr(st, k), 2) for k in STYLE_FIELDS}, "formation": self.formation_name[team],
        })  # fmt: skip
