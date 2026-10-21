# Configuration

Everything is an environment variable. Nothing is required: with none set, MatchMind runs offline on the template engine with no keys and no network.
On Azure the Bicep sets the Brain's variables from `azd env` values (names in the last column).

## The model

| Variable | Default | Effect | azd env |
|---|---|---|---|
| `MATCHMIND_LLM` | `offline` | `offline` (template engine), `openai` (any OpenAI-compatible endpoint) or `foundry` (Microsoft Foundry) | set by Bicep from `FOUNDRY_PROJECT_ENDPOINT` |
| `MATCHMIND_LLM_MODEL` | none | The model or Foundry deployment name. A name starting `gpt-5`, `gpt-6` or `o<digit>` is treated as a **reasoning model** (no temperature, 4 000 output tokens, 60 s per call, low reasoning effort); a name that does not start `gpt-` or `o<digit>` gets the JSON schema in the prompt instead of strict structured output | `MATCHMIND_LLM_MODEL` |
| `FOUNDRY_PROJECT_ENDPOINT` | none | `https://<account>.services.ai.azure.com/api/projects/<project>`; authenticates with `DefaultAzureCredential` (managed identity on Azure, `az login` locally) | `FOUNDRY_PROJECT_ENDPOINT` |
| `MATCHMIND_LLM_BASE_URL`, `MATCHMIND_LLM_API_KEY` | none | For `openai`: the endpoint (GitHub Models, Ollama, Azure OpenAI v1) and its key | |
| `MATCHMIND_AGENTS` | local | `foundry`: the Brain calls the agents registered in Foundry (`matchmind foundry-register`) instead of local ones built from the same prompts. At start-up it checks each registered agent's prompt version and falls back to local agents, reporting it in `/health`, if one is stale | `MATCHMIND_AGENTS` |
| `MATCHMIND_AGENT_TIMEOUT_S` | 8 (60 reasoning) | Longest a single model call may take; in fast mode never more than the request has left | set to 30 by Bicep |
| `MATCHMIND_MAX_TOKENS` | 700 (4 000 reasoning) | Output cap per call | |
| `MATCHMIND_BEAT_BUDGET_S` | 15 (300 reasoning), at most 90 | Time one beat has in the five-agent workflow (`mode: full`) | set to 90 by Bicep |
| `MATCHMIND_REASONING_EFFORT` | `low` for reasoning models | `none`, `minimal`, `low`, `medium`, `high` | |
| `MATCHMIND_STRUCTURED_OUTPUT` | on for `gpt-*` and `o*` | `0` puts the JSON schema in the prompt and tolerates a markdown fence around the answer | |

## The live path

| Variable | Default | Effect |
|---|---|---|
| `MATCHMIND_HEDGE_S` | 4 | After this many seconds a second identical model call starts and the first answer wins; `0` turns hedging off. Measured with `gpt-6-luna`: a call has a median of about 3 s and a 90th percentile of about 4.4 s |
| `MATCHMIND_SHARED_CACHE` | off | `1` keeps verified model text in Cosmos DB too (needs `COSMOS_ENDPOINT` and the `cosmos` extra); set to `1` by Bicep |
| `COSMOS_ENDPOINT` | none | The Cosmos DB account; identity only, database `matchmind`, container `beats` |
| `MATCHMIND_PRELOAD`, `MATCHMIND_PRELOAD_DELAY_S` | off, 10 | `1` loads every match's interpreter in the background after start-up so the first MCP call is not a 20 s simulation; set to `1` by Bicep |

## Protecting the API

| Variable | Default | Effect |
|---|---|---|
| `MATCHMIND_ADMIN_KEY` | none (open) | When set, `mode: full`, `useCache: false` and `deadlineMs` over 10 000 need `x-admin-key`. A Container Apps secret on Azure |
| `MATCHMIND_BEATS_PER_MIN` | 20 | `POST /api/beats` requests a minute per client |
| `MATCHMIND_MCP_PER_MIN` | 60 | `/mcp` requests a minute per client |
| `MATCHMIND_MAX_INFLIGHT` | 8 | `/api/beats` requests served at once; more get 503 |
| `MATCHMIND_ASK_PER_MIN`, `MATCHMIND_MAX_ASK_INFLIGHT` | 10, 4 | `POST /api/ask` questions a minute per client, and questions answered at once |
| `MATCHMIND_CORS_ORIGINS` | none | Extra browser origins that may call the API (comma separated, no trailing slash); `localhost` dev servers and `MATCHMIND_ALLOWED_ORIGINS` are always allowed |
| `MATCHMIND_ALLOWED_HOSTS`, `MATCHMIND_ALLOWED_ORIGINS` | none | The MCP library's DNS-rebinding guard: the host names the service answers to and the browser origins it accepts. Without hosts it accepts only localhost |
| `MATCHMIND_DIRECTOR`, `MATCHMIND_DIRECTOR_KEY` | off | `1` exposes the model-fault switch of the resilience demo; the key, if set, must be sent as `X-Director-Key` |

## The live pipeline

