# Instructions for GitHub Copilot in this repository

MatchMind turns synthetic football events into explained, personalized match intelligence.
Read `SOLUTION PLAN.md` (status section first), `docs/architecture.md` and `docs/agents.md` before changing behaviour; the API and every setting are in `docs/brain-api.md` and `docs/configuration.md`.

## Rules that must not be broken
- **Code computes, models explain.** Numbers come from deterministic code (`intel/`, `tracking/`). A
  language model may only write or localize text, and every sentence it writes must pass
  `agents/verify.py`. Never loosen the Verifier to make a test pass; license the number in the
  evidence pack instead.
- **Evidence or it did not happen.** Agents may use only what is in an evidence pack. Metrics flagged
  `consistent: false` must be admitted, not cherry-picked.
- **Degrade, never drop.** A failing model must fall back to the template tier (`agents/templates.py`),
  never to silence.
- **Messages in the agent workflow are immutable** and edge conditions are mutually exclusive
  (`agents/workflow.py`); a shared mutable message once made two branches fire.
- **The live path has a deadline and a floor.** `agents/fast.py` renders template text first and lets a model text replace it only if it arrives in
  time and passes the Verifier. Never make a request wait on a model call, on a cancelled task or on Cosmos (every Cosmos call is time-boxed;
  an error is a miss). The Repairer may only remove text, never add it.
- **Never block the event loop.** Loading a match re-simulates it (6 to 20 s); anything like that runs in a worker thread (`asyncio.to_thread`) or is
  read from the replay package. A test (`test_a_slow_mcp_tool_does_not_freeze_the_server`) fails if a tool stalls `/health`.
- **Whatever reaches a prompt or a path is validated.** Match ids must be plain slugs (`SAFE_MATCH_ID`); a cohort's `perspective` and `focusPlayer` must be
  the match's own club and player ids. The model sees player names, never ids such as `NOR-21` (their digits fail the number check).
- **Ask the match validates what the model plans.** The planner's tools are checked by code against an allow-list (`agents/ask.py`): unknown tools, undeclared arguments and any
  `match_id` but the request's are dropped, numeric arguments are clamped to their range, and the answer must pass the Verifier against the tool results. The Verifier cannot check
  the logic that joins facts, so the answerer's prompt forbids inventing order or cause.
- **The public API guards itself** (`guards.py`): rate limit, in-flight cap, admin key for `mode: full`, `useCache: false` and long deadlines. Do not
  add an expensive option without putting it behind the key.
- **Prompts are versioned.** After changing `agents/prompts.py`, bump `PROMPT_VERSION` and run `uv run matchmind foundry-register`; with
  `MATCHMIND_AGENTS=foundry` the Brain refuses registered agents whose stored prompt version is stale and falls back to local ones.
- All data is synthetic and the clubs and players are fictional. Do not add real names, crests or logos.
- No pronouns for people in generated text; no case suffixes attached to numbers (Turkish).

## Working here
- Python 3.12 with `uv`: `uv sync`, `uv run pytest -m "not slow" -n auto` (the 3 slow tests run nightly), `uv run ruff check src tests apps`.
- Web: `cd web && pnpm install && pnpm typecheck && pnpm test && pnpm build`. `VITE_BRAIN_URL` points the Live AI switch at a Brain.
- Foundry and Azure: `uv run matchmind foundry-register | foundry-evals | foundry-host`, `azd provision && azd deploy` (Docker must be running); the Dockerfile builds from `ghcr.io`, not Docker Hub.
- After changing the simulator, run `uv run matchmind report-realism`; every metric must stay in its band.
- After changing templates, prompts or contracts: `uv run matchmind export-schemas`, rebuild packages with
  `uv run matchmind build-replay <scenario>` and run `uv run matchmind evals`.
- Check exit codes directly; do not pipe test output into `tail` in a chain you rely on.
