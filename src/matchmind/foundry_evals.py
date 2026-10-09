"""Microsoft Foundry evaluations of the overlay text the agents wrote.

Our own Verifier checks facts deterministically (every number, name and reference). Foundry's built-in evaluators
judge what code cannot: whether the text is *grounded* in the evidence as a whole, *relevant* to the moment,
*coherent* and *fluent* in the viewer's language. Running both gives two independent views of the same text.

The samples come from the replay packages: overlays written by the agent team, and, as a control, the template
overlays for the same kind of moment. Each item carries the evidence pack as grounding context. The run appears in
the Foundry portal; this module also returns the scores so they can be written into the docs.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from .core.paths import replays_dir

LANGUAGES = {"en": "English", "es": "Spanish", "tr": "Turkish"}
DEFAULT_EVALUATORS = ("groundedness", "relevance", "coherence", "fluency")
NARRATIVE = "lower_third"


def evidence_text(pack: dict, limit: int = 900) -> str:
    """The evidence pack as plain text: what a viewer's text may rest on."""
    names = pack.get("teamNames", {})
    parts = [f"Moment: {pack.get('type')} at {pack.get('detectedAt', {}).get('label')}, for {names.get(pack.get('subjectTeam'), pack.get('subjectTeam'))}."]
    facts = {k: v for k, v in pack.get("facts", {}).items() if v not in (None, "", [], {})}
    if facts:
        parts.append("Facts: " + json.dumps(facts, ensure_ascii=False, default=str))
    for key, m in list(pack.get("metrics", {}).items())[:8]:
        before, after = m.get("before"), m.get("after")
        parts.append(f"{key}: {before} -> {after}" if before is not None else f"{key}: {m.get('value')}")
    parts.append("Players: " + ", ".join(p["name"] for p in pack.get("players", [])))
    return " ".join(parts)[:limit]


def _query(overlay: dict, pack: dict) -> str:
    c = overlay["cohort"]
    lang = LANGUAGES.get(c["language"], c["language"])
    return f"Write a short {c['mode']} broadcast graphic in {lang} for this {pack.get('type')} moment ({pack.get('detectedAt', {}).get('label')}). Use only the evidence."


def sample(root: Path | None = None, per_group: int = 12) -> dict[str, list[dict[str, Any]]]:
    """Up to ``per_group`` samples of agent-written and of template overlay text, spread over matches and languages."""
    root = root or replays_dir()
    groups: dict[str, dict[tuple, list[dict]]] = {"agent": defaultdict(list), "template": defaultdict(list)}
    for d in sorted(p for p in root.iterdir() if (p / "overlays.json").exists()):
        packs = {m["id"]: m for m in json.loads((d / "moments.json").read_text())}
        # Agent-written text is in the healthy run; the outage run is all template text, the control.
        for kind, name in (("agent", "overlays.json"), ("template", "overlays.outage.json")):
            if not (d / name).exists():
                continue
            for o in json.loads((d / name).read_text()):
                pack = packs.get(o.get("momentId") or "")
                if o["kind"] != NARRATIVE or pack is None or not o["content"]["body"]:
                    continue
                if (kind == "agent") != str(o["provenance"].get("model", "")).startswith("agent-team"):
                    continue
                groups[kind][(d.name, o["cohort"]["language"])].append(
                    {"id": o["id"], "query": _query(o, pack), "response": f"{o['content']['headline']}. {o['content']['body']}", "context": evidence_text(pack),
                     "language": o["cohort"]["language"], "match": d.name}
                )
    out: dict[str, list[dict]] = {}
    for kind, buckets in groups.items():
        picked: list[dict] = []
        queues = [sorted(v, key=lambda x: x["id"]) for _, v in sorted(buckets.items())]
        while queues and len(picked) < per_group:  # round robin, so every match and language is represented
            for q in list(queues):
                if q and len(picked) < per_group:
                    picked.append(q.pop(0))
                if not q:
                    queues.remove(q)
        out[kind] = picked
    return out


async def run(per_group: int = 12, evaluators: tuple[str, ...] = DEFAULT_EVALUATORS, model: str | None = None, root: Path | None = None) -> dict[str, Any]:
    """Evaluate both groups in Foundry and return their per-evaluator results and portal links."""
    from agent_framework import Content, Message
    from agent_framework._evaluation import EvalItem
    from agent_framework.foundry import FoundryChatClient, FoundryEvals
    from azure.identity import DefaultAzureCredential

    model = model or os.environ.get("MATCHMIND_LLM_MODEL", "gpt-4.1-mini")
    client = FoundryChatClient(project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"], model=model, credential=DefaultAzureCredential())
    results: dict[str, Any] = {"model": model, "evaluators": list(evaluators), "groups": {}}
    for kind, items in sample(root, per_group).items():
        if not items:
            continue
        evals = FoundryEvals(client=client, model=model, evaluators=list(evaluators))
        eval_items = [
            EvalItem(conversation=[Message("user", [Content.from_text(i["query"])]), Message("assistant", [Content.from_text(i["response"])])], context=i["context"])
            for i in items
        ]
        res = await evals.evaluate(eval_items, eval_name=f"MatchMind overlays: {kind}-written text")
        results["groups"][kind] = {
            "samples": len(items), "status": res.status, "report_url": res.report_url, "result_counts": res.result_counts,
            "per_evaluator": res.per_evaluator, "error": res.error,
        }
    return results
