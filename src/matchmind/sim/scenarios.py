"""Scripted match scenarios.

A scenario fixes the fixture and the seed and scripts changes during the match (a team
easing off its press, a substitution, a red card). The pipeline is never told about the
script; it has to *detect* the consequences from events and tracking and explain them.
That is what makes the demo both reliable and honest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class ScriptItem:
    at: str  # display clock "MM:SS", e.g. "55:00" (second half minutes continue from 45)
    team: str  # club id
    change: dict[str, float] = field(default_factory=dict)  # relative style deltas
    set: dict[str, float] = field(default_factory=dict)  # absolute style values
    event: str | None = None  # "substitution" | "red_card"
    player: str | None = None  # for red_card: player id (default: a defender)

    @property
    def at_seconds(self) -> float:
        m, _, s = self.at.partition(":")
        return int(m) * 60 + (int(s) if s else 0)


@dataclass
class Scenario:
    id: str
    home: str
    away: str
    seed: int = 1
    description: str = ""
    script: list[ScriptItem] = field(default_factory=list)


STYLE_FIELDS = (
    "press_intensity", "press_height", "directness", "tempo", "width", "line_height", "counter_bias"
)  # fmt: skip


def parse_scenario(d: dict) -> Scenario:
    script = [ScriptItem(**item) for item in d.get("script", [])]
    for it in script:
        for k in (*it.change, *it.set):
            if k not in STYLE_FIELDS:
                raise ValueError(f"scenario {d.get('id')!r}: unknown style field {k!r}")
        if it.event not in (None, "substitution", "red_card"):
            raise ValueError(f"scenario {d.get('id')!r}: unknown event {it.event!r}")
    return Scenario(
        id=d["id"],
        home=d["home"],
        away=d["away"],
        seed=int(d.get("seed", 1)),
        description=d.get("description", ""),
        script=script,
    )


def load_scenario(path: Path) -> Scenario:
    return parse_scenario(yaml.safe_load(path.read_text()))
