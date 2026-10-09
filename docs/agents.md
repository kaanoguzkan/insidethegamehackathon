# The agent team

The model-backed agents are Microsoft Agent Framework `Agent`s (`agents/team.py`) with typed JSON output validated by
pydantic; the others are plain code. They never call each other; they coordinate through the moment store (an in-memory dict that
also keeps a per-agent trace; the Brain reports the trace in every answer). A Cosmos DB-backed store is not built: Cosmos holds the
shared beat cache, below.

| Agent | Job | Output |
|---|---|---|
| **Editor** | Decides which candidate moments become story beats within a rolling budget (3 per 10 minutes); goals, red cards and penalties are always kept | beat choices with priority and storyline |
| **Explainer** | Explains why a moment matters: what changed, the mechanism, what it means, claims each citing evidence keys, caveats for contradicting metrics | `Explanation` |
| **Verifier** | Code, not a model: numbers, names, citations, honesty, policy, language, format | pass, or an error list for the retry |
| **Storyteller** | English variants per audience (analyst, casual, club side, followed player) | `StoryOut` |
| **Localizer** | Native Spanish or Turkish versions, numbers unchanged | `StoryVariant` |
| **Composer** | The fast path's one call: explains and writes a single cohort's story, natively in its language | `StoryVariant` |
| **Recap Writer** | Preview, half-time and full-time recaps from a recap evidence pack | `Recap` |
| **Router, Cache, Repairer** | Rules, no model: who gets a model call, what has been written before, how to mend rejected text (fast path, below) | |
| **Overlay Producer** | Code: timing, lanes, collisions | overlays |

## Workflow (`agents/workflow.py`)

`WorkflowBuilder` graph: Editor to Explainer to Verifier, then Storyteller to Localizer to Verifier to
Producer, with a retry loop at each Verifier (one retry, told exactly what to fix) and a template tier
reachable from any step. Rules: messages are immutable; edge conditions are mutually exclusive; every step
has a deadline; a failure, timeout or failed check degrades that beat (or only the failing cohorts) to
verified templates.

`fallbackLevel` on every overlay: 0 first-time agent text, 1 after a retry (or mended by the Repairer in the fast path), 2 template, 3 stat graphic.

## Model backends (`agents/llm.py`)

Select with `MATCHMIND_LLM`:

* `offline` (default): a deterministic client that answers from the template engine. Free, instant, and
  what tests and the replay build use. A fault injector can make it fail, stall or hallucinate.
* `openai`: any OpenAI-compatible endpoint. Set `MATCHMIND_LLM_MODEL`, `MATCHMIND_LLM_BASE_URL`,
  `MATCHMIND_LLM_API_KEY` (GitHub Models `https://models.github.ai/inference`; Ollama
  `http://localhost:11434/v1`). Install the extra: `uv sync --extra openai`.
* `foundry`: a Microsoft Foundry project. Set `FOUNDRY_PROJECT_ENDPOINT` and `MATCHMIND_LLM_MODEL`;
  authenticates with `DefaultAzureCredential`. Install: `uv sync --extra foundry`.

The `foundry` backend has been run against a live Foundry project (`gpt-4.1-mini` on Azure, Oct 2026); prompts are
versioned in `agents/prompts.py` (`PROMPT_VERSION`) and recorded in each overlay's provenance. Settings that depend on the model
(reasoning models refuse a temperature and need a bigger token cap; models that do not enforce a JSON schema get it in the prompt)
are chosen from the model's name; see [configuration.md](configuration.md).

**Which model.** Tried through Foundry on a free subscription for the fast path, with the same prompts and the same verifier:
`gpt-4.1-mini` is the one in use (median request 2.6 s, 43 of 45 overlays model-written). `gpt-5-mini` (a reasoning model) took 96 s for
three moments through the five-agent chain; Phi-4 (open weights) generates at about 25 tokens a second and took 50 s for the same chain;
Phi-4-mini-instruct never answered inside five seconds; `gpt-5-nano` and `gpt-4.1-nano` were no faster in practice and failed the verifier more
often. Mistral, Llama and Cohere models cannot be bought on a free subscription (Marketplace). Latency of a shared endpoint varies by a second or
more between calls, which is why the fast path has a hard deadline, templates and a hedged second call. `Microsoft-Decision-1` is in the catalog
but is not a chat model (`chatCompletion: false`) and has not been tried.

