"""Where committed data (league, baselines, scenarios, replays) lives.

Defaults to the repository's ``data/`` directory; set ``MATCHMIND_DATA`` to relocate it (the
container images copy it to ``/app/data``).
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    env = os.environ.get("MATCHMIND_DATA")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "data"


def league_dir() -> Path:
    return data_dir() / "league"


def scenarios_dir() -> Path:
    return data_dir() / "scenarios"


def replays_dir() -> Path:
    return data_dir() / "replays"
