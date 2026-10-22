# Running MatchMind as a service

What an operator gets, and where the limits are. Everything here is in the repository; nothing is a slide.

## Identity and secrets

- Every Azure service is reached with a **user-assigned managed identity** and role assignments from `infra/resources.bicep` (blob, queue, table, Cosmos DB data roles, ACR pull, SignalR). No connection string or storage key is in the code or in the image.
- The model is reached with the same identity through the Foundry project endpoint. There is no model API key to leak.
- The only shared secrets are the two keys that guard operator endpoints (`MATCHMIND_ADMIN_KEY`, `MATCHMIND_LIVE_KEY`), compared in constant time, and they are Container Apps secrets.
- **Limit:** a Key Vault is provisioned but nothing reads it: the two keys are still Container Apps secrets rather than Key Vault references. There is no end-user sign-in: the match center is public by design, and what it exposes is read-only simulated data.

## Reliability

- `GET /health` says the process is alive; `GET /ready` says it can do its job (matches loaded, a model client configured, the shared cache reachable) and answers 503 with the reason when not. An availability test in Application Insights calls `/ready` every five minutes from three regions.
- The narrative has four levels of degradation (model text, repaired once, template, and the pitch without text), so a model outage costs wording, never the product. The verifier checks every number and name in a story against the evidence, so a fluent wrong story does not reach a viewer.
- Alerts (`infra/resources.bicep`): readiness failing from two places, more than five 5xx in ten minutes, CPU above 85% for fifteen minutes, any restart. They mail `budgetContact` when it is set.
- Live matches live in the memory of one replica, so the Brain runs as one always-on replica and caps live matches at six. A restart ends the matches that were on that replica; a viewer sees the match stop and can start another. Recorded matches and the shared cache are not affected.

## Observability

- OpenTelemetry to Application Insights (`src/matchmind/telemetry.py`): a span per agent call and per verification, request telemetry, and the model's token counts.
- `GET /api/ops` and the page at `#ops` show the last fifteen minutes without opening the portal: requests, errors, latency percentiles per group, how each story was made (model, repaired, template), the share of claims verified, cache hits, hedged calls, live matches against capacity. It carries no viewer identifiers.

## Data

- All data is simulated: clubs, players and matches are invented (`docs/data-card.md`). There is no personal data and no cookie; the only thing kept in the browser is a "seen the welcome" flag and the language.
- Live matches are deleted five minutes after the viewer leaves (finished ones after fifteen). The shared cache holds model text for identical demo moments, keyed by the evidence and the viewer profile, and expires.
- Matches are reproducible from fixture and seed. A recorded package is checked in CI on two platforms.

## Governance and supply chain

- Infrastructure is code (Bicep, `azd`), deployed from CI (`deploy.yml`) with OIDC; no long-lived Azure credentials are stored in GitHub.
- Third-party actions are pinned to commit SHAs (a test enforces it). Dependabot covers pip, npm, GitHub Actions and the Dockerfile. CodeQL scans Python and TypeScript on every push and weekly.
- Rate limits protect the public endpoints (6 live matches started per minute per client, 900 feed reads per minute). A budget and its alerts are created when `budgetContact` is set.
- Responsible-AI notes: `docs/responsible-ai.md`.

## Service levels this is built to

| What | Target | How it is measured |
|---|---|---|
| Brain ready | 99% over 30 days | availability test on `/ready` |
| A story in front of a live viewer | median under 3 s after the moment | `/api/ops` request percentiles and the measurements in `docs/live-pipeline.md` |
| Stories that are not template text | above 90% | `/api/ops` narrative block |

## What would come next

Key Vault references for the two keys; a second region with Cosmos-backed live sessions so a replica loss does not end a match; sign-in for operator pages; load tests in CI against a preview environment.
