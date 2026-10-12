"""Where a live match lives: the feed documents, the moments found in them and the overlays written for them.

One interface, two implementations. :class:`MemoryLiveStore` serves the tests and a local run; :class:`CosmosLiveStore` is what the Azure
services share (the simulator job writes, the Functions read and write, the Brain reads). Every method is synchronous and idempotent, so a
change-feed trigger that delivers a batch twice, or a job that is restarted, cannot duplicate anything.

Documents (partition key ``matchId`` everywhere):

* ``matches``  one per match: ``{id, matchId, meta, status, speed, fromMs, wallStartMs, scenario}``; ``status`` is scheduled, live or finished.
* ``events``   the feed, in arrival order: ``{id: "0000042", matchId, n, kind, arrivalMs, doc}`` where ``kind`` is event, physical,
               enrichment or final (the end-of-feed marker).
* ``moments``  ``{id, matchId, moment}``: the evidence pack the agents write from.
* ``overlays`` ``{id, matchId, emittedMs, overlay}``: what viewers see; ``emittedMs`` (wall clock) is the cursor pollers read from.
* ``state``    small bookkeeping documents (``{id: "kept_at", matchId, value}``).
"""

from __future__ import annotations

import threading
import time
from typing import Any, Protocol

FINAL = "final"


class LiveStore(Protocol):
    def put_match(self, match_id: str, info: dict) -> None: ...
    def get_match(self, match_id: str) -> dict | None: ...
    def list_matches(self) -> list[dict]: ...
    def add_docs(self, match_id: str, docs: list[dict]) -> None: ...
    def docs(self, match_id: str) -> list[dict]: ...
    def docs_between(self, match_id: str, after_ms: int, upto_ms: int) -> list[dict]: ...
    def docs_after(self, match_id: str, n: int, limit: int = 200) -> list[dict]: ...
    def add_moments(self, match_id: str, moments: list[dict]) -> list[str]: ...
    def moments(self, match_id: str) -> list[dict]: ...
    def add_overlays(self, match_id: str, overlays: list[dict], emitted_ms: int | None = None) -> list[str]: ...
    def overlays_since(self, match_id: str, since_ms: int) -> list[dict]: ...
    def get_state(self, match_id: str, key: str, default: Any = None) -> Any: ...
    def acquire(self, match_id: str, name: str, ttl_ms: int) -> bool: ...
    def release(self, match_id: str, name: str) -> None: ...
    def put_state(self, match_id: str, key: str, value: Any) -> None: ...


def now_ms() -> int:
    return int(time.time() * 1000)


def sort_key(d: dict) -> tuple:
    """The order documents reach the interpreter in: arrival time, then events before the analyzer's events before the enrichments, then sequence."""
    return (d["arrivalMs"], d.get("order", 0), d.get("seq") or 0, d.get("n") if d.get("n") is not None else 0)


def doc_key(n: int) -> str:
    return f"{n:07d}"


