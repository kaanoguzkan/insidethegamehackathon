# The Brain API

The Brain is a FastAPI service (`apps/brain/main.py`) that serves the match data, the live overlay endpoint and an MCP server. It is
deployed at `https://ca-matchmind-brain.ambitiouswave-e3f38943.northeurope.azurecontainerapps.io` (Container Apps, scale to zero: the first request
after idle takes about 20 seconds, so call `/health` first). Interactive docs are at `/docs` and the schema at `/openapi.json`.

| Method and path | What it does |
|---|---|
| `GET /health` | Liveness plus configuration: `llm`, `agents`, `sharedCache`, `version`, `matches` |
| `GET /api/matches` | The ids of the matches that can be queried |
| `GET /api/matches/{id}/moments?min_salience=0.6` | The detected moments: `id`, `type`, `label`, `salience`, `team` |
| `GET /api/matches/{id}/analytics` | The match's Opta-style analytics (what the replay package stores as `analytics.json`) |
| `GET /api/matches/{id}/win-probability` | The win-probability series, swings and pre-match prediction |
| `GET /api/matches/{id}/report.pdf` | The printable 17-page match report |
| `POST /api/beats` | **Overlays for chosen moments and viewer cohorts, written now** (below) |
| `POST /api/ask` | **Ask the match a question**: an answer written from the match-data tools only, checked by the Verifier (below) |
| `/mcp/` | The Match Data MCP server, streamable HTTP, stateless, 25 tools |
| `GET/POST /api/director/faults` | The model-fault switch of the resilience demo. Only exists when `MATCHMIND_DIRECTOR=1`; key-protected by `X-Director-Key` |

The read endpoints answer from the replay package on disk (milliseconds). Matches that are registered in memory only fall back to the interpreter.

## `POST /api/beats`

The request names a match, one to six moments and one to twelve viewer cohorts. The Brain writes one overlay per moment and cohort.

```json
{
  "match_id": "red-card-drama",
  "moment_ids": ["red-card-drama-mo-004"],
  "cohorts": [
    {"mode": "casual",  "language": "en"},
    {"mode": "analyst", "language": "es", "perspective": "RED", "focusPlayer": null}
  ],
  "budget": 3, "mode": "fast", "deadlineMs": 5000, "useCache": true
}
```

| Field | Default | Meaning |
|---|---|---|
| `cohorts[].mode` | `casual` | `analyst`, `casual` (or `any` for stat graphics, which have no narrative) |
| `cohorts[].language` | `en` | `en`, `es`, `tr` |
| `cohorts[].perspective` | `neutral` | `neutral` or **one of the match's club ids** (anything else is refused): the tone is written for that club's supporter; facts never change |
| `cohorts[].focusPlayer` | `null` | **One of the match's player ids** (anything else is refused) |
| `budget` | 3 | How many non-mandatory moments the Editor may keep as beats (0 to 6) |
| `mode` | `fast` | `fast`: one model call per cohort inside `deadlineMs`, template text for whatever misses it. `full`: the five-agent workflow (tens of seconds) |
| `deadlineMs` | 5000 | Fast mode: wall-clock limit for the whole request (500 to 30 000) |
| `useCache` | true | Serve and store verified model text in the cache |

**Who may use what.** With `MATCHMIND_ADMIN_KEY` set (it is on Azure), `mode: "full"`, `useCache: false` and a `deadlineMs` over 10 000 need the header
`x-admin-key: <key>`; without it the answer is 403. The ordinary fast request is open.

### The answer

```json
{
  "mode": "fast",
  "stats": {"cacheHits": 0, "modelCalls": 3, "hedged": 1, "repaired": 0, "rejected": 0, "missedDeadline": 0, "cacheSize": 12},
  "elapsedMs": 2486,
  "beats": [{
    "momentId": "red-card-drama-mo-004", "level": 0, "agents": ["editor", "router", "composer", "verifier", "producer"],
    "overlays": [ { "...": "an Overlay, see overlay-contract.md" } ],
    "trace": [{"agent": "router", "outcome": "3 of 3 cohorts to the model", "ms": 0.0}, {"agent": "composer", "outcome": "ok: casual/en/neutral/-", "ms": 2301.4}]
  }]
}
```

* `level` is the worst fallback level among the beat's overlays: 0 written by the model and verified first time, 1 mended by the Repairer
  (or retried, in full mode), 2 template text. Each overlay carries its own `provenance.fallbackLevel`, `provenance.agents` and `provenance.verified`.
* `stats` also reports `inputTokens`, `outputTokens` and `costUsd` for the model calls of the request (hedged and cut-off calls included).
* `stats` counts what happened: `cacheHits`, `modelCalls`, `hedged` (second, duplicate calls started because the first was slow), `repaired`,
  `rejected` (model text the Verifier refused and the Repairer could not mend), `missedDeadline` (calls cut off), `cacheSize`.
* `trace` has one entry per step with its duration in milliseconds. Agents that appear: `editor`, `router`, `cache`, `composer`, `verifier`, `repairer`, `producer`.
* Moments the Editor does not select become one-line `ticker` overlays at level 2.

