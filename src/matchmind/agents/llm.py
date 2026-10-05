"""Chat clients for the agent team.

Every agent talks to a Microsoft Agent Framework chat client, so the same agents run against:

* ``offline``  a deterministic client that answers from the template engine. It needs no network
               and no key, which is what tests, CI and the zero-cost replay build use.
* ``openai``   any OpenAI-compatible endpoint (GitHub Models, Ollama, Azure OpenAI v1 ...)
* ``foundry``  a Microsoft Foundry project

``FaultyChatClient`` wraps any of them and can be told to fail, stall or hallucinate, which is how
the recovery paths are tested and how the Director console demonstrates a model outage.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

from agent_framework import BaseChatClient, ChatResponse, Content, Message

from ..core.contracts import (
    BeatChoice,
    Cohort,
    EditorOut,
    StoryOut,
)
from . import templates as T

TASK_PREFIX = "TASK:"
MUST_SHOW = {"goal", "red_card", "penalty"}


def task_message(task: str, payload: dict[str, Any]) -> str:
    """The user message every agent receives: a task header and a JSON payload."""
    return f"{TASK_PREFIX} {task}\n{json.dumps(payload, ensure_ascii=False, default=str)}"


def parse_task(text: str) -> tuple[str, dict[str, Any]]:
    head, _, body = text.partition("\n")
    if not head.startswith(TASK_PREFIX):
        raise ValueError("offline client expects a 'TASK: <name>' header")
    return head[len(TASK_PREFIX) :].strip(), json.loads(body)


# ---------------------------------------------------------------------------------------------
# Faults
# ---------------------------------------------------------------------------------------------


@dataclass
class Faults:
    """Mutable failure switches shared between a client and whoever is demonstrating failure."""

    mode: str = "none"  # none | error | slow | hallucinate
    delay_s: float = 5.0  # for slow
    remaining: int | None = None  # how many calls the fault affects (None = until cleared)
    tasks: frozenset[str] | None = None  # limit the fault to these tasks (None = every task)
    every: int = 1  # affect every Nth matching call (2 = alternate calls), for a flaky rather than dead model
    _seen: int = 0

    def active(self, task: str | None = None) -> bool:
        if self.mode == "none" or (self.remaining is not None and self.remaining <= 0):
            return False
        return self.tasks is None or task is None or task in self.tasks

    def hit(self, task: str | None = None) -> bool:
        """Does the fault apply to *this* call? Counts matching calls so ``every`` can alternate."""
        if not self.active(task):
            return False
        self._seen += 1
        return self._seen % max(1, self.every) == 0

    def consume(self) -> None:
        if self.remaining is not None and self.remaining > 0:
            self.remaining -= 1


class ModelUnavailable(RuntimeError):
    """The model endpoint failed (injected or real)."""


# ---------------------------------------------------------------------------------------------
# Offline client
# ---------------------------------------------------------------------------------------------


HEADLINE_SALIENCE = 0.6  # a story this strong is always told, whatever the budget


def _priority(salience: float) -> int:
    return 1 if salience >= 0.9 else 2 if salience >= 0.7 else 3 if salience >= 0.5 else 4 if salience >= 0.35 else 5


def offline_edit(payload: dict) -> EditorOut:
    """A deterministic Editor: must-show events, then the most salient stories within budget."""
    moments = payload["moments"]
    budget = int(payload.get("budget", 3))
    chosen: dict[str, BeatChoice] = {}
    optional = []
    for m in moments:
        if m["type"] in MUST_SHOW:
            chosen[m["id"]] = BeatChoice(momentId=m["id"], keep=True, priority=_priority(m["salience"]), reason="must show")
        else:
            optional.append(m)
    seen: dict[tuple, str] = {}
    for m in sorted(optional, key=lambda m: -m["salience"]):
        key = (m["type"], m.get("subjectTeam"))
        if key in seen:  # the same story twice in one batch: keep the stronger, note the merge
            chosen[seen[key]].mergeWith.append(m["id"])
            chosen[m["id"]] = BeatChoice(momentId=m["id"], keep=False, priority=5, reason="merged")
            continue
        keep = m["salience"] >= 0.3 and (budget > 0 or m["salience"] >= HEADLINE_SALIENCE)
        if keep and m["salience"] < HEADLINE_SALIENCE:
            budget -= 1
        chosen[m["id"]] = BeatChoice(
            momentId=m["id"], keep=keep, priority=_priority(m["salience"]),
            storyline=f"{m['type']}:{m.get('subjectTeam') or 'match'}",
            reason="within budget" if keep else "below budget",
        )  # fmt: skip
        if keep:
            seen[key] = m["id"]
    return EditorOut(beats=[chosen[m["id"]] for m in moments if m["id"] in chosen])


def _cohort(key: str) -> Cohort:
    mode, lang, persp, focus = key.split("/")
    return Cohort(mode=mode, language=lang, perspective=persp, focusPlayer=None if focus == "-" else focus)


def offline_answer(task: str, payload: dict, context: dict | None = None) -> str:
    if task == "edit":
        return offline_edit(payload).model_dump_json()
    if task == "explain":
        return T.explain(payload["pack"]).model_dump_json()
    if task == "story":
        variants = [T.render(payload["pack"], _cohort(k)) for k in payload["cohorts"]]
        return StoryOut(variants=variants).model_dump_json()
    if task == "localize":
        return T.render(payload["pack"], _cohort(payload["cohort"])).model_dump_json()
    if task == "recap":
        from . import recap as R

        return R.render(payload["pack"], _cohort(payload["cohort"]), (context or {}).get("moments")).model_dump_json()
    if task == "causal":
        return json.dumps({"supported": True, "reason": "offline"})
    raise ValueError(f"unknown task {task!r}")


def hallucinate(task: str, answer: str) -> str:
    """Corrupt a good answer the way a careless model might: an invented number and name."""
    data = json.loads(answer)
    fake = "Rafael Brandmont made 99 shots"
    if task == "explain":
        data["why"] = f"{fake}; {data['why']}"
    elif task == "story":
        for v in data["variants"]:
            v["body"] = f"{fake}. {v['body']}"
    elif task == "localize":
        data["body"] = f"{fake}. {data['body']}"
    elif task == "recap":
        data["summary"] = f"{fake}. {data['summary']}"
    return json.dumps(data, ensure_ascii=False)


class OfflineChatClient(BaseChatClient):
    """Answers from the template engine. Deterministic, free and instant."""

    def __init__(self, faults: Faults | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.faults = faults or Faults()
        self.calls: list[str] = []
        # Side channel for data a real model would get through tools, not the prompt (e.g. full moment packs).
        self.context: dict = {}

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):  # type: ignore[override]
        await self._validate_options(options)
        user = [m for m in messages if m.role == "user"][-1].text
        task, payload = parse_task(user)
        self.calls.append(task)
        answer = offline_answer(task, payload, self.context)
        if self.faults.hit(task):
            mode = self.faults.mode
            self.faults.consume()
            if mode == "error":
                raise ModelUnavailable("injected model outage")
            if mode == "slow":
                await asyncio.sleep(self.faults.delay_s)
            elif mode == "hallucinate":
                answer = hallucinate(task, answer)
        return ChatResponse(
            messages=[Message("assistant", [Content.from_text(answer)])],
            response_format=options.get("response_format"),
            model="offline-template",
        )


class FaultyChatClient(BaseChatClient):
    """Wraps a real client and applies :class:`Faults` before delegating."""

    def __init__(self, inner: BaseChatClient, faults: Faults, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.inner, self.faults = inner, faults

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):  # type: ignore[override]
        await self._validate_options(options)
        if self.faults.active():
            mode = self.faults.mode
            self.faults.consume()
            if mode == "error":
                raise ModelUnavailable("injected model outage")
            if mode == "slow":
                await asyncio.sleep(self.faults.delay_s)
        return await self.inner.get_response(messages, options=options)


# ---------------------------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------------------------


def make_chat_client(kind: str | None = None, faults: Faults | None = None) -> BaseChatClient:
    """Build a chat client from ``MATCHMIND_LLM`` (offline | openai | foundry) and friends.

    openai:  MATCHMIND_LLM_MODEL, MATCHMIND_LLM_BASE_URL, MATCHMIND_LLM_API_KEY
             (GitHub Models: https://models.github.ai/inference; Ollama: http://localhost:11434/v1)
    foundry: FOUNDRY_PROJECT_ENDPOINT, MATCHMIND_LLM_MODEL; authenticates with DefaultAzureCredential
    """
    kind = (kind or os.environ.get("MATCHMIND_LLM", "offline")).lower()
    faults = faults or Faults()
    if kind == "offline":
        return OfflineChatClient(faults=faults)
    if kind == "openai":
        from agent_framework.openai import OpenAIChatCompletionClient

        client = OpenAIChatCompletionClient(
            model=os.environ["MATCHMIND_LLM_MODEL"],
            base_url=os.environ.get("MATCHMIND_LLM_BASE_URL"),
            api_key=os.environ.get("MATCHMIND_LLM_API_KEY", "none"),
        )
    elif kind == "foundry":
        from agent_framework.foundry import FoundryChatClient
        from azure.identity import DefaultAzureCredential

        client = FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
            model=os.environ["MATCHMIND_LLM_MODEL"],
            credential=DefaultAzureCredential(),
        )
    else:
        raise ValueError(f"unknown MATCHMIND_LLM {kind!r}; use offline, openai or foundry")
    return FaultyChatClient(client, faults)

