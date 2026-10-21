"""Simulate a season: the command the season Container Apps Job runs (several replicas at once), and the same on a laptop.

    python -m matchmind.live.season_job --season season-2 --create --seed 2 --workers 8     # plan it and simulate it with 8 local processes
    SEASON_ID=season-2 python -m matchmind.live.season_job                                    # what a job replica does: claim fixtures until none is left

Every fixture is simulated once and stored as a match pack (``packs.py``) in Blob Storage; its result goes to the season store. With ``COSMOS_ENDPOINT`` and
``STORAGE_ACCOUNT`` set those are Cosmos DB and Blob Storage; without them everything stays in this process (fine for a single worker).
"""

from __future__ import annotations

import argparse
import os
import socket
import time
from collections.abc import Callable
from multiprocessing import Process

from ..core.paths import league_dir
from ..sim.engine import simulate
from ..sim.league import load_league
from .blobs import Blobs, MemoryBlobs
from .packs import write_pack
from .season import CosmosSeasonStore, MemorySeasonStore, SeasonStore, plan
from .simulator import make_blobs


def make_season_store() -> SeasonStore:
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    return CosmosSeasonStore(endpoint) if endpoint else MemorySeasonStore()


def simulate_fixture(fx: dict, clubs: dict, packs: Blobs) -> dict:
    """Simulate one fixture and store its pack. Returns the score by club id."""
    match_id = f"{fx['seasonId']}-{fx['id']}"
    result = simulate(match_id, clubs[fx["home"]], clubs[fx["away"]], seed=fx["seed"])
    write_pack(packs, f"{fx['seasonId']}/{fx['id']}", result)
    return {k: int(v) for k, v in result.meta["score"].items()}


def run_worker(
    season_id: str, store: SeasonStore, packs: Blobs, worker: str | None = None, *, simulate_one: Callable[[dict, dict, Blobs], dict] = simulate_fixture,
    clubs: dict | None = None,
) -> int:
    """Claim, simulate and record fixtures until none is pending. Returns how many this worker did."""
    worker = worker or f"{socket.gethostname()}-{os.getpid()}"
    clubs = clubs or load_league(league_dir() / "league.json")
    done = 0
    while (fx := store.claim(season_id, worker)) is not None:
        t0 = time.monotonic()
        try:
            score = simulate_one(fx, clubs, packs)
        except Exception as e:  # noqa: BLE001 - one bad fixture must not take the replica down; it goes back to pending
            store.fail(season_id, fx["id"], f"{type(e).__name__}: {e}")
            print(f"{worker}: {fx['id']} failed: {e}", flush=True)
            continue
        store.finish(season_id, fx["id"], score, f"{season_id}/{fx['id']}")
        done += 1
        print(f"{worker}: {fx['id']} {fx['home']} {score.get(fx['home'])}-{score.get(fx['away'])} {fx['away']} in {time.monotonic() - t0:.0f} s", flush=True)
    return done


def create_season(store: SeasonStore, season_id: str, seed: int, *, featured: bool) -> None:
    season, fixtures = plan(season_id, seed, featured=featured)
    store.create(season, fixtures)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="simulate a season")
    p.add_argument("--season", default=os.environ.get("SEASON_ID"), help="the season id")
    p.add_argument("--create", action="store_true", help="plan the season first (fixtures all pending)")
    p.add_argument("--seed", type=int, default=int(os.environ.get("SEASON_SEED", "1")))
    p.add_argument("--featured", action="store_true", help="the three stories use the seeds that tell them well (the default season)")
    p.add_argument("--workers", type=int, default=1, help="local processes (each claims fixtures; needs Cosmos DB and Blob Storage to share the work)")
    p.add_argument("--make-current", action="store_true", help="make this the season the site shows once it is planned")
    a = p.parse_args(argv)
    if not a.season:
        p.error("--season or SEASON_ID is required")
    store, packs = make_season_store(), make_blobs("packs")
    if a.create:
        create_season(store, a.season, a.seed, featured=a.featured)
        print(f"planned {a.season}: 30 fixtures", flush=True)
    if a.make_current:
        store.set_current(a.season)
    t0 = time.monotonic()
    if a.workers > 1:
        if isinstance(store, MemorySeasonStore) or isinstance(packs, MemoryBlobs):
            p.error("several workers need COSMOS_ENDPOINT and STORAGE_ACCOUNT: in-memory stores are not shared between processes")
        procs = [Process(target=run_worker, args=(a.season, make_season_store(), make_blobs("packs"), f"local-{i}")) for i in range(a.workers)]
        for pr in procs:
            pr.start()
        for pr in procs:
            pr.join()
    else:
        run_worker(a.season, store, packs)
    fixtures = store.fixtures(a.season)
    pending = sum(1 for f in fixtures if f["status"] == "pending")  # unclaimed: nobody is going to do them (one still being simulated is another replica's)
    print(f"{a.season}: this worker is done after {time.monotonic() - t0:.0f} s; {sum(1 for f in fixtures if f['status'] == 'done')} of {len(fixtures)} fixtures are done, {pending} still pending", flush=True)
    return 0 if pending == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