### Errors

| Status | When |
|---|---|
| 403 | An admin-only option without the right `x-admin-key` |
| 404 | Unknown match or unknown moment ids |
| 422 | The request breaks a bound (no moments, more than 6 moments or 12 cohorts, an unknown language ...), or a cohort names a club or player the match does not have. These two fields go into the model's prompt, so free text there is refused before any model call |
| 429 | More than 20 `/api/beats` (or 60 `/mcp`) requests a minute from one client; `Retry-After` says when to retry |
| 503 | More than 8 `/api/beats` requests being served at once; `Retry-After: 2` |

### The five-second guarantee

Fast mode answers inside `deadlineMs` whatever the model does. Template text is rendered first for every cohort; the model's text replaces it only
if it arrives in time and the Verifier accepts it (a rejected text is first mended by the Repairer, which cuts out only what failed). A model call that
is slower than 3.2 s is hedged with a second identical call and the first answer wins. Measured on the deployed Brain: median 2.6 s, 95th percentile
4.2 s, no missed deadline in 45 calls ([agents.md](agents.md)). The browser's own limit in the match center is 12 s, a safety net only. The match center sends only a club and a followed player that belong to the match on screen (they survive a change of match in the URL, and the Brain refuses a foreign one).

## `POST /api/ask`

```json
{"match_id": "pressing-collapse", "question": "How did the pressing change?", "language": "en", "mode": "casual", "minute": 54}
```

`question` is 2 to 280 characters (longer is refused, control characters are stripped); `language` is `en`, `es` or `tr`; `mode` is `analyst` or `casual`;
`minute` (optional, 0 to 130) tells the planner where the viewer is, but answers may use the whole match.

```json
{
  "answer": "Harbour City pressed higher after the 55th minute ...",
  "level": 0, "verified": true, "refused": false, "cached": false,
  "tools": [{"name": "get_pressing_report", "args": {}}],
  "elapsedMs": 2600,
  "usage": {"inputTokens": 2283, "outputTokens": 100, "costUsd": 0.001},
  "trace": [{"agent": "planner", "outcome": "ok: get_pressing_report", "ms": 1457.7}, {"agent": "tools", "outcome": "1 of 1 gave data", "ms": 1.7}, {"agent": "answerer", "outcome": "ok", "ms": 1109.9}]
}
```

How it works ([agents.md](agents.md#ask-the-match)): a **planner** chooses up to three tools from an allow-list of the MCP tools (or keyword rules do, if the model is
unavailable or its choice does not run); code runs them against this match; an **answerer** writes the reply from the results only; the **Verifier** checks every number and name
against those results.

* `level`: 0 a model answer that passed the checks, 1 mended by cutting out the sentences the data did not support, 2 only the numbers the data gives (no model text could be
  verified), 3 refused (off topic) or nothing found.
* `tools` are the tools that were run, never including `match_id`, which is always the request's.
* `usage` is the tokens the answer used and what they cost at the configured price (`costUsd`); a `cached` answer costs nothing.
* An off-topic question is refused after the planner, with no tools run and no answerer call.
* Errors: 404 unknown match, 422 a bound broken, 429 more than 10 questions a minute from one client (`MATCHMIND_ASK_PER_MIN`), 503 more than 4 questions being answered at once.

## MCP

`/mcp/` is a stateless streamable-HTTP MCP server with 25 tools: `list_matches`, `list_moments`, `get_match_state`, `get_window_stats`,
`compare_windows`, `get_event_chain`, `get_player_window`, `get_player_profile`, `get_season_context`, `get_prediction`, `get_win_probability`,
`get_key_actions`, `get_space_control`, `get_passing_network`, `get_team_shape`, `get_phases_of_play`, `get_line_breaks`, `get_off_ball_runs`,
`get_physical_load`, `get_transitions`, `get_set_piece_report`, `get_shot_map`, `get_goalkeeper_report`, `get_pressing_report`, `explain_metric`.
Tools run in worker threads, and the Brain loads the matches in the background after start-up, so a first call does not wait for a simulation.
MCP requests count towards the per-client rate limit (60 a minute). `.vscode/mcp.json` points GitHub Copilot's agent mode at a local Brain.

## The same endpoint as a Foundry hosted agent

`matchmind-newsroom` (`foundry/hosted/main.py`, uploaded with `matchmind foundry-host`) serves the same `serve_beats` function behind Foundry's agent endpoint.
Send the same JSON as the input text and receive the same answer as JSON text; see [foundry.md](foundry.md) for the URL, the protocol version and the first-call caveat.

## Protection and CORS

Rate limit, in-flight cap, admin key and security headers are described in [running-on-azure.md](running-on-azure.md#running-it-in-public-october-2026-hardening).
Browsers may call the API from `localhost` dev servers and from the origins in `MATCHMIND_CORS_ORIGINS` and `MATCHMIND_ALLOWED_ORIGINS`
(the Static Web App and the GitHub Pages site); allowed methods are `GET`, `POST` and `OPTIONS`.
