"""The agent team: Editor, Explainer, Storyteller, Localizer, each a Microsoft Agent Framework
``Agent`` with its own instructions and a typed JSON output.

The team is a thin layer: build agents from a chat client, send a task and payload, get a
validated pydantic model back or an :class:`AgentFailure`. Orchestration lives in
``workflow.py``; this module knows nothing about retries or fallbacks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, TypeVar

from agent_framework import Agent, BaseChatClient
from pydantic import BaseModel, ValidationError

from ..core.contracts import Cohort, EditorOut, Explanation, Recap, StoryOut, StoryVariant
from . import prompts
from .llm import task_message

M = TypeVar("M", bound=BaseModel)


class AgentFailure(RuntimeError):
    """An agent timed out, errored or returned something unusable."""

    def __init__(self, agent: str, reason: str) -> None:
        super().__init__(f"{agent}: {reason}")
        self.agent, self.reason = agent, reason


@dataclass
class AgentSettings:
    timeout_s: float = 8.0
    editor_budget: int = 3  # non-mandatory beats per batch
    max_tokens: int = 700
    explain_temperature: float = 0.2
    story_temperature: float = 0.6


class AgentTeam:
    def __init__(
        self,
        client: BaseChatClient,
        settings: AgentSettings | None = None,
        explainer_tools: Any = None,
    ) -> None:
        self.client = client
        self.settings = settings or AgentSettings()
        self.editor = Agent(client, prompts.EDITOR, name="editor")
        self.explainer = Agent(client, prompts.EXPLAINER, name="explainer", tools=explainer_tools)
        self.storyteller = Agent(client, prompts.STORYTELLER, name="storyteller")
        self.localizer = Agent(client, prompts.LOCALIZER, name="localizer")
        self.recap_writer = Agent(client, prompts.RECAP, name="recap_writer")

    # ----- one call ----------------------------------------------------------------------------

    async def _ask(self, agent: Agent, task: str, payload: dict, model: type[M], temperature: float) -> M:
        name = agent.name or task
        options = {"response_format": model, "temperature": temperature, "max_tokens": self.settings.max_tokens}
        try:
            resp = await asyncio.wait_for(
                agent.run(task_message(task, payload), options=options), timeout=self.settings.timeout_s
            )
        except TimeoutError as e:
            raise AgentFailure(name, f"no answer within {self.settings.timeout_s:g}s") from e
        except AgentFailure:
            raise
        except Exception as e:  # network, auth, content filter, injected outage ...
            raise AgentFailure(name, f"{type(e).__name__}: {e}") from e
        value = resp.value
        if isinstance(value, model):
            return value
        try:
            return model.model_validate_json(resp.text)
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
        payload = {"pack": pack, "feedback": feedback}
        return await self._ask(self.explainer, "explain", payload, Explanation, self.settings.explain_temperature)

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
