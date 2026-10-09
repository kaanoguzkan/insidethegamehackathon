"""Matches the MCP server and the Brain API can answer questions about.

A match is an :class:`Interpreter` holding the normalised events and state. Locally a match is
loaded by re-simulating a scenario (deterministic, about 5 s) and caching it; in the Azure
deployment the Brain registers the live interpreter instead. Tools never touch storage directly.
"""

from __future__ import annotations

import json
import re
import threading
from collections import OrderedDict
from pathlib import Path

from ..analytics import load_models
from ..analytics.season import context_for, load_season
from ..core.paths import league_dir, replays_dir, scenarios_dir
from ..intel.baselines import load_baselines
from ..intel.interpreter import Interpreter
from ..intel.pipeline import interpret_match
from ..intel.xt import XTGrid
from ..sim.engine import simulate
from ..sim.league import load_league
from ..sim.scenarios import load_scenario

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_CACHED = 4  # each cached match is a full interpreter (tens of MB); bound it so ids cannot exhaust memory


class UnknownMatch(KeyError):
    pass


class MatchRegistry:
    """Looks matches up by id. Ids are agent- or user-supplied, so they are never used to build a path
    unless they are a plain slug *and* one of the ids this registry actually lists."""

    def __init__(self, replay_root: Path | None = None, max_cached: int = MAX_CACHED) -> None:
        self.root = replay_root or replays_dir()
        self.max_cached = max_cached
        self._cache: OrderedDict[str, Interpreter] = OrderedDict()
        self._live: dict[str, Interpreter] = {}  # registered by the Brain; never evicted
        self._lock = threading.Lock()
        self._wanted: list[str] = []  # matches someone is about to need: the preload loads these first

    def _disk_ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if SAFE_ID.match(p.name) and (p / "meta.json").exists())

    def loaded(self) -> list[str]:
        """The matches whose interpreter is in memory, so a tool call on them is instant."""
        return sorted(set(self._live) | set(self._cache))

    def want(self, match_id: str) -> None:
        """Say that a match is about to be needed (the match center is open on it): the preload moves it to the front."""
        if SAFE_ID.match(match_id) and match_id in self.ids() and match_id not in self.loaded() and match_id not in self._wanted:
            self._wanted.insert(0, match_id)

    def next_to_load(self, skip: set[str] | frozenset[str] = frozenset()) -> str | None:
        """The next match for the preload: a wanted one first, then the rest in order. ``skip`` are ones that already failed."""
        done = set(self.loaded()) | set(skip)
        for match_id in [*self._wanted, *self.ids()]:
            if match_id not in done:
                return match_id
        return None

    def ids(self) -> list[str]:
        return sorted(set(self._live) | set(self._disk_ids()))

    def register(self, match_id: str, ip: Interpreter) -> None:
        """Called by the Brain with a live interpreter."""
        if not SAFE_ID.match(match_id):
            raise ValueError(f"invalid match id {match_id!r}")
        with self._lock:
            self._live[match_id] = ip

    def get(self, match_id: str) -> Interpreter:
        if not isinstance(match_id, str) or not SAFE_ID.match(match_id) or match_id not in self.ids():
            raise UnknownMatch(f"unknown match {match_id!r}; known: {', '.join(self.ids()) or 'none'}")
        # One lock: concurrent requests for the same match must not each spend seconds re-simulating it.
        with self._lock:
            if match_id in self._live:
                return self._live[match_id]
            if match_id in self._cache:
                self._cache.move_to_end(match_id)
                return self._cache[match_id]
            ip = self._load(match_id)
            self._cache[match_id] = ip
            while len(self._cache) > self.max_cached:
                self._cache.popitem(last=False)
            return ip

    def _load(self, match_id: str) -> Interpreter:
        meta = json.loads((self.root / match_id / "meta.json").read_text())
        scenario = meta.get("scenario")
        if scenario is not None and not SAFE_ID.match(str(scenario)):
            raise UnknownMatch(f"match {match_id!r} names an invalid scenario")
        clubs = load_league(league_dir() / "league.json")
        sc = load_scenario(scenarios_dir() / f"{scenario}.yaml") if scenario else None
        res = simulate(match_id, clubs[meta["home"]["id"]], clubs[meta["away"]["id"]], seed=meta["seed"], scenario=sc)
        ctx = context_for(load_season(), meta["home"]["id"], meta["away"]["id"])
        ip, _ = interpret_match(
            res, baselines=load_baselines(), xt=XTGrid.load(league_dir() / "xt_grid.json"), season=ctx, models=load_models()
        )
        return ip


async def preload(registry: MatchRegistry, delay_s: float = 10.0) -> list[str]:
    """Load every listed match in a worker thread, one after another, a little after start-up.

    The first tool call on a match re-simulates it (about 6 s on a laptop, 20 s on the container). Done here, in the
    background and off the event loop, that wait is gone by the time an agent asks. Returns the ids it loaded.
    """
    import asyncio

    await asyncio.sleep(delay_s)
    loaded: list[str] = []
    failed: set[str] = set()
    while (match_id := registry.next_to_load(failed)) is not None:  # re-asked each time: a match may become wanted meanwhile
        try:
            await asyncio.to_thread(registry.get, match_id)
            loaded.append(match_id)
        except Exception:  # noqa: BLE001 - a match that cannot load is reported by its first real call
            failed.add(match_id)
    return loaded
