"""The MatchMind newsroom as a Microsoft Foundry hosted agent.

Foundry runs this file in a container it manages and exposes it at the project's agent endpoint
(``.../agents/matchmind-newsroom/endpoint/protocols/openai/responses``). The message is a JSON request, the reply a JSON
answer: the same ``BeatRequest`` and answer as the Brain's ``POST /api/beats``, produced by the same code
(``matchmind.agents.service.serve_beats``) with the same agents, Verifier, Repairer and fallback ladder.

    {"match_id": "red-card-drama", "moment_ids": ["red-card-drama-mo-003"],
     "cohorts": [{"mode": "casual", "language": "en"}], "mode": "fast"}

``matchmind foundry-host`` zips this file with the ``matchmind`` package and the replay packages' moments and uploads
it. Locally: ``python foundry/hosted/main.py`` serves on port 8088.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# The packaged zip first (the file sits at /app/main.py, which has no grandparent), then a repository checkout.
for candidate in (HERE / "src", *(p / "src" for p in HERE.parents[1:2])):
    if (candidate / "matchmind").exists():
        sys.path.insert(0, str(candidate))
        break
data = HERE / "data"
if data.exists():
    os.environ.setdefault("MATCHMIND_DATA", str(data))
os.environ.setdefault("MATCHMIND_LLM", "foundry")

from agent_framework import (  # noqa: E402
    AgentResponse,
    AgentResponseUpdate,
    BaseAgent,
    Content,
    Message,
    ResponseStream,
)
from agent_framework.foundry import FoundryChatClient, ResponsesHostServer  # noqa: E402
from azure.identity import DefaultAzureCredential  # noqa: E402

from matchmind.agents.cache import BeatCache  # noqa: E402
from matchmind.agents.service import (  # noqa: E402
    BeatRequest,
    UnknownMoments,
    load_recorded,
    serve_beats,
)
from matchmind.agents.team import AgentSettings, AgentTeam  # noqa: E402
from matchmind.core.paths import replays_dir  # noqa: E402

USAGE = (
    "Send a JSON request, for example "
    '{"match_id": "red-card-drama", "moment_ids": ["red-card-drama-mo-003"], "cohorts": [{"mode": "casual", "language": "en"}]}. '
    "Optional: mode (fast|full), deadlineMs, budget, useCache."
)


def _json_in(text: str) -> dict | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        return json.loads(m.group(0)) if m else None
    except ValueError:
        return None


class Newsroom(BaseAgent):
    """Turns a request for moments and viewer cohorts into verified overlays."""

    def __init__(self) -> None:
        super().__init__(name="matchmind-newsroom", description="Explained, personalized match overlays: editor, composer, verifier, repairer, producer.")
        client = FoundryChatClient(
            project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], model=os.environ.get("MATCHMIND_LLM_MODEL", "gpt-4.1-mini"),
            credential=DefaultAzureCredential(),
        )
        self.team = AgentTeam(client, AgentSettings.from_env())
        self.cache = BeatCache()
        self.recorded: dict = {}

    async def _answer(self, text: str) -> str:
        raw = _json_in(text)
        if raw is None:
            return json.dumps({"error": "no JSON request found", "usage": USAGE})
        try:
            req = BeatRequest.model_validate(raw)
        except ValueError as e:
            return json.dumps({"error": "invalid request", "detail": str(e)[:600], "usage": USAGE})
        loaded = self.recorded.get(req.match_id)
        if loaded is None:
            loaded = load_recorded(replays_dir(), req.match_id)  # refuses anything but a plain slug
            if loaded is not None and len(self.recorded) < 64:
                self.recorded[req.match_id] = loaded
        if loaded is None:
            return json.dumps({"error": f"unknown match {req.match_id!r}"})
        packs, names = loaded
        try:
            answer = await serve_beats(req, packs=packs, registry=names, team=self.team, cache=self.cache)
        except UnknownMoments as e:
            return json.dumps({"error": str(e)})
        return json.dumps(answer, ensure_ascii=False)

    @staticmethod
    def _text_of(messages) -> str:  # noqa: ANN001
        items = messages if isinstance(messages, list) else ([messages] if messages is not None else [])
        text = ""
        for m in items:
            text = m if isinstance(m, str) else (getattr(m, "text", None) or text)
        return text

    async def _once(self, messages):  # noqa: ANN001
        answer = await self._answer(self._text_of(messages))
        return AgentResponse(messages=[Message("assistant", [Content.from_text(answer)])])

    async def _stream(self, messages):  # noqa: ANN001
        answer = await self._answer(self._text_of(messages))
        yield AgentResponseUpdate(contents=[Content.from_text(answer)], role="assistant")

    def run(self, messages=None, *, stream: bool = False, session=None, **kwargs):  # noqa: ANN001, ARG002
        """A plain method, not a coroutine: the host iterates the result when streaming and awaits it otherwise."""
        if stream:
            return ResponseStream(self._stream(messages), finalizer=AgentResponse.from_updates)
        return self._once(messages)


if __name__ == "__main__":
    # A custom agent keeps its own history (it has none: every request is self-contained).
    ResponsesHostServer(agent=Newsroom(), history_source="agent").run()
