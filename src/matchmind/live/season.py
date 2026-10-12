"""A season of the Lumen League: the fixtures, who has simulated which, and the table.

Six clubs play each other home and away: 30 fixtures in 10 rounds. **Round 1 is the three scripted stories** (Redmoor v Saltmarsh with the red card, Harbour v
Northbridge with the pressing collapse, Kestrel v Aldergate with the high-line gamble), so the first match anyone watches is a dramatic one; the other
27 fixtures are plain simulations.

Simulating a season is batch work for a Container Apps Job with several replicas. They do not need to be told which fixtures are theirs: each one *claims*
the next pending fixture (an atomic change of its status, guarded by the document's version in Cosmos DB), simulates it, stores the match pack and records
the result, until none is left. A replica that dies mid-fixture leaves a claim that expires, and the fixture is claimed again.

Documents (partition key ``seasonId``): ``{id: <seasonId>, kind: "season", ...}``, ``{id: "f07", kind: "fixture", ...}`` and a pointer
``{seasonId: "_", id: "current", value: <seasonId>}`` naming the season the site shows.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Protocol

CLUB_ORDER = ["RED", "HAR", "KES", "ALD", "NOR", "SAL"]  # the circle method over this list makes round 1 RED-SAL, HAR-NOR, KES-ALD
SCRIPTED = {("RED", "SAL"): "red-card-drama", ("HAR", "NOR"): "pressing-collapse", ("KES", "ALD"): "high-line-gamble"}
SCENARIO_SEEDS = {"red-card-drama": 102, "pressing-collapse": 104, "high-line-gamble": 85}  # the seeds that tell each story well (data/scenarios)
CLAIM_TTL_MS = 5 * 60_000  # a claim older than this was abandoned
POINTER = "_"


def now_ms() -> int:
    return int(time.time() * 1000)


def schedule(clubs: list[str] | None = None) -> list[tuple[int, str, str]]:
    """``(round, home, away)`` for the double round-robin, by the circle method; the second leg reverses the first."""
    ring = list(clubs or CLUB_ORDER)
    n = len(ring)
    first: list[tuple[int, str, str]] = []
    for r in range(n - 1):
        for i in range(n // 2):
            a, b = ring[i], ring[n - 1 - i]
            first.append((r + 1, a, b) if r == 0 or (r + i) % 2 == 0 else (r + 1, b, a))  # round 1 as listed: the three stories have their own home and away
        ring = [ring[0], ring[-1], *ring[1:-1]]
    second = [(r + n - 1, b, a) for r, a, b in first]
    return first + second


def plan(season_id: str, seed: int, *, featured: bool) -> tuple[dict, list[dict]]:
    """The season document and its fixtures, all pending. ``featured`` plays the three stories with the seeds that tell them well (the default season);
    otherwise every fixture, scripted ones included, gets a seed of its own so the results differ."""
    fixtures = []
    for i, (rnd, home, away) in enumerate(schedule(), start=1):
        scenario = SCRIPTED.get((home, away)) if rnd == 1 else None
        fixtures.append({
            "id": f"f{i:02d}", "seasonId": season_id, "kind": "fixture", "n": i, "round": rnd, "home": home, "away": away, "scenario": scenario,
            "seed": SCENARIO_SEEDS[scenario] if (scenario and featured) else seed * 1000 + i, "status": "pending", "score": None, "pack": None,
        })
    season = {"id": season_id, "seasonId": season_id, "kind": "season", "seed": seed, "featured": featured, "createdMs": now_ms(), "total": len(fixtures)}
    return season, fixtures


def standings(fixtures: list[dict], names: dict[str, str] | None = None) -> list[dict]:
    """The table from the fixtures that have been simulated: 3 points for a win, 1 for a draw; then goal difference, goals scored, name."""
    table: dict[str, dict[str, Any]] = {}

    def row(club: str) -> dict[str, Any]:
        return table.setdefault(club, {"club": club, "name": (names or {}).get(club, club), "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0, "gd": 0, "points": 0})

    for f in fixtures:
        row(f["home"])
        row(f["away"])
        if f.get("status") != "done" or not f.get("score"):
            continue
        hg, ag = f["score"].get(f["home"], 0), f["score"].get(f["away"], 0)
        for club, gf, ga in ((f["home"], hg, ag), (f["away"], ag, hg)):
            r = row(club)
            r["played"] += 1
            r["gf"] += gf
            r["ga"] += ga
            r["gd"] = r["gf"] - r["ga"]
            if gf > ga:
                r["won"] += 1
                r["points"] += 3
            elif gf == ga:
                r["drawn"] += 1
                r["points"] += 1
            else:
                r["lost"] += 1
    return sorted(table.values(), key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["name"]))


class SeasonStore(Protocol):
    def create(self, season: dict, fixtures: list[dict]) -> None: ...
    def get(self, season_id: str) -> dict | None: ...
    def fixtures(self, season_id: str) -> list[dict]: ...
    def claim(self, season_id: str, worker: str) -> dict | None: ...
    def finish(self, season_id: str, fixture_id: str, score: dict, pack: str) -> None: ...
    def fail(self, season_id: str, fixture_id: str, error: str) -> None: ...
    def current(self) -> str | None: ...
    def set_current(self, season_id: str) -> None: ...
    def list(self) -> list[dict]: ...


class MemorySeasonStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seasons: dict[str, dict] = {}
        self._fixtures: dict[str, dict[str, dict]] = {}
        self._current: str | None = None

    def create(self, season: dict, fixtures: list[dict]) -> None:
        with self._lock:
            self._seasons[season["id"]] = dict(season)
            self._fixtures[season["id"]] = {f["id"]: dict(f) for f in fixtures}

    def get(self, season_id: str) -> dict | None:
        with self._lock:
            s = self._seasons.get(season_id)
            return dict(s) if s else None

    def fixtures(self, season_id: str) -> list[dict]:
        with self._lock:
            return sorted((dict(f) for f in self._fixtures.get(season_id, {}).values()), key=lambda f: f["n"])

    def claim(self, season_id: str, worker: str) -> dict | None:
        with self._lock:
            for f in sorted(self._fixtures.get(season_id, {}).values(), key=lambda f: f["n"]):
                stale = f["status"] == "simulating" and now_ms() - (f.get("claimedMs") or 0) > CLAIM_TTL_MS
                if f["status"] == "pending" or stale:
                    f.update(status="simulating", claimedMs=now_ms(), worker=worker)
                    return dict(f)
            return None

    def finish(self, season_id: str, fixture_id: str, score: dict, pack: str) -> None:
        with self._lock:
            self._fixtures[season_id][fixture_id].update(status="done", score=score, pack=pack, doneMs=now_ms())

    def fail(self, season_id: str, fixture_id: str, error: str) -> None:
        with self._lock:
            self._fixtures[season_id][fixture_id].update(status="pending", error=error[:300])  # claimed again by whoever is next

    def current(self) -> str | None:
        with self._lock:
            return self._current

    def set_current(self, season_id: str) -> None:
        with self._lock:
            self._current = season_id

    def list(self) -> list[dict]:
        with self._lock:
            return sorted((dict(s) for s in self._seasons.values()), key=lambda s: -s["createdMs"])


class CosmosSeasonStore:
    """The same on Cosmos DB, container ``season`` (partition key ``/seasonId``), with the identity the service runs as."""

    def __init__(self, endpoint: str, database: str = "matchmind", credential: Any = None) -> None:
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential

        self._c = CosmosClient(endpoint, credential=credential or DefaultAzureCredential()).get_database_client(database).get_container_client("season")

    def _q(self, season_id: str | None, sql: str, params: list[dict] | None = None) -> list[dict]:
        kw: dict = {"query": sql, "parameters": params or []}
        if season_id is None:
            kw["enable_cross_partition_query"] = True
        else:
            kw["partition_key"] = season_id
        return list(self._c.query_items(**kw))

    def create(self, season: dict, fixtures: list[dict]) -> None:
        from concurrent.futures import ThreadPoolExecutor

        self._c.upsert_item(season)
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(self._c.upsert_item, fixtures))

    def get(self, season_id: str) -> dict | None:
        rows = self._q(season_id, "SELECT * FROM c WHERE c.kind = 'season'")
        return rows[0] if rows else None

    def fixtures(self, season_id: str) -> list[dict]:
        return sorted(self._q(season_id, "SELECT * FROM c WHERE c.kind = 'fixture'"), key=lambda f: f["n"])

    def claim(self, season_id: str, worker: str) -> dict | None:
        from azure.core import MatchConditions
        from azure.cosmos.exceptions import CosmosAccessConditionFailedError

        for f in self.fixtures(season_id):
            stale = f["status"] == "simulating" and now_ms() - (f.get("claimedMs") or 0) > CLAIM_TTL_MS
            if f["status"] != "pending" and not stale:
                continue
            taken = {**f, "status": "simulating", "claimedMs": now_ms(), "worker": worker}
            try:  # only one replica's replace succeeds: the others' etag no longer matches
                self._c.replace_item(item=f["id"], body=taken, etag=f["_etag"], match_condition=MatchConditions.IfNotModified)
                return taken
            except CosmosAccessConditionFailedError:
                continue
        return None

    def _update(self, season_id: str, fixture_id: str, **changes: Any) -> None:
        f = self._c.read_item(item=fixture_id, partition_key=season_id)
        self._c.replace_item(item=fixture_id, body={**f, **changes})

    def finish(self, season_id: str, fixture_id: str, score: dict, pack: str) -> None:
        self._update(season_id, fixture_id, status="done", score=score, pack=pack, doneMs=now_ms())

    def fail(self, season_id: str, fixture_id: str, error: str) -> None:
        self._update(season_id, fixture_id, status="pending", error=error[:300])

    def current(self) -> str | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return self._c.read_item(item="current", partition_key=POINTER)["value"]
        except CosmosResourceNotFoundError:
            return None

    def set_current(self, season_id: str) -> None:
        self._c.upsert_item({"id": "current", "seasonId": POINTER, "value": season_id})

    def list(self) -> list[dict]:
        rows = self._q(None, "SELECT * FROM c WHERE c.kind = 'season'")
        return sorted(rows, key=lambda s: -s["createdMs"])
