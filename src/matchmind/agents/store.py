"""Shared state for the agent team.

Agents never call each other directly; they read and write the *moment document*, which holds
the status, each agent's output and a trace of what every agent did. In Azure this is the Cosmos
DB ``moments`` container; locally it is a dict. The trace is what the Foundry/Monitor dashboards
and the Director console render.
"""

from __future__ import annotations

import time
from typing import Any, Protocol


class MomentStore(Protocol):
    def put(self, moment_id: str, **fields: Any) -> None: ...
    def trace(self, moment_id: str, agent: str, outcome: str, ms: float, **extra: Any) -> None: ...
    def get(self, moment_id: str) -> dict[str, Any]: ...


class InMemoryMomentStore:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    def put(self, moment_id: str, **fields: Any) -> None:
        self.docs.setdefault(moment_id, {"momentId": moment_id, "trace": []}).update(fields)

    def trace(self, moment_id: str, agent: str, outcome: str, ms: float, **extra: Any) -> None:
        doc = self.docs.setdefault(moment_id, {"momentId": moment_id, "trace": []})
        doc["trace"].append({"agent": agent, "outcome": outcome, "ms": round(ms, 1), "at": time.time(), **extra})

    def get(self, moment_id: str) -> dict[str, Any]:
        return self.docs.get(moment_id, {})

    def all_traces(self) -> list[dict[str, Any]]:
        return [step | {"momentId": d["momentId"]} for d in self.docs.values() for step in d["trace"]]
