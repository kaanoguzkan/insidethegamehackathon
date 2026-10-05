# Running on Azure

**Status: authored, partly verified, not deployed.** No Azure access was available while building.

| Piece | What is verified |
|---|---|
| `infra/*.bicep` | Compiles with `az bicep build` with no errors or warnings (this caught one real error) |
| `Dockerfile` | Builds; the container runs as a non-root user, serves the API, runs the agent workflow, degrades through the fault switch, and answers MCP |
| `.github/workflows/*` | YAML valid; not yet executed on GitHub |
| Everything that needs a subscription | **Not verified**: role assignments, Container Apps ingress, Cosmos free tier, SignalR, budget |

## First deploy

```bash
azd auth login
azd env new matchmind && azd env set AZURE_LOCATION westeurope
# Optional: a Foundry project (portal) and a model deployment, then
azd env set FOUNDRY_PROJECT_ENDPOINT https://<account>.services.ai.azure.com/api/projects/<project>
azd env set MATCHMIND_LLM_MODEL <deployment-name>
azd up
```

Without a Foundry endpoint the Brain keeps the offline model. `azd down --purge` removes everything.

## Cost notes (verify on the pricing pages)

Cosmos DB free tier (one per subscription), SignalR Free, Static Web Apps Free and Container Apps scale-to-zero
keep idle cost near zero; model tokens are the real cost. The Azure free account's credit lasts 30 days, so
open it close to when you need it, and keep the GitHub Pages mirror (`pages.yml`) as the judge link that
needs no backend. A budget with alerts at 25%, 50% and 90% is created when budget contacts are provided.

## Not built yet

The Functions pipeline adapters (Cosmos change feed, Event Grid blob trigger, SignalR publishing) and
Microsoft Fabric. The Brain runs the agents on demand and the web app plays replay packages.
