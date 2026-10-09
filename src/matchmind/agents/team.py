"""The agent team: Editor, Explainer, Storyteller, Localizer, each a Microsoft Agent Framework
``Agent`` with its own instructions and a typed JSON output.

The team is a thin layer: build agents from a chat client, send a task and payload, get a
validated pydantic model back or an :class:`AgentFailure`. Orchestration lives in
``workflow.py``; this module knows nothing about retries or fallbacks.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from typing import Any, TypeVar

from agent_framework import Agent, BaseChatClient
from pydantic import BaseModel, ValidationError

from ..core.contracts import (
    ChatAnswer,
    Cohort,
    EditorOut,
    Explanation,
    Plan,
    Recap,
    StoryOut,
    StoryVariant,
)
from . import prompts
from .llm import task_message
from .verify import valid_refs

M = TypeVar("M", bound=BaseModel)


def names_not_ids(pack: dict) -> dict:
    """A copy of the pack for a small model: player ids ("NOR-21") become names, because small models write the id
    into the text and the digits then fail the number check. Keys stay as they are."""
    by_id = {p["id"]: p["name"] for p in pack.get("players", []) if p.get("id") and p.get("name")}

    def walk(v: Any) -> Any:
        if isinstance(v, str):
            for pid, name in by_id.items():
                v = v.replace(pid, name)
            return v
        if isinstance(v, list):
            return [walk(x) for x in v]
        if isinstance(v, dict):
            return {k: walk(x) for k, x in v.items()}
        return v

    out = walk(pack)
    out["players"] = [{k: p[k] for k in ("name", "team", "pos") if k in p} for p in pack.get("players", [])]
    return out


class AgentFailure(RuntimeError):
    """An agent timed out, errored or returned something unusable."""

    def __init__(self, agent: str, reason: str) -> None:
        super().__init__(f"{agent}: {reason}")
        self.agent, self.reason = agent, reason


# Models that think before they answer (OpenAI's GPT-5 and GPT-6 families and the o-series). They refuse a custom
# temperature, count their hidden reasoning against the output cap, and take seconds rather than a second to answer.
_REASONING_MODEL = re.compile(r"^(gpt-5|gpt-6|o\d)", re.IGNORECASE)
# Models whose endpoint enforces a JSON schema. Others (Phi, Llama, Mistral ...) get the schema in the prompt instead
# and may wrap their answer in a markdown fence.
_STRICT_JSON_MODEL = re.compile(r"^(gpt-|o\d)", re.IGNORECASE)
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL | re.IGNORECASE)


def _json_text(text: str) -> str:
    """The JSON object in a model's answer, without a markdown fence or chatter around it."""
    m = _FENCE.match(text)
    if m:
        text = m.group(1)
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if 0 <= start < end else text


@dataclass
class AgentSettings:
    timeout_s: float = 8.0
    editor_budget: int = 3  # non-mandatory beats per batch
    max_tokens: int = 700
    explain_temperature: float = 0.2
    story_temperature: float = 0.6
    send_temperature: bool = True  # a reasoning model rejects the parameter outright
    structured_output: bool = True  # ask the endpoint to enforce the JSON schema; off: the schema goes in the prompt
    agent_side_options: bool = False  # Foundry-registered agents: schema and temperature live in the agent, calls pass none
    reasoning_effort: str | None = None  # "minimal" | "low" | "medium" | "high" for reasoning models
    beat_budget_s: float | None = None  # wall-clock time a beat has to become overlays (None: the caller's default)

    @classmethod
    def from_env(cls) -> AgentSettings:
        """Settings for the configured model: a reasoning model needs different options and far more time.

        ``MATCHMIND_AGENT_TIMEOUT_S``, ``MATCHMIND_MAX_TOKENS``, ``MATCHMIND_BEAT_BUDGET_S`` and
        ``MATCHMIND_REASONING_EFFORT`` override what is chosen from the model name.
        """
        env = os.environ
        s = cls()
        model = env.get("MATCHMIND_LLM_MODEL", "").split("/")[-1]
        if env.get("MATCHMIND_LLM", "offline").lower() != "offline" and not _STRICT_JSON_MODEL.match(model):
            s.structured_output = False
        if env.get("MATCHMIND_LLM", "offline").lower() != "offline" and _REASONING_MODEL.match(model):
            s.send_temperature = False
            s.max_tokens = 4000  # reasoning tokens count against the cap
            s.timeout_s = 60.0
            s.beat_budget_s = 300.0
            s.reasoning_effort = "low"
        if v := env.get("MATCHMIND_STRUCTURED_OUTPUT"):
            s.structured_output = v.lower() not in ("0", "false", "no")
        if v := env.get("MATCHMIND_AGENT_TIMEOUT_S"):
            s.timeout_s = float(v)
        if v := env.get("MATCHMIND_MAX_TOKENS"):
            s.max_tokens = int(v)
        if v := env.get("MATCHMIND_BEAT_BUDGET_S"):
            s.beat_budget_s = float(v)
        if v := env.get("MATCHMIND_REASONING_EFFORT"):
            s.reasoning_effort = None if v.lower() == "none" else v
        return s