| Variable | Default | Effect |
|---|---|---|
| `LIVE_JOB_ID` | none | The simulator job's resource id; with it the Brain's `POST /api/live/start` starts that job through Azure Resource Manager (set by Bicep) |
| `SEASON_JOB_ID` | none | The season job's resource id; with it `POST /api/season/simulate` starts that job (5 replicas) through Azure Resource Manager (set by Bicep). Without it, and with `MATCHMIND_LIVE_LOCAL=1`, the Brain simulates in threads of its own process |
| `SEASON_ID`, `SEASON_SEED` | none, 1 | Read by the season job (the Brain sets `SEASON_ID` for each run) |
| `LIVE_PUSH_URL` | none | The Function app's `/api` address, where browsers negotiate a SignalR connection; the Brain reports it in `GET /api/live/config` (set by Bicep). Without it the page polls |
| `LIVE_DELAY_S` | 25 | How far behind the live feed viewers watch, in wall seconds |
| `STORAGE_ACCOUNT` | none | The storage account of the tracking chunks (`frames`) and the workers' checkpoints (`checkpoints`); the job, the Function app and the Brain read it (identity, no keys). Without it chunks stay in memory |
| `LIVE_SPEED` | 5 | Match seconds per real second (the Brain passes it to the job; the job reads it too) |
| `LIVE_SCENARIO`, `LIVE_FROM_MINUTE`, `LIVE_MATCH_ID` | a demo id from `data/demos.json`, 0, generated | Read by the simulator job; the Brain sets them for each run |
| `MATCHMIND_LIVE_KEY` | none | Shared secret between the dispatcher Function and the Brain's `/api/live/{id}/beats` (`x-live-key`); it also signs the workers' checkpoints (without it there are no checkpoints). Set on both; a Container Apps secret on the Brain. `azd env set MATCHMIND_LIVE_KEY ...` |
| `MATCHMIND_LIVE_OPEN` | off | `1` lets `/api/live/{id}/beats` be called without a key (development only; the endpoint otherwise fails closed) |
| `MATCHMIND_LIVE_LOCAL` | off | `1` lets the Brain start the simulator in a thread of its own process when no job is configured (a laptop) |
| `MATCHMIND_LIVE_START_PER_MIN`, `MATCHMIND_LIVE_POLL_PER_MIN` | 3, 240 | Per-client limits on `POST /api/live/start` and on the live read endpoints |
| `MATCHMIND_STREAM_START_PER_MIN`, `MATCHMIND_STREAM_POLL_PER_MIN` | 6, 900 | Per-client limits on `POST /api/stream` and on the GETs under `/api/stream` (a viewer polls the feed about once a second and fetches a tracking chunk every few seconds) |
| `COSMOS_ENDPOINT` | none | Also the live store: containers `matches`, `events`, `moments`, `overlays`, `state`. Without it the live store is in memory |
| Function app: `COSMOS__*`, `AzureSignalRConnectionString__*`, `AzureWebJobsStorage__*`, `STORAGE_ACCOUNT`, `COSMOS_ENDPOINT`, `BRAIN_URL`, `MATCHMIND_LIVE_KEY`, `AZURE_CLIENT_ID` | set by Bicep | The triggers' and bindings' connections (identity, no keys: `__serviceUri` / `__accountEndpoint` / `__accountName`, `__credential=managedidentity`, `__clientId`), the stores, the Brain's address and the shared key |

## Cost reporting

| Variable | Default | Effect |
|---|---|---|
| `MATCHMIND_PRICE_IN_PER_M`, `MATCHMIND_PRICE_OUT_PER_M` | the list price of the model named by `MATCHMIND_LLM_MODEL` (`pricing.py`; unknown models are costed at the `gpt-4.1-mini` rate) | US dollars per million input and output tokens. They only feed the `costUsd` that `/api/ask` and `/api/beats` report; set them to the list price of whatever model you deploy (see `pricing.py`) |

## Telemetry

| Variable | Default | Effect |
|---|---|---|
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | none (off) | Turns on OpenTelemetry export to Application Insights. Point it at the Foundry project's own resource to see traces in the Foundry portal; on Azure set it through `APPINSIGHTS_CONNECTION_STRING_OVERRIDE` |
| `MATCHMIND_TRACE_CONTENT` | off | `1` also records prompts and answers in the traces |

## Data and the web app

| Variable | Default | Effect |
|---|---|---|
| `MATCHMIND_DATA` | the repo's `data/` | Where the league, the demo list and the replay packages live (`/app/data` in the image) |
| `VITE_BRAIN_URL` | none | Build time, web app: the Brain's address. With none, the Live AI switch does not appear. `azd deploy` builds with the Brain's address as `BRAIN_URI`; the Pages workflow uses the repository variable `BRAIN_URL` |
| `PORT` | 8088 | The Foundry hosted agent's port (set by the platform) |

## azd-only values (infrastructure)

`AZURE_LOCATION`, `APPS_LOCATION`, `WEB_LOCATION`, `BUDGET_CONTACT`, `MATCHMIND_ADMIN_KEY`, `APPINSIGHTS_CONNECTION_STRING_OVERRIDE`, `MATCHMIND_CORS_ORIGINS`,
`MATCHMIND_AGENTS`, `FOUNDRY_PROJECT_ENDPOINT`, `MATCHMIND_LLM_MODEL` are read by `infra/main.parameters.json`. `azd env get-values` lists what is set;
the admin key and the connection string are secrets and are not committed (`.azure/` is ignored). See [running-on-azure.md](running-on-azure.md).

## Optional dependencies

`uv sync --extra <name>`: `brain` (FastAPI, uvicorn), `openai`, `foundry` (Agent Framework's Foundry client, azure-identity), `telemetry`
(azure-monitor-opentelemetry), `cosmos` (azure-cosmos), `azure` (all Azure adapters), `report` (PDF). The container image installs
`brain`, `openai`, `foundry`, `telemetry` and `cosmos`.
