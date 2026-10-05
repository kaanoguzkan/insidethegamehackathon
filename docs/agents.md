# The agent team

All agents are Microsoft Agent Framework `Agent`s (`agents/team.py`) with typed JSON output validated by
pydantic. They never call each other; they coordinate through the moment store (a Cosmos DB container in
Azure, a dict locally), which also keeps a per-agent trace.

| Agent | Job | Output |
|---|---|---|
| **Editor** | Decides which candidate moments become story beats within a rolling budget (3 per 10 minutes); goals, red cards and penalties are always kept | beat choices with priority and storyline |
| **Explainer** | Explains why a moment matters: what changed, the mechanism, what it means, claims each citing evidence keys, caveats for contradicting metrics | `Explanation` |
| **Verifier** | Code, not a model: numbers, names, citations, honesty, policy, language, format | pass, or an error list for the retry |
| **Storyteller** | English variants per audience (analyst, casual, club side, followed player) | `StoryOut` |
| **Localizer** | Native Spanish or Turkish versions, numbers unchanged | `StoryVariant` |
| **Recap Writer** | Preview, half-time and full-time recaps from a recap evidence pack | `Recap` |
| **Overlay Producer** | Code: timing, lanes, collisions | overlays |

## Workflow (`agents/workflow.py`)

`WorkflowBuilder` graph: Editor to Explainer to Verifier, then Storyteller to Localizer to Verifier to
Producer, with a retry loop at each Verifier (one retry, told exactly what to fix) and a template tier
reachable from any step. Rules: messages are immutable; edge conditions are mutually exclusive; every step
has a deadline; a failure, timeout or failed check degrades that beat (or only the failing cohorts) to
verified templates.

`fallbackLevel` on every overlay: 0 first-time agent text, 1 after a retry, 2 template, 3 stat graphic.

## Model backends (`agents/llm.py`)

Select with `MATCHMIND_LLM`:

* `offline` (default): a deterministic client that answers from the template engine. Free, instant, and
  what tests and the replay build use. A fault injector can make it fail, stall or hallucinate.
* `openai`: any OpenAI-compatible endpoint. Set `MATCHMIND_LLM_MODEL`, `MATCHMIND_LLM_BASE_URL`,
  `MATCHMIND_LLM_API_KEY` (GitHub Models `https://models.github.ai/inference`; Ollama
  `http://localhost:11434/v1`). Install the extra: `uv sync --extra openai`.
* `foundry`: a Microsoft Foundry project. Set `FOUNDRY_PROJECT_ENDPOINT` and `MATCHMIND_LLM_MODEL`;
  authenticates with `DefaultAzureCredential`. Install: `uv sync --extra foundry`.

The real-model paths are wired but have **not** been run against a live model; prompts are versioned in
`agents/prompts.py` (`PROMPT_VERSION`) and recorded in each overlay's provenance.

## The Verifier

Checks, all deterministic: every number must be licensed by the pack (rounded as written, whole-number
tokens matching whole-number evidence), including minute labels, scores, window lengths, percentages of
share metrics and written-out counts in three languages; every player or club mentioned must belong to the
moment; claims with numbers must cite real evidence keys; a claim resting on a metric that moved against
the story must say so; no betting, alcohol, drugs, tobacco, politics, insults or medical speculation; the
text must be in the requested language; length limits by mode. Tests include adversarial cases for each.
