"""Live win probability.

Goals arrive as a Poisson process, so the chance of each result from a given moment follows from
how many goals each side is still expected to score. A team's scoring rate starts from the league
average (scaled by its pre-match strength) and is updated by what the match shows: expected goals so
far, blended with the prior as if it were ``prior_minutes`` of evidence. A red card cuts the
ten-man side's rate and lifts the other's.

The league goal rate and the match length are *fitted* from simulated matches (``matchmind
fit-models``); the red-card multipliers are priors (a sent-off side concedes roughly a fifth more and
scores a fifth less), because a simulated league has too few sendings-off to estimate them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULTS = {
    "goal_rate": 0.0128,  # goals per team per minute, league average (fitted)
    "match_minutes": 95.5,  # 90 plus the usual stoppage
    "prior_minutes": 30.0,  # weight of the prior against the match's own xG, in minutes
    "red_own": 0.78,
    "red_opp": 1.22,
    "max_goals": 12,
}


def _pmf(mu: float, n: int) -> list[float]:
    p = [math.exp(-mu)]
    for k in range(1, n + 1):
        p.append(p[-1] * mu / k)
    return p


def outcome_probabilities(diff: int, mu_home: float, mu_away: float, max_goals: int = 12) -> dict[str, float]:
    """P(home win / draw / away win) given the current goal difference and remaining expected goals."""
    ph, pa = _pmf(mu_home, max_goals), _pmf(mu_away, max_goals)
    win = draw = lose = 0.0
    for i, a in enumerate(ph):
        for j, b in enumerate(pa):
            net = diff + i - j
            w = a * b
            if net > 0:
                win += w
            elif net == 0:
                draw += w
            else:
                lose += w
    tot = win + draw + lose
    return {"home": win / tot, "draw": draw / tot, "away": lose / tot}


@dataclass
class WinProbModel:
    params: dict

    @classmethod
    def default(cls) -> WinProbModel:
        return cls(dict(DEFAULTS))

    @classmethod
    def from_dict(cls, d: dict | None) -> WinProbModel:
        return cls({**DEFAULTS, **(d or {})})

    def state_probabilities(
        self, minute: float, score: tuple[int, int], xg: tuple[float, float], reds: tuple[int, int],
        strength: tuple[float, float] = (1.0, 1.0),
    ) -> dict[str, float]:
        p = self.params
        elapsed = max(minute, 0.0)
        remaining = max(p["match_minutes"] - elapsed, 0.4)
        rates = []
        for i in (0, 1):
            prior = p["goal_rate"] * strength[i]
            rate = (prior * p["prior_minutes"] + xg[i]) / (p["prior_minutes"] + elapsed)
            rate *= (p["red_own"] ** reds[i]) * (p["red_opp"] ** reds[1 - i])
            rates.append(rate)
        return outcome_probabilities(score[0] - score[1], rates[0] * remaining, rates[1] * remaining, int(p["max_goals"]))

    @staticmethod
    def timeline(events: list[dict]) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, float]]]:
        """Goals and red cards as ``(ms, kind, club)`` and open-play and set-piece shots as ``(ms, club, xG)`` (penalties excluded)."""
        marks: list[tuple[int, str, str]] = []
        shots: list[tuple[int, str, float]] = []
        for e in events:
            if e["type"] == "goal":
                marks.append((e["_ms"], "goal", e["team"]))
            elif e["type"] == "card" and e.get("outcome") == "red":
                marks.append((e["_ms"], "red", e["team"]))
            elif e["type"] == "shot" and (e.get("attributes") or {}).get("situation") != "penalty":
                # A penalty already moves the odds as a goal; counting its xG as well would make the
                # scoring side look more dominant than it was in open play.
                shots.append((e["_ms"], e["team"], float(e.get("_xg", 0.0))))
        return marks, shots

    def at(self, marks: list, shots: list, clubs: list[str], ms: int, inclusive: bool = True,
           strength: tuple[float, float] = (1.0, 1.0)) -> dict[str, float]:
        """Win probabilities at ``ms`` (events at exactly ``ms`` count only if ``inclusive``)."""
        score, reds, xg = [0, 0], [0, 0], [0.0, 0.0]
        for t, kind, club in marks:
            if t < ms or (inclusive and t == ms):
                i = clubs.index(club)
                if kind == "goal":
                    score[i] += 1
                else:
                    reds[i] += 1
        for t, club, v in shots:
            if t <= ms:
                xg[clubs.index(club)] += v
        return self.state_probabilities(ms / 60000.0, (score[0], score[1]), (xg[0], xg[1]), (reds[0], reds[1]), strength)

    def series(self, events: list[dict], clubs: list[str], end_ms: int, strength: tuple[float, float] = (1.0, 1.0),
               step_ms: int = 60_000) -> list[dict]:
        """Win probability every ``step_ms`` and just before and after every goal and red card."""
        marks, shots = self.timeline(events)
        points: list[tuple[int, str]] = [(ms, "tick") for ms in range(0, end_ms + 1, step_ms)]
        for t, kind, _ in marks:
            points += [(max(t - 1, 0), f"before_{kind}"), (t, f"after_{kind}")]
        points.sort(key=lambda p: (p[0], 0 if p[1].startswith("before") else 1))
        out = []
        for ms, tag in points:
            probs = self.at(marks, shots, clubs, ms, inclusive=not tag.startswith("before"), strength=strength)
            score = [0, 0]
            for t, kind, club in marks:
                if kind == "goal" and (t < ms or (not tag.startswith("before") and t == ms)):
                    score[clubs.index(club)] += 1
            out.append({"matchMs": ms, "tag": tag, "score": score, "p": {k: round(v, 4) for k, v in probs.items()}})
        return out

    @staticmethod
    def swings(series: list[dict]) -> list[dict]:
        """How much each goal or red card moved the odds (largest change of any outcome)."""
        out = []
        for i, pt in enumerate(series):
            if not pt["tag"].startswith("after_") or i == 0:
                continue
            prev = series[i - 1]
            delta = {k: pt["p"][k] - prev["p"][k] for k in ("home", "draw", "away")}
            out.append({
                "matchMs": pt["matchMs"], "kind": pt["tag"][6:], "before": prev["p"], "after": pt["p"],
                "swing": round(max(abs(v) for v in delta.values()), 4),
            })
        return out
