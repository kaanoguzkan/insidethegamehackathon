# Running on Azure

**Status: deployed and verified on a free subscription (October 2026).** `azd up` provisions everything below into one resource group
(`rg-matchmind`); the Brain and the web app were then deployed with `azd deploy`.

## What is deployed

| Resource | Region | What uses it |
|---|---|---|
| Container App `ca-matchmind-brain` (2 vCPU, 4 GiB, one always-on replica: live matches are held in the replica's memory, capped at twelve) | North Europe | The Brain: REST, MCP, both agent paths |
| Availability test `ready-matchmind`, action group, four metric alerts (readiness, 5xx, CPU, restarts) | Sweden Central / global | Monitoring of the Brain; see [enterprise.md](enterprise.md). Mail goes to `BUDGET_CONTACT` when set |
| Static Web App `swa-matchmind` | East US 2 | The match center, built with the Brain's address (`BRAIN_URI`) |
| Microsoft Foundry account and project `kaanoguzkan-9930` | Sweden Central | The models (`gpt-6-luna` in use, `gpt-4.1-mini` kept as a fallback deployment, 120 000 tokens a minute for the latter), eight registered prompt agents, the hosted agent `matchmind-newsroom`, evaluations |
| Cosmos DB (free tier), database `matchmind` | Sweden Central | `beats`: the Brain's shared cache of verified model text (7-day expiry). `matches`, `events`, `moments`, `overlays`, `state`, `leases`: the live pipeline. `season`: the season's fixtures and results. Identity only, no keys |
| Application Insights, Log Analytics (30 days, 0.5 GB a day cap) | Sweden Central | Traces and logs. The Brain exports to the **Foundry project's own** Application Insights so traces show in the Foundry portal |
| Container Registry (Basic), user-assigned managed identity | Sweden Central | The Brain image; the identity pulls it and calls Cosmos, Storage and the model |
| Container Apps Job `caj-matchmind-season` (1 vCPU, 2 GiB, 5 parallel replicas, manual trigger) | North Europe | Simulates a season: each replica claims fixtures, simulates them and stores their match packs until none is left (`python -m matchmind.live.season_job`, the Brain's image). The Brain starts it |
| Container Apps Job `caj-matchmind-sim` (1 vCPU, 2 GiB, manual trigger) | North Europe | Plays a demo match as a feed (`python -m matchmind.live.simulator`); a Live match on the **Live** page is played inside the Brain instead, one per viewer |
| Function App `func-matchmind-<id>` (Flex Consumption, Python 3.12, at most 2 instances) | North Europe | `analyze` (Event Grid), `interpret`, `dispatch`, `push_overlays`, `push_moments`, `push_events` (Cosmos DB change feeds), `negotiate` (SignalR), `sweep` (timer) ([live-pipeline.md](live-pipeline.md)) |
| Event Grid system topic on the storage account, subscription `analyze-chunks` | Sweden Central | Routes `BlobCreated` events of the `frames` container to the `analyze` Function (the subscription is created by the postdeploy hook, after the Function exists) |
| Storage account | Sweden Central | Containers `packs` (a simulated match each, about 2 MB, 60 MB a season), `frames` (tracking chunks), `checkpoints` (the workers' signed checkpoints), `deployments` (the Functions package) and the Functions host's own state, through the managed identity; no keys |
| SignalR (Free, serverless mode, Entra authentication only) | Sweden Central | Pushes overlays, moments and events to the Live page ([live-pipeline.md](live-pipeline.md)) |
| Key Vault | Sweden Central | **Provisioned, not used by the app** |
| Consumption budget | subscription | Alerts at 25%, 50% and 90% of $20 a month |

## What was verified, and how

| Piece | Evidence |
|---|---|
| `infra/*.bicep` | `az bicep build` clean; `azd provision` repeatedly (it is incremental) |
| Brain image | Built locally for `linux/amd64`, pushed, running; non-root user |
| Live model | Real `POST /api/beats` calls against `gpt-6-luna` through registered Foundry agents: median 2.8 s, 90th percentile 3.8 s ([agents.md](agents.md)) |
| Live pipeline | A match started from the web page's button, played through the job, both Functions and the Brain: 13 moments, 91 of 104 story overlays model-written, median 19.8 s from detection to stored overlay ([live-pipeline.md](live-pipeline.md)) |
| Cold start | A scaled-to-zero Brain answers its first request after about 20 s; the page waits for `/health` first |
| Rate limit, admin key, headers | Exercised with `curl` against the live Brain (403 without the key, 429 after 20 requests a minute) |
| Shared cache | A request cached before a restart was served by the fresh replica from Cosmos DB in 282 ms with no model call |
| Event-loop stalls | A cold MCP call no longer freezes `/health` (0.3 s during it, 20.8 s before) |
| Traces | `matchmind.beats`, agent and model spans in the Foundry project's Application Insights |
| `.github/workflows/*` | `actionlint`-clean and covered by a test; CI and the Pages mirror run on GitHub |

## First deploy

```bash
azd auth login
azd env new matchmind && azd env set AZURE_LOCATION swedencentral   # any region open to your subscription; try azd provision --preview first
azd env set BUDGET_CONTACT you@example.com    # alerts at 25%, 50% and 90% of a $20 monthly budget
azd env set MATCHMIND_ADMIN_KEY "$(python3 -c 'import secrets; print(secrets.token_hex(24))')"   # operator key, stored as a Container Apps secret
azd up                                         # first pass: everything except the model
```

Then the Foundry side (a project and a model deployment from the portal or `az cognitiveservices account deployment create`):

```bash
azd env set FOUNDRY_PROJECT_ENDPOINT https://<account>.services.ai.azure.com/api/projects/<project>
azd env set MATCHMIND_LLM_MODEL <deployment-name>
# The Brain's identity needs the "Foundry User" role on the Foundry account (role id 53ca6127-db72-4b80-b1b0-d745d6d5456d):
az role assignment create --assignee-object-id <principalId of id-matchmind> --assignee-principal-type ServicePrincipal \
   --role 53ca6127-db72-4b80-b1b0-d745d6d5456d --scope <Foundry account resource id>
uv run matchmind foundry-register              # the eight agents, with their prompt version in the metadata
azd env set MATCHMIND_AGENTS foundry           # the Brain calls the registered agents (falls back to local ones if they are stale)
azd env set APPINSIGHTS_CONNECTION_STRING_OVERRIDE "$(az monitor app-insights component show --app <project>-appinsights -g <rg> --query connectionString -o tsv)"
azd env set MATCHMIND_CORS_ORIGINS https://<your-pages-origin>     # other sites that call the Brain from a browser
azd provision && azd deploy
```

The Static Web App has its own region (`WEB_LOCATION`, default `eastus2`): it only exists in a few regions and is served from a CDN, so it does not need to match. Some new subscriptions are refused in popular regions (West Europe returned `locationineligible` for one); pick another region for `AZURE_LOCATION`.

If the Container Apps environment fails with `ManagedEnvironmentNoAvailableCapacityInRegion`, keep the data where it is and put only the apps elsewhere: `azd env set APPS_LOCATION northeurope` (any region with capacity) and run `azd up` again.

Locally built image: ACR cloud builds (Tasks) are refused on new subscriptions (`TasksOperationsNotAllowed`), so `azure.yaml` builds the Brain image on your machine (**Docker must be running**) for `linux/amd64`. The Dockerfile builds from Astral's Python image on `ghcr.io`, because Docker Hub's token service timed out and rate-limited builds.

The Brain's MCP endpoint (`/mcp/`) refuses any Host header the library does not know (421), so the Bicep sets `MATCHMIND_ALLOWED_HOSTS` to the app's public name.

Without a Foundry endpoint the Brain keeps the offline model. `azd down --purge` removes everything.

## Things that went wrong on a free subscription

| Symptom | Cause and fix |
|---|---|
| `Marketplace Subscription purchase eligibility check failed ... free subscription` when deploying Mistral, Llama or Cohere | Partner models are sold through the Marketplace and cannot be bought on a free subscription. Use OpenAI, Phi (Microsoft) or `gpt-oss` models. |
| `Role 'Azure AI User' doesn't exist` | The role is now called **Foundry User**; use its id `53ca6127-db72-4b80-b1b0-d745d6d5456d`. |
| `InsufficientQuota` on a model deployment | Capacity is in thousands of tokens a minute and quota is per model and SKU (`az cognitiveservices usage list -l <region>`). Ask for less. |
| `ServiceModelDeprecating` | The model is retiring and cannot be newly deployed (`gpt-4o-mini` here). |
| Hosted agent: `Unsupported runtime 'python_3_12'` | Hosted agents run Python 3.13 or 3.14; the protocol version must be `2.0.0` ([foundry.md](foundry.md)). |
| Cosmos container creation fails | A TTL cannot be set on a container with indexing off; the Bicep uses per-document `ttl` instead. |
| `docker build` fails with `failed to fetch oauth token ... auth.docker.io` | Docker Hub; the Dockerfile avoids it by using `ghcr.io`. Start Docker Desktop first. |
| First request after idle takes 20 s and the first `/health` can time out | Scale to zero. Do not pay for `minReplicas: 1` on the free tier; the web page wakes the Brain on load with `/health?match=<id>`, which also loads that match's data first (about 20 s per match on the container). The Ask tab waits for that before it sends a question, because a question asked sooner would only wait for the match to load. |

## Cost notes (verify on the pricing pages)

Cosmos DB free tier (one per subscription), SignalR Free, Static Web Apps Free and Container Apps scale-to-zero
keep idle cost near zero; model tokens are the real cost, and the deployment's token-a-minute capacity is the ceiling on them.
Month to date at the time of writing (Oct 9, 2026) the whole resource group had cost about $1.42 against the $20 budget.
The Azure free account's credit lasts 30 days, so open it close to when you need it, and keep the GitHub Pages mirror
(`pages.yml`) as the judge link that needs no backend. A budget with alerts at 25%, 50% and 90% of $20 a month is created
when `BUDGET_CONTACT` is set; budgets alert, they do not stop spending, which is why the guards below exist.

## Operating it

```bash
curl https://<brain>/health            # {"status","llm","agents","sharedCache":{"connected","lastError","entries"}}
az containerapp logs show -g rg-matchmind -n ca-matchmind-brain --type console --tail 50
az containerapp revision restart -g rg-matchmind -n ca-matchmind-brain --revision <name>   # a fresh replica with empty memory
```

In the Foundry project's Application Insights (Logs), the traces of the last hour:

```
dependencies | where timestamp > ago(1h) and name == 'matchmind.beats'
| extend hedged = toint(customDimensions['matchmind.hedged']), calls = toint(customDimensions['matchmind.modelCalls'])
| summarize requests = count(), calls = sum(calls), hedged = sum(hedged), p50 = percentile(duration, 50), p95 = percentile(duration, 95)
```

## Not built yet

Microsoft Fabric. Key Vault is provisioned but nothing uses it. The event-driven pipeline of the plan (simulator job, Event Grid analyzer, change-feed
Functions, SignalR push) is built: [live-pipeline.md](live-pipeline.md).

## Running it in public (October 2026 hardening)

The Brain is on the open internet and calls a paid model, so it protects itself. All of it is in `src/matchmind/guards.py`
and `apps/brain/main.py`, and was checked on the live service.

| Guard | Behaviour |
|---|---|
| Rate limit | 20 `POST /api/beats`, 10 `POST /api/ask` and 60 `/mcp` requests a minute per client, then HTTP 429 with `Retry-After`. The client is the **last** `X-Forwarded-For` entry (the one the ingress appends), so a forged header does not help. |
| Concurrency cap | At most 8 `/api/beats` and 4 `/api/ask` requests are served at once; a burst gets 503 at once instead of queueing behind slow model calls. |
| Admin key | `mode: "full"`, `useCache: false` and `deadlineMs` over 10 000 need the `x-admin-key` header. The key is `MATCHMIND_ADMIN_KEY` in the azd environment, stored as a Container Apps secret. Unset (local development), nothing is restricted. |
| Headers | `X-Content-Type-Options`, `Referrer-Policy`, `Strict-Transport-Security`. |
| Spend ceiling | The model deployment is capped at 120 000 tokens a minute, and the Log Analytics workspace at 0.5 GB a day. |

Three things that used to stall or lose work, and what fixed them:

* **The event loop must never wait on a match.** Loading a match re-simulates it (about 6 s on a laptop, 20 s on the container).
  MCP tools now run in worker threads, `moments`, `analytics` and `win-probability` are read from the replay package, and the
  matches are preloaded in the background after start-up (`MATCHMIND_PRELOAD=1`). A cold MCP call used to take 22 s and freeze
  `/health` for 20 s; it now takes about 0.3 s and nothing waits.
* **Cached text outlives a restart.** Verified model text is kept in memory and in Cosmos DB (`beats` container, 7-day expiry,
  `MATCHMIND_SHARED_CACHE=1`). A fresh replica served a result cached before it existed in 282 ms with no model call. Cosmos is
  time-boxed and any error counts as a miss, so it can only make a request faster. `/health` shows `sharedCache`.
* **Hedging is for the slow tail only.** A second identical model call starts after 4 s (`MATCHMIND_HEDGE_S`). With the earlier, faster model, at 2.2 s about half of
  all calls were duplicated and at 3.2 s, 16% were; `gpt-6-luna` is about a second slower, so the hedge moved to 4 s.

Traces go to the **Foundry project's own** Application Insights (`APPINSIGHTS_CONNECTION_STRING_OVERRIDE`), so they appear in the
Foundry portal; set it with `az monitor app-insights component show --app <project>-appinsights -g <rg> --query connectionString`.
`matchmind foundry-register` must be re-run after any change to `prompts.py`: with `MATCHMIND_AGENTS=foundry` the Brain checks each
registered agent's `promptVersion` at start-up and, if one is stale or missing, falls back to local agents and says so in `/health`.

Provisioned but not used by the app: Key Vault.

### Deploying the live pipeline

* `azd provision` creates the job, the Function App and their roles; **always run `azd deploy` after it** (provisioning alone resets the Brain's image to the
  placeholder). `azd deploy` builds and pushes the Brain image, packages the Function App (the `prepackage` hook copies `src/matchmind` and `data/league` into
  `apps/functions/`) and publishes the web app; a `postdeploy` hook then points the simulator job at the image just deployed.
* `MATCHMIND_LIVE_KEY` is a shared secret between the dispatcher Function and the Brain: `azd env set MATCHMIND_LIVE_KEY "$(openssl rand -hex 24)"` before provisioning.
  Without it the Brain refuses the dispatcher (the endpoint fails closed).
* The postdeploy hook (`infra/hooks/postdeploy.sh`) points the job at the new image and (re)creates the Event Grid subscription of the `analyze` Function; the Event Grid provider
  (`Microsoft.EventGrid`) has to be registered on the subscription.
* Things that went wrong: SignalR answered 403 to the Function's token request because the Bicep role called "SignalR Service Owner" carried the GUID of the management-plane
  Contributor (the data-plane role is `7e4f1700-ea5a-4f59-8f37-079cfe29dce3`); the SignalR JavaScript client sends credentialed requests by default, which a CORS list without credentials
  rejects (`withCredentials: false`); the job-start API takes the container list itself, not a job template wrapped around it (a bare 400); the Functions host needs Blob Data Owner
  and Table Data Contributor on the storage account besides the roles the Brain uses.
