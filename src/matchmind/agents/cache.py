"""The Cache agent: remembers verified model text so a repeated request costs no model call.

A beat is keyed by match, moment, cohort, model and prompt version: change the prompt or the model and old text is
never served. Only model-written text (fallback level 0 or 1) is stored. A template is cheap to rebuild, and keeping
it would stop a later request from trying the model again.

It is a small in-memory LRU with an expiry, enough for one Brain replica. The interface is two methods, so a shared
store (Cosmos DB) can replace it when several replicas must see the same answers.
"""

from __future__ import annotations

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
