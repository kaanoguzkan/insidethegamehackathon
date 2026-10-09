"""The MatchMind agents as Microsoft Foundry agents.

Each agent's instructions (``agents/prompts.py``) are registered in the Foundry project as a versioned *prompt agent*,
so the team shows up in the Foundry portal with its prompts, versions and traces, and can be called by name. The
registered version carries the prompt version in its metadata; registering again with unchanged instructions is a
no-op on the Foundry side (it creates a new version only when the definition changed).

    matchmind foundry-register          # create or update the agents in the project
    MATCHMIND_AGENTS=foundry ...        # the Brain's full workflow then calls these agents instead of local ones

Needs ``FOUNDRY_PROJECT_ENDPOINT`` and ``MATCHMIND_LLM_MODEL`` (a model deployment in the project).
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel

from .agents import prompts
from .agents.team import AgentSettings, AgentTeam
from .core.contracts import EditorOut, Explanation, Recap, StoryOut, StoryVariant


class Spec:
    """One agent: its Foundry name, which AgentTeam role it fills, its prompt, output schema and temperature."""

    def __init__(self, name: str, role: str, instructions: str, description: str, output: type[BaseModel], temperature: float) -> None:
        self.name, self.role, self.instructions, self.description, self.output, self.temperature = name, role, instructions, description, output, temperature


# The schema and temperature are part of each agent's definition: a registered agent refuses them per call.
SPECS: list[Spec] = [
    Spec("matchmind-editor", "editor", prompts.EDITOR, "Chooses which detected moments become on-screen story beats.", EditorOut, 0.1),
    Spec("matchmind-explainer", "explainer", prompts.EXPLAINER, "Explains why a moment matters, citing the evidence pack.", Explanation, 0.2),
    Spec("matchmind-storyteller", "storyteller", prompts.STORYTELLER, "Writes the English story for each viewer cohort.", StoryOut, 0.6),
    Spec("matchmind-localizer", "localizer", prompts.LOCALIZER, "Rewrites a verified story natively in Spanish or Turkish.", StoryVariant, 0.6),
    Spec("matchmind-composer", "composer", prompts.COMPOSER, "Fast path: explains and writes one cohort's story in one call.", StoryVariant, 0.6),
    Spec("matchmind-recap-writer", "recap_writer", prompts.RECAP, "Writes the pre-match, half-time and full-time recaps.", Recap, 0.6),
]


def register(endpoint: str | None = None, model: str | None = None) -> list[dict[str, Any]]:
    """Create (or add a version of) every agent in the Foundry project. Returns what the project now holds."""
    from agent_framework import Agent
    from agent_framework.foundry import FoundryChatClient, to_prompt_agent
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = endpoint or os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    model = model or os.environ.get("MATCHMIND_LLM_MODEL", "gpt-4.1-mini")
    cred = DefaultAzureCredential()
    chat = FoundryChatClient(project_endpoint=endpoint, model=model, credential=cred)
    project = AIProjectClient(endpoint=endpoint, credential=cred)
    out = []
    for sp in SPECS:
        agent = Agent(chat, sp.instructions, name=sp.name, default_options={"response_format": sp.output, "temperature": sp.temperature})
        v = project.agents.create_version(
            agent_name=sp.name, definition=to_prompt_agent(agent), description=sp.description,
            metadata={"promptVersion": prompts.PROMPT_VERSION, "app": "matchmind"},
        )
        out.append({"name": sp.name, "version": getattr(v, "version", None), "id": getattr(v, "id", None), "model": model})
    return out


def stale_agents(project: Any) -> list[str]:
    """Names of registered agents whose stored prompt version differs from this code's, or that are missing.

    A registered agent carries its own instructions. If ``prompts.py`` changed and ``foundry-register`` was not run again,
    the service would keep answering with the old prompts while its cache is keyed on the new version.
    """
    stale = []
    for sp in SPECS:
        try:
            latest = project.agents.get(agent_name=sp.name)["versions"]["latest"]
            registered = (latest.get("metadata") or {}).get("promptVersion")
        except Exception:  # noqa: BLE001 - missing, forbidden or unreachable all mean "cannot trust it"
            registered = None
        if registered != prompts.PROMPT_VERSION:
            stale.append(f"{sp.name} (registered {registered}, code {prompts.PROMPT_VERSION})")
    return stale


def foundry_team(chat_client: Any, endpoint: str | None = None) -> tuple[AgentTeam | None, list[str]]:
    """An :class:`AgentTeam` whose agents are the ones registered in Foundry (called by name, latest version).

    Returns ``(None, problems)`` when any registered agent is stale or missing, so the caller can fall back to local agents.
    """
    from agent_framework.foundry import FoundryAgent
    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = endpoint or os.environ["FOUNDRY_PROJECT_ENDPOINT"]
    cred = DefaultAzureCredential()
    problems = stale_agents(AIProjectClient(endpoint=endpoint, credential=cred))
    if problems:
        return None, problems
    agents = {sp.role: FoundryAgent(project_endpoint=endpoint, agent_name=sp.name, credential=cred) for sp in SPECS}
    settings = AgentSettings.from_env()
    settings.agent_side_options = True
    return AgentTeam(chat_client, settings, agents=agents), []
