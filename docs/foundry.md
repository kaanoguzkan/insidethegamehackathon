# Microsoft Foundry

MatchMind uses Foundry for four things beyond hosting the model. Each is a command, and each was run against the project
`kaanoguzkan-9930` (Sweden Central, free subscription) in October 2026.

| What | Command / setting | What you see |
|---|---|---|
| **Agents registered in Foundry** | `matchmind foundry-register` | Six versioned prompt agents in the project: `matchmind-editor`, `-explainer`, `-storyteller`, `-localizer`, `-composer`, `-recap-writer` |
| **The Brain calls them** | `MATCHMIND_AGENTS=foundry` (set in `infra/`) | `/health` reports `"agents":"foundry"`; traces show `invoke_agent matchmind-composer` |
| **Evaluations** | `matchmind foundry-evals --samples 30` | A run in the Foundry portal with groundedness, relevance, coherence and fluency per overlay |
| **A hosted agent** | `matchmind foundry-host` | `matchmind-newsroom`, the whole fast path, served by Foundry at the project's agent endpoint |
| **Tracing** | `APPLICATIONINSIGHTS_CONNECTION_STRING` (set in `infra/`, pointed at the project's own resource) | A span for each request, batch, agent run and model call, in the Foundry project's Application Insights |

All of these use the experimental parts of Agent Framework's Foundry package (`to_prompt_agent`, `FoundryAgent`,
`FoundryEvals`, `ResponsesHostServer`); the APIs may change.

## Registered agents

`agents/prompts.py` holds each agent's instructions. `foundry_agents.py` registers them as Foundry *prompt agents*, with
each agent's output schema and temperature inside the definition: a registered agent **refuses** `temperature` and
`response_format` on a call (HTTP 400, "Not allowed when agent is specified"), so `AgentTeam` passes no options to them
(`AgentSettings.agent_side_options`). The prompt version is stored in each version's metadata.

Calling a registered agent costs nothing extra: 2.4 to 3.5 s against 2.7 to 4.4 s for the same prompt sent straight to the
model (three calls each, one laptop, one afternoon). On the live Brain, nine overlays over the three matches were all
model-written (fallback level 0) in 1.8 to 3.2 s.

**Stale prompts are refused.** A registered agent carries its own instructions, so `agents/prompts.py` and Foundry can drift apart. Each registered
version stores the code's `PROMPT_VERSION` in its metadata; at start-up the Brain (`MATCHMIND_AGENTS=foundry`) reads the latest version of each agent and,
if one is missing or its stored version differs, uses local agents instead and says so in `/health` (`"agents": "local (Foundry agents stale or missing: ...)"`).
After any prompt change: bump `PROMPT_VERSION`, run `matchmind foundry-register`, redeploy.

Registered agents bypass the Brain's fault injector (the resilience switch), because the injector wraps the local client.
Run the director demo with `MATCHMIND_AGENTS` unset.

## Evaluations

Our own Verifier checks facts with code. Foundry's built-in evaluators judge what code cannot: whether a text is
grounded in the evidence as a whole, relevant, coherent and fluent in its language.

`foundry_evals.py` samples overlay text from the replay packages (spread over matches and languages), pairs each with its
evidence pack as grounding context, and runs the evaluators in Foundry. The control is the template text of the recorded
outage run.

30 overlays per group, judge `gpt-4.1-mini` (October 2026):

| Text | Groundedness | Relevance | Coherence | Fluency |
|---|---|---|---|---|
| Written by the agent team | 30/30 | 30/30 | 30/30 | 26/30 |
| Template (control) | 30/30 | 30/30 | 30/30 | 24/30 |

Read this carefully:

* The samples come from the **recorded** replay packages, not from the live fast path.
* The judge is the same model family as the writer, which can flatter it. Groundedness is also what the Verifier already
  enforces, so a perfect score there is expected, not a separate finding.
* Four fluency failures in 30 is small, and the template control fails more, so the evaluators are not simply
  rewarding model text. The failing items have not been inspected.

## The hosted agent

`foundry/hosted/main.py` serves the same `serve_beats` function as the Brain's `POST /api/beats`
(`agents/service.py`) as a Foundry **hosted agent**, `matchmind-newsroom`. `matchmind foundry-host` zips `main.py`, the
requirements, the `matchmind` package and the replay packages' `moments.json` and `meta.json` (about 0.3 MB), uploads
a new version and waits until it is active; Foundry builds the dependencies (remote build, Python 3.13).

Call it with the project's agent endpoint, protocol version 2.0.0:

```
POST https://<account>.services.ai.azure.com/api/projects/<project>/agents/matchmind-newsroom/endpoint/protocols/openai/responses
{"input": "{\"match_id\": \"red-card-drama\", \"moment_ids\": [\"red-card-drama-mo-004\"], \"cohorts\": [{\"mode\": \"casual\", \"language\": \"en\"}]}"}
```

The reply is the Brain's answer as JSON text: overlays, the agents that wrote them, a trace and the run statistics.

Measured on the project: status `completed`, model-written English and Spanish overlays, 2.8 and 4.7 s of server time, about
12 to 13 s end to end through Foundry's front door. **The first call to a new session can fail**: it returned
`session_not_ready` after 62 s while the container started, and the next call succeeded. Hosted agents are a good place
for the pipeline to live and be governed; they are not the low-latency path. The 5-second target applies to the Brain.

Things learned the hard way:

* Protocol version must be `2.0.0` (the SDK docstring says `v0.1.1`, which the service rejects at call time).
* The runtime must be `python_3_13` or `python_3_14`.
* A custom agent needs `history_source="agent"`, and `run()` must be a plain method that returns a `ResponseStream` when
  streaming.
* Zip entries need regular-file mode bits (`0o100644`), or Foundry reports "No Python dependency manifest found".
* The container's entry point sits at `/app/main.py`, which has no grandparent directory.

## Tracing

`telemetry.py` starts OpenTelemetry to Application Insights when `APPLICATIONINSIGHTS_CONNECTION_STRING` is set, and
turns on Agent Framework's instrumentation. In Application Insights (`dependencies`): `matchmind.beats` (one per batch,
with the Router, Cache, Repairer, hedge and deadline numbers as attributes), `invoke_agent <name>`,
`chat <model>`, `AgentsOperations.get` (the stale-prompt check), the HTTP call to the Foundry Responses API and the managed-identity token fetch.
Prompts and answers are not recorded unless `MATCHMIND_TRACE_CONTENT=1`.

**Which Application Insights.** A Foundry project is connected to its *own* Application Insights resource, and the portal's tracing view reads that one.
The Bicep first created a second resource (`appi-matchmind`) and the Brain exported there, so nothing showed in Foundry. The Brain now exports to the
project's resource: `azd env set APPINSIGHTS_CONNECTION_STRING_OVERRIDE <its connection string>` (see [running-on-azure.md](running-on-azure.md)). To
look at the last hour in Logs: `dependencies | where timestamp > ago(1h) | summarize count() by name`.

## What is not done

* Foundry's red-teaming and scheduled evaluations, content-safety (RAI) policy on the agents, and Foundry IQ / memory.
* The web app does not call the hosted agent; it calls the Brain.
* The evaluation of live fast-path output (only recorded text is evaluated so far).
* The shared beat cache and the Brain's guards are not Foundry features; they are described in [running-on-azure.md](running-on-azure.md).
