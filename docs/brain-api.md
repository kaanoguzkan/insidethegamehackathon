# The Brain API

The Brain is a FastAPI service (`apps/brain/main.py`) that serves the match data, the live overlay endpoint and an MCP server. It is
deployed at `https://ca-matchmind-brain.ambitiouswave-e3f38943.northeurope.azurecontainerapps.io` (Container Apps, scale to zero: the first request
after idle takes about 20 seconds, so call `/health` first). Interactive docs are at `/docs` and the schema at `/openapi.json`.

| Method and path | What it does |
|---|---|
| `GET /health` | Liveness plus configuration: `llm`, `agents`, `sharedCache`, `loaded`, `version`, `matches`. `?match=<id>` says the match center is open on that match: its data is loaded first, and `loaded` lists the matches whose tools are instant |
| `GET /api/matches` | The ids of the matches that can be queried |
| `GET /api/matches/{id}/moments?min_salience=0.6` | The detected moments: `id`, `type`, `label`, `salience`, `team` |
| `GET /api/matches/{id}/analytics` | The match's Opta-style analytics (what the replay package stores as `analytics.json`) |
| `GET /api/matches/{id}/win-probability` | The win-probability series, swings and pre-match prediction |
| `GET /api/matches/{id}/report.pdf` | The printable 17-page match report |
| `POST /api/beats` | **Overlays for chosen moments and viewer cohorts, written now** (below) |
| `POST /api/ask` | **Ask the match a question**: an answer written from the match-data tools only, checked by the Verifier (below) |
| `GET /api/live`, `GET /api/live/{id}`, `GET /api/live/{id}/feed`, `/meta`, `/chunks/{n}`, `GET /api/live/config` | **The live pipeline**: live and recent matches, one match with its clock, what is new in it, its metadata and tracking chunks, and the deployment's push address ([below](#live-pipeline)) |
| `GET /api/stream/{id}/vision`, `GET /api/stream/{id}/vision/frame?atMs=` | **The video feed of a live match**: how close the tracking rebuilt from the pixels is to the truth (and how many chunks were skipped when the video model fell behind), and the frame at a moment with the detections boxed as a PNG. See [vision.md](vision.md) |
| `POST /api/ask/live` | **Ask a live match**: `{streamId, question, language, mode, atMs}`. Answered by the same agents, tools and Verifier as `/api/ask`, but from the match as it stood at `atMs` (never later than the match clock): an interpreter is rebuilt from the documents that had arrived by then, so nothing the viewer has not seen can be in an answer. Shares Ask's rate limit; not cached |
| `GET /api/ops` | **Operations**: the last 15 minutes of requests (counts, 5xx, p50/p95 per group), how stories were made (model, repaired, template), claims verified, cache hits, tokens, live matches against capacity, model and cache status. Public, read-only |
| `GET /ready` | **Readiness**: 200 when the matches are loaded, a model client is configured and the shared cache is reachable; 503 with the failing checks otherwise. The availability test calls it |
| `GET /api/channel`, `POST /api/channel/tune` | **The channel** (not used by the web app): what is on air, and join it or start the next fixture |
| `GET /api/season`, `POST /api/season/simulate` | **The season** (not used by the web app): fixtures, results, tables and simulation progress; plan and simulate a new season (public, limited) |
| `POST /api/live/start` | Start the simulator job on a demo match (public, limited) |
| `GET /api/stream/demos`, `POST /api/stream`, `GET /api/stream/{id}` (`/meta`, `/feed`, `/chunks/{n}`), `POST /api/stream/{id}/cohorts`, `POST /api/stream/{id}/speed` (1, 5 or 10: the match carries on from the same minute at the new speed), `DELETE /api/stream/{id}` | A match of your own, played and interpreted in the Brain's process (public, limited); see [live-pipeline.md](live-pipeline.md#streams-the-same-stages-in-one-process) |
| `POST /api/live/{id}/beats` | Internal: write the narrative overlays for new moments (the dispatcher Function calls it; needs `x-live-key`) |
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
  "budget": 3, "mode": "fast", "deadlineMs": 6000, "useCache": true
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
| `deadlineMs` | 6000 | Fast mode: wall-clock limit for the whole request (500 to 30 000) |
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

### The six-second guarantee

