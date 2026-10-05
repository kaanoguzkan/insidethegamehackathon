"""Reading and writing the fitted analytics models (``data/league/models.json``)."""

from __future__ import annotations

import json
from pathlib import Path

from ..core.paths import league_dir


def save_models(models: dict, path: Path | None = None) -> Path:
    path = path or league_dir() / "models.json"
    path.write_text(json.dumps(models, separators=(",", ":")) + "\n")
    return path


def load_models(path: Path | None = None) -> dict:
    path = path or league_dir() / "models.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}
