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

from .agents import prompts

# Foundry agent name -> (instructions, what it does). The names are the public address of each agent.
AGENTS: dict[str, tuple[str, str]] = {
    "matchmind-editor": (prompts.EDITOR, "Chooses which detected moments become on-screen story beats."),
    "matchmind-explainer": (prompts.EXPLAINER, "Explains why a moment matters, citing the evidence pack."),
    "matchmind-storyteller": (prompts.STORYTELLER, "Writes the English story for each viewer cohort."),
    "matchmind-localizer": (prompts.LOCALIZER, "Rewrites a verified story natively in Spanish or Turkish."),
    "matchmind-composer": (prompts.COMPOSER, "Fast path: explains and writes one cohort's story in one call."),
    "matchmind-recap-writer": (prompts.RECAP, "Writes the pre-match, half-time and full-time recaps."),
}


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
    for name, (instructions, description) in AGENTS.items():
        definition = to_prompt_agent(Agent(chat, instructions, name=name))
        v = project.agents.create_version(
            agent_name=name, definition=definition, description=description,
            metadata={"promptVersion": prompts.PROMPT_VERSION, "app": "matchmind"},
        )
        out.append({"name": name, "version": getattr(v, "version", None), "id": getattr(v, "id", None), "model": model})
    return out