Fast mode answers inside `deadlineMs` whatever the model does. Template text is rendered first for every cohort; the model's text replaces it only
if it arrives in time and the Verifier accepts it (a rejected text is first mended by the Repairer, which cuts out only what failed). A model call that
is slower than 4 s is hedged with a second identical call and the first answer wins. Measured with the model in use (`gpt-6-luna`, registered agents): median 2.8 s, 90th percentile
3.8 s, slowest 4.7 s, no missed deadline in 27 requests ([agents.md](agents.md)); the match center shows a loading bar meanwhile. The browser's own limit in the match center is 12 s, a safety net only. The match center sends only a club and a followed player that belong to the match on screen (they survive a change of match in the URL, and the Brain refuses a foreign one).

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

## The channel and the season

* `GET /api/channel` → `{now, seasonId, speeds}`. `now` is the match on air (`matchId`, `seasonId`, `fixtureId`, `round`, `speed`, `heartbeatMs`, and `match`: the same summary as `GET /api/live/{id}`) or null.
* `POST /api/channel/tune` with `{}` joins the match on air or starts the next fixture of the current season from its pack; `{"fixtureId": "f07"}` plays that (simulated) fixture, replacing the
  match on air; `{"next": true}` skips to the next one; `{"speed": 10}` sets the speed of the match it starts (5, 10 or 20, anything else is a 422). **503** with `Retry-After: 5` while no fixture of the
  season is simulated yet; **429** over 20 a minute.
* `GET /api/season` → the current season: `seasonId`, `total`, `done`, `simulating`, `fixtures` (`id`, `round`, `home`, `away`, `scenario`, `status`: pending, simulating or done, `score`), `aired` (the
  fixtures played on air to the end), `standings` (the table over every simulated fixture), `standingsAired` (over the aired ones only: what the home page shows) and `clubs` (names and kit colours).
  On a deployment with no season it plans the default one (`season-1`, round 1 being the three stories) and starts the season job.
* `POST /api/season/simulate` plans a new season (new seeds) and starts the season job; it becomes the current season at once. **409** with the id of a season that is still being simulated, **429** over two a minute.

## Live pipeline

How it fits together: [live-pipeline.md](live-pipeline.md). A match is `{matchId, status (scheduled | live | finished), scenario, speed, fromMs, wallStartMs, durationMs, clockMs,
serverNowMs, home, away, players}`; `clockMs` is where the match clock stands at `serverNowMs`, and a client advances it by the wall time since at `speed` times.

* `GET /api/live` lists live and recent matches (newest first, at most 20). Failed starts and jobs that never began are not listed.
* `GET /api/live/{id}/feed?event=<n>&since=<ms>` returns the match plus what is new: `events` (goals, shots, cards, substitutions, formation changes above feed sequence
  `n`, at most 500 raw documents per call; `more` says to ask again at once with `eventCursor`), `overlays` emitted at or after `since` (the client drops repeats by id; use
  `overlayCursor` next time) and every `moments` found so far. Start with `event=-1&since=0`.
* `GET /api/live/{id}/meta` is the match's metadata (teams, kits, line-ups, periods): the same document as a replay package's `meta.json`, which the pitch draws from.
  `GET /api/live/{id}/chunks/{n}` is one five-second tracking chunk (gzip JSON, `Content-Encoding: gzip`, immutable and cacheable; 404 until the simulator job has published
  it): the storage account is private, so the Brain serves the chunks. `GET /api/live/config` says where browsers connect for SignalR pushes (`push`, the Function app's `/api`
  address or null) and how far behind the live feed to watch (`delayS`, 25).
* `GET /api/live/{id}/feed` also returns each moment's `createdMs` (when the interpreter stored it), so a client can split the delay between detecting a moment and writing its overlay.
* `POST /api/live/start` with `{"scenario": "red-card-drama", "fromMinute": 40}` answers `{matchId, scenario, fromMinute}` at once; the job takes about half a minute to
  simulate before the match goes live. **409** with `{"detail": {"matchId": ...}}` when a match is already running (join it); **422** for an unknown scenario or a start
  minute outside 0 to 80; **429** over three starts a minute; **502** when the job could not be started; **503** on a Brain with no job configured.
* `POST /api/live/{id}/beats` with `{"momentIds": [...]}` writes and stores the narrative overlays, once per moment (a repeat writes nothing). **403** without the right
  `x-live-key`, which is required even when none is configured (set `MATCHMIND_LIVE_OPEN=1` on a development machine).

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