class AgentTeam:
    def __init__(
        self,
        client: BaseChatClient,
        settings: AgentSettings | None = None,
        explainer_tools: Any = None,
        agents: dict[str, Any] | None = None,
    ) -> None:
        """``agents`` replaces the local agents by role (editor, explainer, ...), e.g. with Foundry-registered ones."""
        self.client = client
        self.settings = settings or AgentSettings.from_env()
        a = agents or {}
        self.editor = a.get("editor") or Agent(client, prompts.EDITOR, name="editor")
        self.explainer = a.get("explainer") or Agent(client, prompts.EXPLAINER, name="explainer", tools=explainer_tools)
        self.storyteller = a.get("storyteller") or Agent(client, prompts.STORYTELLER, name="storyteller")
        self.localizer = a.get("localizer") or Agent(client, prompts.LOCALIZER, name="localizer")
        self.recap_writer = a.get("recap_writer") or Agent(client, prompts.RECAP, name="recap_writer")
        self.composer = a.get("composer") or Agent(client, prompts.COMPOSER, name="composer")
        self.planner = a.get("planner") or Agent(client, prompts.PLANNER, name="planner")
        self.answerer = a.get("answerer") or Agent(client, prompts.ANSWERER, name="answerer")

    # ----- one call ----------------------------------------------------------------------------

    def _options(self, model: type[M], temperature: float) -> dict:
        """The chat options for one call, leaving out what the configured model refuses."""
        if self.settings.agent_side_options:
            return {}  # a Foundry agent refuses per-call temperature and response format: they are in its definition
        opts: dict = {"max_tokens": self.settings.max_tokens}
        if self.settings.structured_output:
            opts["response_format"] = model
        if self.settings.send_temperature:
            opts["temperature"] = temperature
        if self.settings.reasoning_effort:
            opts["reasoning"] = {"effort": self.settings.reasoning_effort}
        return opts

    async def _ask(
        self, agent: Agent, task: str, payload: dict, model: type[M], temperature: float, timeout_s: float | None = None, usage: dict | None = None
    ) -> M:
        """One call. ``usage``, if given, gets the call's token counts added to ``inputTokens`` and ``outputTokens``."""
        name = agent.name or task
        options = self._options(model, temperature)
        try:
            message = task_message(task, payload)
            if not self.settings.structured_output and not self.settings.agent_side_options:
                schema = json.dumps(model.model_json_schema(), ensure_ascii=False)
                message += f"\nReply with one JSON object only, no markdown fence, matching this JSON schema:\n{schema}"
            limit = self.settings.timeout_s if timeout_s is None else min(timeout_s, self.settings.timeout_s)
            resp = await asyncio.wait_for(agent.run(message, options=options), timeout=limit)
        except TimeoutError as e:
            raise AgentFailure(name, f"no answer within {limit:g}s") from e
        except AgentFailure:
            raise
        except Exception as e:  # network, auth, content filter, injected outage ...
            raise AgentFailure(name, f"{type(e).__name__}: {e}") from e
        if usage is not None:
            u = getattr(resp, "usage_details", None) or {}
            usage["inputTokens"] = usage.get("inputTokens", 0) + int(u.get("input_token_count") or 0)
            usage["outputTokens"] = usage.get("outputTokens", 0) + int(u.get("output_token_count") or 0)
        value = resp.value if self.settings.structured_output and not self.settings.agent_side_options else None
        if isinstance(value, model):
            return value
        try:
            return model.model_validate_json(_json_text(resp.text))
        except (ValidationError, ValueError) as e:
            raise AgentFailure(name, "the answer was not valid JSON for the schema") from e

    # ----- the four roles --------------------------------------------------------------------------

    async def edit(self, moments: list[dict], budget: int | None = None) -> EditorOut:
        slim = [
            {"id": m["id"], "type": m["type"], "salience": m["salience"], "subjectTeam": m["subjectTeam"],
             "minute": m["detectedAt"]["label"]}
            for m in moments
        ]  # fmt: skip
        payload = {"moments": slim, "budget": self.settings.editor_budget if budget is None else budget}
        return await self._ask(self.editor, "edit", payload, EditorOut, 0.1)

    async def explain(self, pack: dict, feedback: str = "") -> Explanation:
        payload = {"pack": pack, "validRefs": sorted(valid_refs(pack)), "feedback": feedback}
        return await self._ask(self.explainer, "explain", payload, Explanation, self.settings.explain_temperature)

    async def plan(self, payload: dict, timeout_s: float | None = None, usage: dict | None = None) -> Plan:
        """The chat's first step: which match-data tools answer this question (a refusal if it is off topic)."""
        return await self._ask(self.planner, "plan", payload, Plan, 0.0, timeout_s, usage)

    async def answer(self, payload: dict, timeout_s: float | None = None, usage: dict | None = None) -> ChatAnswer:
        """The chat's last step: the answer, written only from what the tools returned."""
        return await self._ask(self.answerer, "answer", payload, ChatAnswer, 0.2, timeout_s, usage)

    async def compose(self, pack: dict, cohort: Cohort, timeout_s: float | None = None, usage: dict | None = None) -> StoryVariant:
        """The fast path: one call that explains and writes the story for one cohort, in its language."""
        refs = sorted(r for r in valid_refs(pack) if not r.startswith("player:"))
        payload = {"pack": names_not_ids(pack), "validRefs": refs, "cohort": cohort.key}
        return await self._ask(self.composer, "compose", payload, StoryVariant, self.settings.story_temperature, timeout_s, usage)

    async def tell(self, pack: dict, explanation: Explanation, cohorts: list[Cohort], feedback: str = "") -> StoryOut:
        payload = {
            "pack": pack,
            "explanation": explanation.model_dump(),
            "cohorts": [c.key for c in cohorts],
            "feedback": feedback,
        }
        return await self._ask(self.storyteller, "story", payload, StoryOut, self.settings.story_temperature)

    async def localize(self, pack: dict, base: StoryVariant, cohort: Cohort) -> StoryVariant:
        payload = {"pack": pack, "variant": base.model_dump(), "cohort": cohort.key}
        return await self._ask(self.localizer, "localize", payload, StoryVariant, self.settings.story_temperature)

    async def recap(self, pack: dict, cohort: Cohort, moments: dict[str, dict] | None = None) -> Recap:
        # The prompt carries a slim summary of the key moments; full packs stay out of it.
        slim = [
            {"id": mid, "type": m["type"], "label": m["detectedAt"]["label"], "team": m["subjectTeam"]}
            for mid in pack.get("keyMoments", []) if (m := (moments or {}).get(mid))
        ]
        payload = {"pack": pack, "cohort": cohort.key, "moments": slim}
        return await self._ask(self.recap_writer, "recap", payload, Recap, self.settings.story_temperature)
