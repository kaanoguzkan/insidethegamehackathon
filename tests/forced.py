"""A match in which the managers do exactly what a test says, and nothing else.

The engine's managers decide for themselves (``sim/manager.py``). A test of the interpreter needs the opposite: a
change it knows happened, at a minute it knows, with a control of the same match where nothing did. ``Forced``
switches the managers off and applies the given changes, which the pipeline is never told about.
"""

from __future__ import annotations

from matchmind.sim.engine import MatchSim

PRESS_OFF = {"press_intensity": -0.80, "press_height": -0.70, "line_height": -0.40}  # a side that stops pressing
LINE_UP = {"line_height": 0.7, "press_height": 0.5, "press_intensity": 0.3}  # a side that throws its line up the pitch


class Forced(MatchSim):
    """``changes``: ``(display minute, club index 0|1, style deltas, formation or None)``."""

    def __init__(self, *args, changes=(), **kw) -> None:
        super().__init__(*args, **kw)
        self.forced = sorted(((self._display_to_t(m * 60.0), team, deltas, formation) for m, team, deltas, formation in changes), key=lambda c: c[0])

    def _manager_review(self) -> None:
        while self.forced and self.forced[0][0] <= self.t:
            _, team, deltas, formation = self.forced.pop(0)
            self._manager_act(team, "forced", deltas, formation)
