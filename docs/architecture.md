# Architecture

MatchMind is one Python package (`src/matchmind`) used by every deployment shape, plus a Brain service
(`apps/brain`) and a static web app (`web/`).

## Data flow

1. **Simulator** (`sim/`). A 5 Hz agent-based simulation of 22 players and a ball for a fictional
   six-club league. Style dials (press intensity and height, line height, width, tempo, directness,
   counter bias) drive movement, pressing, marking, transitions and decisions, so clubs differ in the data.
   Nine formations each have an attacking shape and a defensive block that a team glides between with the
   ball, club tags choose how the shape is played (fullbacks, pivot, false nine), and restarts are
   choreographed (corner routines, walls, short or long goal kicks, throw-in outlets; see
   [tactics.md](tactics.md)). Output: an event stream and tracking frames, as a data provider would deliver. Scenarios (YAML) script
   changes mid-match; the pipeline is never told about them.
2. **Tracking** (`tracking/`). Frames travel as 5-second gzip chunks (live) or one bundle (replay). The
   **physical analyzer** is incremental and reads only tracking and events: sprints, top speed, distance
   milestones, team shape, how closely the nearest defender closes the ball down, and per-pass/shot
   context (ball speed, pressure, lane blockage). Streaming and batch runs give identical output.
3. **Interpreter** (`intel/`). A streaming state machine. It merges late physics, computes window metrics,
   three indices (control vs chaos, pressure, rhythm, z-scored against measured league baselines), and
   detects moments. Each moment gets an **evidence pack** (see [metrics.md](metrics.md)).
4. **Agent workflow** (`agents/workflow.py`). See [agents.md](agents.md).
5. **Overlay Producer** (`agents/producer.py`). Timing from the match clock, one lower-third at a time per
   cohort, late items dropped or turned into tickers, stat graphics shared across modes
   ([overlay-contract.md](overlay-contract.md)).
6. **Delivery.** A replay package (static JSON + one tracking bundle) played by the web app, or the Brain
   service running the same agents on demand and exposing the data through MCP.

## Key decisions

* **Code computes, models explain.** Numbers are exact, cheap and testable; models only choose and phrase.
* **Ports and adapters.** The pipeline touches storage, queues and models through small interfaces, so the
  same code runs locally (files, memory, an offline model) and on Azure.
* **Immutable workflow messages, mutually exclusive edge conditions.** A shared mutable message once made
  two branches fire during prototyping; the rule is now structural.
* **Cohorts, not viewers.** Text is generated once per distinct audience (mode, language, club side,
  followed player); cost grows with cohorts, not audience size.
* **Replay packages for judges.** Static files, no backend and no model at view time, plus a GitHub Pages
  mirror that survives an Azure outage.

## Azure shape (Bicep in `infra/`)

Container Apps (the Brain, scales to zero, max 2 replicas), Cosmos DB free tier (identity-only), Storage
(replays, tracking chunks, work queue), SignalR free, Key Vault, Static Web Apps, Application Insights
and a budget with alerts. A user-assigned managed identity holds every role assignment; there are no keys
in configuration. See [running-on-azure.md](running-on-azure.md) for what is and is not verified.
