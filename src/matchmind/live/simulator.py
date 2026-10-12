"""The simulator job: play a scenario as a live feed.

    python -m matchmind.live.simulator --scenario red-card-drama --speed 5 --from-minute 40

Simulates the match (seconds), then releases its documents into the store at ``--speed`` times real time. With ``COSMOS_ENDPOINT`` set the store is
Cosmos DB (the Functions react to what is written there); without it everything stays in memory and the job just prints what it did, which is the
way to try it on a laptop.
"""

from __future__ import annotations

import argparse
import os
import time

from ..core.paths import league_dir, scenarios_dir
from ..sim.engine import simulate
from ..sim.league import load_league
from ..sim.scenarios import load_scenario
from .analysis import AnalyzerWorker
from .blobs import AzureBlobs, Blobs, MemoryBlobs
from .feed import build_chunks, build_feed, play, start_match
from .pipeline import InterpretWorker
from .store import CosmosLiveStore, LiveStore, MemoryLiveStore


def make_store() -> LiveStore:
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    return CosmosLiveStore(endpoint) if endpoint else MemoryLiveStore()


def make_blobs(container: str) -> Blobs:
    account = os.environ.get("STORAGE_ACCOUNT")
    return AzureBlobs(account, container) if account else MemoryBlobs()


def run(scenario_name: str, *, speed: float, from_minute: float, match_id: str | None = None, store: LiveStore | None = None) -> str:
    clubs = load_league(league_dir() / "league.json")
    sc = load_scenario(scenarios_dir() / f"{scenario_name}.yaml")
    match_id = match_id or f"live-{scenario_name}-{time.strftime('%d%H%M')}"
    store = store or make_store()
    print(f"simulating {scenario_name} (seed {sc.seed}) as {match_id}", flush=True)
    result = simulate(match_id, clubs[sc.home], clubs[sc.away], seed=sc.seed, scenario=sc)
    docs = build_feed(result, physical="chunks")  # events only; the physical facts come from the tracking chunks, through Event Grid and the analyzer Function
    chunks = build_chunks(result)
    frames = make_blobs("frames")
    start_match(store, match_id, result.meta, docs, scenario=scenario_name, speed=speed, from_ms=int(from_minute * 60_000), chunks=len(chunks))
    print(f"{len(docs)} events and {len(chunks)} tracking chunks over {chunks[-1][0] / 60000:.0f} match minutes; playing at {speed:g}x from minute {from_minute:g}", flush=True)
    on_tick = None
    if isinstance(store, MemoryLiveStore):  # no Azure: nothing will react to the writes, so run the workers here
        checkpoints = MemoryBlobs()
        analyzer, interpreter = AnalyzerWorker(store, frames, checkpoints), InterpretWorker(store, checkpoints)

        def on_tick() -> None:
            analyzer.drain(match_id)
            interpreter.run(match_id)

    n = play(store, match_id, docs, speed=speed, from_ms=int(from_minute * 60_000), chunks=chunks, blobs=frames, on_tick=on_tick)
    print(f"finished: {n} documents released", flush=True)
    return match_id


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="play a scenario as a live feed")
    p.add_argument("--scenario", default=os.environ.get("LIVE_SCENARIO", "red-card-drama"), help="a scenario in data/scenarios")
    p.add_argument("--speed", type=float, default=float(os.environ.get("LIVE_SPEED", "5")), help="match seconds per real second")
    p.add_argument("--from-minute", type=float, default=float(os.environ.get("LIVE_FROM_MINUTE", "0")), help="start this far into the match")
    p.add_argument("--match-id", default=os.environ.get("LIVE_MATCH_ID") or None)
    a = p.parse_args(argv)
    run(a.scenario, speed=a.speed, from_minute=a.from_minute, match_id=a.match_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
