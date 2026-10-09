# Running on Azure

**Status: deployed and verified on a free subscription (October 2026).** The Brain (Container Apps), the web app (Static Web Apps), Cosmos DB, Storage, SignalR, Application Insights and a Foundry project are provisioned by `azd up`. SignalR and Cosmos are provisioned but not yet used by the app. The table below dates from before the first deploy; see [foundry.md](foundry.md) for what ran against Foundry.

| Piece | What is verified |
|---|---|
| `infra/*.bicep` | Compiles with `az bicep build` with no errors or warnings (this caught one real error) |
| `Dockerfile` | Builds; the container runs as a non-root user, serves the API, runs the agent workflow, degrades through the fault switch, and answers MCP |
| `.github/workflows/*` | YAML valid; not yet executed on GitHub |
| Everything that needs a subscription | **Not verified**: role assignments, Container Apps ingress, Cosmos free tier, SignalR, budget |

## First deploy

```bash
azd auth login
azd env new matchmind && azd env set AZURE_LOCATION swedencentral   # any region open to your subscription; try azd provision --preview first
azd env set BUDGET_CONTACT you@example.com    # alerts at 25%, 50% and 90% of a $20 monthly budget
# Optional: a Foundry project (portal) and a model deployment, then
azd env set FOUNDRY_PROJECT_ENDPOINT https://<account>.services.ai.azure.com/api/projects/<project>
azd env set MATCHMIND_LLM_MODEL <deployment-name>
azd up
```

The Static Web App has its own region (`WEB_LOCATION`, default `eastus2`): it only exists in a few regions and is served from a CDN, so it does not need to match. Some new subscriptions are refused in popular regions (West Europe returned `locationineligible` for one); pick another region for `AZURE_LOCATION`.

If the Container Apps environment fails with `ManagedEnvironmentNoAvailableCapacityInRegion`, keep the data where it is and put only the apps elsewhere: `azd env set APPS_LOCATION northeurope` (any region with capacity) and run `azd up` again.

Locally built image: ACR cloud builds (Tasks) are refused on new subscriptions (`TasksOperationsNotAllowed`), so `azure.yaml` builds the Brain image on your machine (Docker running) for `linux/amd64`.

The Brain's MCP endpoint (`/mcp/`) refuses any Host header the library does not know (421), so the Bicep sets `MATCHMIND_ALLOWED_HOSTS` to the app's public name.

Without a Foundry endpoint the Brain keeps the offline model. `azd down --purge` removes everything.

## Cost notes (verify on the pricing pages)

Cosmos DB free tier (one per subscription), SignalR Free, Static Web Apps Free and Container Apps scale-to-zero
keep idle cost near zero; model tokens are the real cost. The Azure free account's credit lasts 30 days, so
open it close to when you need it, and keep the GitHub Pages mirror (`pages.yml`) as the judge link that
needs no backend. A budget with alerts at 25%, 50% and 90% of $20 a month is created when `BUDGET_CONTACT` is set.

## Not built yet

The Functions pipeline adapters (Cosmos change feed, Event Grid blob trigger, SignalR publishing) and
Microsoft Fabric. The Brain runs the agents on demand and the web app plays replay packages.

## Running it in public (October 2026 hardening)

The Brain is on the open internet and calls a paid model, so it protects itself. All of it is in `src/matchmind/guards.py`
and `apps/brain/main.py`, and was checked on the live service.

| Guard | Behaviour |
|---|---|
| Rate limit | 20 `POST /api/beats` and 60 `/mcp` requests a minute per client, then HTTP 429 with `Retry-After`. The client is the **last** `X-Forwarded-For` entry (the one the ingress appends), so a forged header does not help. |
| Concurrency cap | At most 8 `/api/beats` requests are served at once; a burst gets 503 at once instead of queueing behind slow model calls. |
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
* **Hedging is for the slow tail only.** A second identical model call starts after 3.2 s (`MATCHMIND_HEDGE_S`). At 2.2 s, about half of
  all calls were duplicated; at 3.2 s, 16% were (45 uncached calls, 15 requests, no missed deadline, request p50 2.6 s, p95 4.2 s).

Traces go to the **Foundry project's own** Application Insights (`APPINSIGHTS_CONNECTION_STRING_OVERRIDE`), so they appear in the
Foundry portal; set it with `az monitor app-insights component show --app <project>-appinsights -g <rg> --query connectionString`.
`matchmind foundry-register` must be re-run after any change to `prompts.py`: with `MATCHMIND_AGENTS=foundry` the Brain checks each
registered agent's `promptVersion` at start-up and, if one is stale or missing, falls back to local agents and says so in `/health`.

Provisioned but not used by the app yet: SignalR, Storage and Key Vault (the event-driven pipeline of the plan is not built).