class MemoryLiveStore:
    """Everything in dictionaries, behind one lock."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._matches: dict[str, dict] = {}
        self._docs: dict[str, dict[str, dict]] = {}
        self._moments: dict[str, dict[str, dict]] = {}
        self._overlays: dict[str, dict[str, dict]] = {}
        self._state: dict[tuple[str, str], Any] = {}
        self._locks: dict[tuple[str, str], int] = {}

    def put_match(self, match_id: str, info: dict) -> None:
        with self._lock:
            self._matches[match_id] = {**info, "id": match_id, "matchId": match_id}

    def get_match(self, match_id: str) -> dict | None:
        with self._lock:
            m = self._matches.get(match_id)
            return dict(m) if m else None

    def list_matches(self) -> list[dict]:
        with self._lock:
            return [dict(m) for m in self._matches.values()]

    def add_docs(self, match_id: str, docs: list[dict]) -> None:
        with self._lock:
            bucket = self._docs.setdefault(match_id, {})
            for d in docs:
                bucket.setdefault(d["id"], {**d, "matchId": match_id})

    def docs(self, match_id: str) -> list[dict]:
        with self._lock:
            return sorted(self._docs.get(match_id, {}).values(), key=sort_key)

    def docs_between(self, match_id: str, after_ms: int, upto_ms: int) -> list[dict]:
        """The documents that arrived in ``(after_ms, upto_ms]``, in arrival order. This is how the interpreter reads: only what it has not seen."""
        return [d for d in self.docs(match_id) if after_ms < d["arrivalMs"] <= upto_ms]

    def docs_after(self, match_id: str, n: int, limit: int = 200) -> list[dict]:
        """The feed documents with a sequence number above ``n`` (what a poller has not seen), oldest first."""
        return [d for d in self.docs(match_id) if d.get("n") is not None and d["n"] > n][:limit]

    def add_moments(self, match_id: str, moments: list[dict]) -> list[str]:
        """Store the moments that are new; returns their ids (what the dispatcher has to write overlays for)."""
        new = []
        with self._lock:
            bucket = self._moments.setdefault(match_id, {})
            for m in moments:
                if m["id"] not in bucket:
                    bucket[m["id"]] = {"id": m["id"], "matchId": match_id, "createdMs": now_ms(), "moment": m}
                    new.append(m["id"])
        return new

    def moments(self, match_id: str) -> list[dict]:
        with self._lock:
            ms = [{**d["moment"], "createdMs": d.get("createdMs")} for d in self._moments.get(match_id, {}).values()]
        return sorted(ms, key=lambda m: m["detectedAt"]["matchMs"])

    def add_overlays(self, match_id: str, overlays: list[dict], emitted_ms: int | None = None) -> list[str]:
        at = emitted_ms if emitted_ms is not None else now_ms()
        new = []
        with self._lock:
            bucket = self._overlays.setdefault(match_id, {})
            for o in overlays:
                if o["id"] not in bucket:
                    bucket[o["id"]] = {"id": o["id"], "matchId": match_id, "emittedMs": at, "overlay": o}
                    new.append(o["id"])
        return new

    def overlays_since(self, match_id: str, since_ms: int) -> list[dict]:
        with self._lock:
            rows = [d for d in self._overlays.get(match_id, {}).values() if d["emittedMs"] > since_ms]
        return sorted(rows, key=lambda d: (d["emittedMs"], d["id"]))

    def get_state(self, match_id: str, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._state.get((match_id, key), default)

    def put_state(self, match_id: str, key: str, value: Any) -> None:
        with self._lock:
            self._state[(match_id, key)] = value

    def acquire(self, match_id: str, name: str, ttl_ms: int) -> bool:
        """Take a named lock for ``ttl_ms`` (a crashed holder's lock expires on its own). False if someone else holds it."""
        with self._lock:
            held = self._locks.get((match_id, name))
            if held is not None and held > now_ms():
                return False
            self._locks[(match_id, name)] = now_ms() + ttl_ms
            return True

    def release(self, match_id: str, name: str) -> None:
        with self._lock:
            self._locks.pop((match_id, name), None)


class CosmosLiveStore:
    """The same interface on Cosmos DB for NoSQL, with the identity the service runs as (no keys)."""

    CONTAINERS = ("matches", "events", "moments", "overlays", "state")

    def __init__(self, endpoint: str, database: str = "matchmind", credential: Any = None) -> None:
        from azure.cosmos import CosmosClient
        from azure.identity import DefaultAzureCredential

        client = CosmosClient(endpoint, credential=credential or DefaultAzureCredential())
        db = client.get_database_client(database)
        self._c = {name: db.get_container_client(name) for name in self.CONTAINERS}

    def _query(self, name: str, match_id: str | None, sql: str, params: list[dict] | None = None) -> list[dict]:
        kw: dict = {"query": sql, "parameters": params or []}
        if match_id is None:
            kw["enable_cross_partition_query"] = True
        else:
            kw["partition_key"] = match_id
        return list(self._c[name].query_items(**kw))

    def _create_if_absent(self, name: str, doc: dict) -> bool:
        from azure.cosmos.exceptions import CosmosResourceExistsError

        try:
            self._c[name].create_item(doc)
            return True
        except CosmosResourceExistsError:
            return False

    def put_match(self, match_id: str, info: dict) -> None:
        self._c["matches"].upsert_item({**info, "id": match_id, "matchId": match_id})

    def get_match(self, match_id: str) -> dict | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return self._c["matches"].read_item(item=match_id, partition_key=match_id)
        except CosmosResourceNotFoundError:
            return None

    def list_matches(self) -> list[dict]:
        return self._query("matches", None, "SELECT * FROM c")

    def add_docs(self, match_id: str, docs: list[dict]) -> None:
        for d in docs:
            self._create_if_absent("events", {**d, "matchId": match_id})

    def docs(self, match_id: str) -> list[dict]:
        return sorted(self._query("events", match_id, "SELECT * FROM c"), key=sort_key)

    def docs_between(self, match_id: str, after_ms: int, upto_ms: int) -> list[dict]:
        rows = self._query("events", match_id, "SELECT * FROM c WHERE c.arrivalMs > @a AND c.arrivalMs <= @b", [{"name": "@a", "value": after_ms}, {"name": "@b", "value": upto_ms}])
        return sorted(rows, key=sort_key)

    def docs_after(self, match_id: str, n: int, limit: int = 200) -> list[dict]:
        return self._query("events", match_id, f"SELECT TOP {int(limit)} * FROM c WHERE c.n > @n ORDER BY c.n", [{"name": "@n", "value": n}])

    def add_moments(self, match_id: str, moments: list[dict]) -> list[str]:
        return [m["id"] for m in moments if self._create_if_absent("moments", {"id": m["id"], "matchId": match_id, "createdMs": now_ms(), "moment": m})]

    def moments(self, match_id: str) -> list[dict]:
        rows = self._query("moments", match_id, "SELECT c.moment, c.createdMs FROM c")
        return sorted(({**r["moment"], "createdMs": r.get("createdMs")} for r in rows), key=lambda m: m["detectedAt"]["matchMs"])

    def add_overlays(self, match_id: str, overlays: list[dict], emitted_ms: int | None = None) -> list[str]:
        at = emitted_ms if emitted_ms is not None else now_ms()
        return [o["id"] for o in overlays if self._create_if_absent("overlays", {"id": o["id"], "matchId": match_id, "emittedMs": at, "overlay": o})]

    def overlays_since(self, match_id: str, since_ms: int) -> list[dict]:
        return self._query("overlays", match_id, "SELECT * FROM c WHERE c.emittedMs > @s ORDER BY c.emittedMs", [{"name": "@s", "value": since_ms}])

    def get_state(self, match_id: str, key: str, default: Any = None) -> Any:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            return self._c["state"].read_item(item=key, partition_key=match_id)["value"]
        except CosmosResourceNotFoundError:
            return default

    def put_state(self, match_id: str, key: str, value: Any) -> None:
        self._c["state"].upsert_item({"id": key, "matchId": match_id, "value": value})

    def acquire(self, match_id: str, name: str, ttl_ms: int) -> bool:
        """A lock as a document: created if absent, taken over (with its etag, so only one taker wins) if its holder's time ran out."""
        from azure.core import MatchConditions
        from azure.cosmos.exceptions import (
            CosmosAccessConditionFailedError,
            CosmosResourceExistsError,
            CosmosResourceNotFoundError,
        )

        doc = {"id": f"lock-{name}", "matchId": match_id, "expiresMs": now_ms() + ttl_ms}
        try:
            self._c["state"].create_item(doc)
            return True
        except CosmosResourceExistsError:
            pass
        try:
            held = self._c["state"].read_item(item=doc["id"], partition_key=match_id)
        except CosmosResourceNotFoundError:
            return self.acquire(match_id, name, ttl_ms)
        if held.get("expiresMs", 0) > now_ms():
            return False
        try:
            self._c["state"].replace_item(item=doc["id"], body=doc, etag=held["_etag"], match_condition=MatchConditions.IfNotModified)
            return True
        except CosmosAccessConditionFailedError:
            return False

    def release(self, match_id: str, name: str) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            self._c["state"].delete_item(item=f"lock-{name}", partition_key=match_id)
        except CosmosResourceNotFoundError:
            pass
