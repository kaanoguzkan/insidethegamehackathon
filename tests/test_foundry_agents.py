"""Registered Foundry agents must not be used when their stored prompts are out of date."""

from __future__ import annotations

from matchmind.agents import prompts
from matchmind.foundry_agents import SPECS, stale_agents


class FakeAgents:
    def __init__(self, registered: dict[str, str | None], missing: set[str] = frozenset()) -> None:
        self.registered, self.missing = registered, set(missing)

    def get(self, agent_name: str) -> dict:
        if agent_name in self.missing:
            raise RuntimeError("404 not found")
        return {"versions": {"latest": {"metadata": {"promptVersion": self.registered.get(agent_name)}}}}


class FakeProject:
    def __init__(self, **kw) -> None:  # noqa: ANN003
        self.agents = FakeAgents(**kw)


def test_agents_registered_with_the_current_prompt_version_are_fine():
    assert stale_agents(FakeProject(registered={sp.name: prompts.PROMPT_VERSION for sp in SPECS})) == []


def test_an_agent_registered_with_an_older_prompt_version_is_reported():
    reg = {sp.name: prompts.PROMPT_VERSION for sp in SPECS}
    reg["matchmind-composer"] = "2026-01-01.1"
    out = stale_agents(FakeProject(registered=reg))
    assert len(out) == 1 and out[0].startswith("matchmind-composer") and "2026-01-01.1" in out[0]


def test_a_missing_or_unreadable_agent_counts_as_stale():
    reg = {sp.name: prompts.PROMPT_VERSION for sp in SPECS}
    out = stale_agents(FakeProject(registered=reg, missing={"matchmind-editor"}))
    assert [o.split(" ")[0] for o in out] == ["matchmind-editor"]
    assert len(stale_agents(FakeProject(registered={}))) == len(SPECS)
