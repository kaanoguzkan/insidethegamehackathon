"""The demo matches: a fixture and a seed each, nothing more.

``data/demos.json`` lists the matches that ship as replay packages. A demo is not scripted: the engine plays the
fixture from the seed, its managers react to the score and the clock, and the seed was chosen because the match
that came out of it is worth watching (see ``matchmind pick-demos``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .core.paths import demos_path


@dataclass(frozen=True)
class Demo:
    id: str
    home: str
    away: str
    seed: int


def load_demos() -> dict[str, Demo]:
    path = demos_path()
    if not path.exists():
        return {}
    return {d["id"]: Demo(d["id"], d["home"], d["away"], int(d["seed"])) for d in json.loads(path.read_text())}


def get_demo(demo_id: str) -> Demo:
    demos = load_demos()
    if demo_id not in demos:
        raise KeyError(f"no demo {demo_id!r}; the committed demos are {', '.join(sorted(demos)) or 'none'}")
    return demos[demo_id]