## Foundry

The same agents can run as agents registered in a Foundry project (`MATCHMIND_AGENTS=foundry`), and the fast path is also served
as a Foundry hosted agent. See [foundry.md](foundry.md).

## The fast path (`agents/fast.py`)

`POST /api/beats` defaults to `mode: "fast"`, which answers inside `deadlineMs` (5 s). The five-call workflow above
takes tens of seconds with a real model, so the fast path uses one model call per moment and cohort, in parallel, and
surrounds it with agents that need no model at all:

| Agent | Kind | Job |
|---|---|---|
| Editor | rules | picks the moments that become beats (`offline_edit`) |
| Router | rules | sends beats to the model, stat graphics and tickers to templates, and caps the calls per request |
| Cache | rules | returns verified model text for a repeated request, keyed by match, moment, cohort, model and prompt version |
| Composer | model | one call: explains and writes the story for one cohort, natively in its language |
| Verifier | code | the same deterministic checks as everywhere else |
| Repairer | rules | cuts failing sentences, headlines and claims out of rejected text and re-verifies; the result is level 1 |
| Template | rules | the answer that is always ready: rendered first, kept for anything late, failed or unrepairable |
| Producer | code | builds the timed overlay JSON |

Each agent leaves an entry in the beat's `trace`, and every overlay's `provenance.agents` lists who made it
(for example `editor, router, composer, verifier, repairer`, or `editor, router, cache, composer, verifier` for a cached one).
The response carries `stats` (cache hits, model calls, hedged, repaired, rejected, calls past the deadline).

**Router** (`agents/router.py`). Only moments the Editor kept as beats go to the model; stat-graphic cohorts (`mode: any`) and tickers get
templates; at most 18 model calls a request, most important moments first.

**Cache** (`agents/cache.py`). Verified model text only, never a template. Memory in front (LRU, 2 048 entries, one hour), Cosmos DB behind
(`beats`, seven days, shared by replicas and kept across restarts). Keyed by match, moment, cohort, model and prompt version. Every Cosmos call
is time-boxed (0.6 s) and any error is a miss; the connection is opened at start-up with a generous limit because the first call needs an
identity token and account discovery. `/health` reports `sharedCache`.

**Repairer** (`agents/repair.py`). It only removes: a failing sentence is dropped, a failing headline is replaced by the template's, a failing claim
is dropped, an over-long body loses its last sentences, and the result must pass the Verifier again. It never adds a word, so it cannot introduce a
fact. A text in the wrong language is not repairable. A mended text is level 1.

**Hedging** (`MATCHMIND_HEDGE_S`, 3.2 s). If the first call is slower than that, a second identical call starts and the first answer wins. At 2.2 s,
about half of all calls were duplicated; at 3.2 s, 16%.

### Measured on the deployed Brain

15 uncached requests of three cohorts (English casual, Spanish analyst, Turkish casual), `gpt-4.1-mini` through registered Foundry agents, Oct 2026:

| | |
|---|---|
| Model calls | 45; 7 hedged (16%); 0 passed the deadline |
| Request time | median 2.6 s, 95th percentile 4.2 s, maximum 4.7 s |
| Narrative overlays | 45: 43 written by the model and verified first time, 1 mended by the Repairer, 1 fell back to a template |
| A repeated request | 2 ms from memory; about 280 ms from Cosmos DB on a freshly started replica |

This is one afternoon and one model. Shared-endpoint latency varies, and an earlier run of the same code on a slow afternoon had 5 to 9 of 24 overlays
fall back to templates when calls crept past four seconds; the answer was still on time, just written by the template. What the Verifier refused in
the first live runs, and what fixed it: the model cited evidence keys that do not exist (the prompt now carries the exact list of valid references),
it wrote player ids such as `NOR-21` into the text so their digits failed the number check (the model now sees names, never ids), and a few
sentences used words the policy bans.

## The Verifier

Checks, all deterministic: every number must be licensed by the pack (rounded as written, whole-number
tokens matching whole-number evidence), including minute labels, scores, window lengths, percentages of
share metrics and written-out counts in three languages; every player or club mentioned must belong to the
moment; claims with numbers must cite real evidence keys; a claim resting on a metric that moved against
the story must say so; no betting, alcohol, drugs, tobacco, politics, insults or medical speculation; the
text must be in the requested language; length limits by mode. Tests include adversarial cases for each.
