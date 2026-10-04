"""Matches the MCP server and the Brain API can answer questions about.

A match is an :class:`Interpreter` holding the normalised events and state. Locally a match is
loaded by re-simulating a scenario (deterministic, about 5 s) and caching it; in the Azure
deployment the Brain registers the live interpreter instead. Tools never touch storage directly.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.paths import league_dir, replays_dir, scenarios_dir
from ..intel.baselines import load_baselines
from ..intel.interpreter import Interpreter
from ..intel.pipeline import interpret_match
from ..intel.xt import XTGrid
from ..sim.engine import simulate
from ..sim.league import load_league
from ..sim.scenarios import load_scenario


class UnknownMatch(KeyError):
    pass


class MatchRegistry:
    def __init__(self, replay_root: Path | None = None) -> None:
        self.root = replay_root or replays_dir()
        self._cache: dict[str, Interpreter] = {}

    def ids(self) -> list[str]:
        live = list(self._cache)
        disk = sorted(p.name for p in self.root.iterdir() if (p / "meta.json").exists()) if self.root.exists() else []
        return sorted(set(live) | set(disk))

    def register(self, match_id: str, ip: Interpreter) -> None:
        """Called by the Brain with a live interpreter."""
        self._cache[match_id] = ip

    def get(self, match_id: str) -> Interpreter:
        if match_id in self._cache:
            return self._cache[match_id]
        meta_path = self.root / match_id / "meta.json"
        if not meta_path.exists():
            raise UnknownMatch(f"unknown match {match_id!r}; known: {', '.join(self.ids()) or 'none'}")
        meta = json.loads(meta_path.read_text())
        scenario = meta.get("scenario")
        clubs = load_league(league_dir() / "league.json")
        sc = load_scenario(scenarios_dir() / f"{scenario}.yaml") if scenario else None
        res = simulate(
            match_id, clubs[meta["home"]["id"]], clubs[meta["away"]["id"]], seed=meta["seed"], scenario=sc,
        )
        ip, _ = interpret_match(res, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"))
        self._cache[match_id] = ip
        return ip
