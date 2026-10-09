"""The Cache agent: remembers verified model text so a repeated request costs no model call.

A beat is keyed by match, moment, cohort, model and prompt version: change the prompt or the model and old text is
never served. Only model-written text (fallback level 0 or 1) is stored. A template is cheap to rebuild, and keeping
it would stop a later request from trying the model again.

It is a small in-memory LRU with an expiry, enough for one Brain replica. The interface is two methods, so a shared
store (Cosmos DB) can replace it when several replicas must see the same answers.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from ..core.contracts import StoryVariant


@dataclass(frozen=True)
class Cached:
    variant: StoryVariant
    level: int
    agents: tuple[str, ...]  # the agents that made it, so a hit still shows who wrote the text


class BeatCache:
    def __init__(self, max_items: int = 2048, ttl_s: float = 3600.0, clock: Callable[[], float] = time.monotonic) -> None:
        self.max_items, self.ttl_s, self._clock = max_items, ttl_s, clock
        self._items: OrderedDict[tuple, tuple[float, Cached]] = OrderedDict()

    @staticmethod
    def key(match_id: str, moment_id: str, cohort_key: str, model: str, prompt_version: str) -> tuple:
        return (match_id, moment_id, cohort_key, model, prompt_version)

    def get(self, key: tuple) -> Cached | None:
        hit = self._items.get(key)
        if hit is None:
            return None
        stored_at, value = hit
        if self._clock() - stored_at > self.ttl_s:
            del self._items[key]
            return None
        self._items.move_to_end(key)
        return value

    def put(self, key: tuple, value: Cached) -> None:
        if value.level > 1:
            return  # templates are never cached
        self._items[key] = (self._clock(), value)
        self._items.move_to_end(key)
        while len(self._items) > self.max_items:
            self._items.popitem(last=False)

    def __len__(self) -> int:
        return len(self._items)

    def clear(self) -> None:
        self._items.clear()


# ---------------------------------------------------------------------------------------------
# A shared layer: Cosmos DB behind the in-memory cache
# ---------------------------------------------------------------------------------------------


def doc_id(key: tuple) -> str:
    """A stable Cosmos document id for a cache key (ids may not contain ``/``, and keys carry free text)."""
    return hashlib.sha256("\x1f".join(key).encode()).hexdigest()[:40]


class SharedBeatCache:
    """The in-memory :class:`BeatCache` with Cosmos DB behind it, so verified text survives a restart and is shared by replicas.

    * ``get`` looks in memory, then in Cosmos, and keeps what it finds in memory;
    * ``put`` stores in memory at once and writes to Cosmos in the background;
    * every Cosmos call is time-boxed and any error is a miss: the shared layer can only make a request faster, never slower
      or broken (the request has a 5 s deadline). After a failure the layer is left alone for ``cooldown_s``.

    ``open_container`` is an async callable returning a Cosmos container client (partition key ``/matchId``).
    """

    def __init__(self, local: BeatCache, open_container, *, ttl_s: int = 7 * 86400, timeout_s: float = 0.6, cooldown_s: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:  # noqa: ANN001
        self.local, self._open, self.ttl_s, self.timeout_s, self.cooldown_s, self._clock = local, open_container, ttl_s, timeout_s, cooldown_s, clock
        self._container = None
        self._down_until = 0.0
        self._pending: set[asyncio.Future] = set()

    async def _use(self):  # noqa: ANN202
        if self._clock() < self._down_until:
            return None
        if self._container is None:
            try:
                self._container = await asyncio.wait_for(self._open(), self.timeout_s * 4)
            except Exception:  # noqa: BLE001
                self._down_until = self._clock() + self.cooldown_s
                return None
        return self._container

    def _fail(self) -> None:
        self._down_until = self._clock() + self.cooldown_s

    async def get(self, key: tuple) -> Cached | None:
        hit = self.local.get(key)
        if hit is not None:
            return hit
        c = await self._use()
        if c is None:
            return None
        try:
            doc = await asyncio.wait_for(c.read_item(item=doc_id(key), partition_key=key[0]), self.timeout_s)
        except TimeoutError:
            self._fail()
            return None
        except Exception:  # noqa: BLE001 - not found is the normal miss; anything else is just a miss too
            return None
        if tuple(doc.get("key", ())) != key:
            return None  # a hash collision or a stale document: never serve text that belongs to another key
        value = Cached(StoryVariant.model_validate(doc["variant"]), int(doc["level"]), tuple(doc["agents"]))
        self.local.put(key, value)
        return value

    async def put(self, key: tuple, value: Cached) -> None:
        self.local.put(key, value)
        if value.level > 1:
            return
        task = asyncio.ensure_future(self._write(key, value))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _write(self, key: tuple, value: Cached) -> None:
        c = await self._use()
        if c is None:
            return
        doc = {
            "id": doc_id(key), "matchId": key[0], "key": list(key), "level": value.level, "agents": list(value.agents),
            "variant": value.variant.model_dump(mode="json"), "ttl": self.ttl_s,
        }
        try:
            await asyncio.wait_for(c.upsert_item(doc), self.timeout_s * 3)
        except TimeoutError:
            self._fail()
        except Exception:  # noqa: BLE001
            pass

    def __len__(self) -> int:
        return len(self.local)
