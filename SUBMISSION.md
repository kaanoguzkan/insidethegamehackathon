# Rifinitore: submission

Every field of the Innovation Studio "Create Project" form, ready to paste (or to send to the Microsoft Global Hackathon Support Team, who said they will accept a manual submission).

## Title

Rifinitore: a live match explained, minute by minute, by verified AI agents

## Tagline

A synthetic Premier League match is played, analysed and explained as you watch it: code finds the moments, Foundry agents write the story for each viewer, a verifier checks every number, and you can ask the match anything.

## Keywords

football, multi-agent, Microsoft Foundry, Agent Framework, Azure Container Apps, Azure Functions, Event Grid, SignalR, Cosmos DB, MCP, explainable AI, real-time narratives, personalization

## Challenge

The Synthetic Match Insights Engine for Premier League Studio

## Skills needed / Writing code

Not open to join. Writing code: Yes.

## Code repository

https://github.com/kaanoguzkan/insidethegamehackathon

## Live site (no sign-in)

https://happy-beach-0379fb50f.5.azurestaticapps.net

## Demo video

https://www.youtube.com/watch?v=IcC8Hgkt26s

---

## Description (paste as Markdown)

### What it is

Rifinitore turns synthetic football events into explainable match intelligence in real time. Press **Watch live** and a match of your own is played on a 3D pitch with humanoid players. While it plays, the system detects what matters (a pressing collapse, a red card, a momentum swing), explains why, and writes the story for *you*: an analyst gets the numbers, a casual fan gets the narrative, in English, Spanish or Turkish. You can change the match's speed (1x, 5x, 10x) while it plays, and **ask the match a question** at any point.

### Architecture

![One match, five stages, and the Azure services behind each one](https://raw.githubusercontent.com/kaanoguzkan/insidethegamehackathon/main/docs/img/architecture-stages.svg)

More figures (two live paths, a story's path, the Azure map): `docs/img/architecture-*.svg`, and on the site at `#architecture`.

### The five stages

1. **Ingest.** A 5 Hz agent-based simulator plays fictional clubs; each side has a manager who reacts to the score, the clock, a sending-off and tired legs. Nothing is scripted.
2. **Interpret.** Code (not a model) computes the metrics, indices and moments (pressing, control vs chaos, rhythm, win probability, shape changes) and packs the evidence.
3. **Explain.** Eight Microsoft Foundry agents (registered prompt agents on gpt-6-luna, plus a hosted agent) choose the moments and write the explanation, orchestrated with the Microsoft Agent Framework.
4. **Render.** Timed, machine-readable overlays (lower thirds, tickers, pitch graphics) sit on the 3D pitch next to the match.
5. **Personalize.** Viewer mode (analyst or casual), language, favourite club and player change what is said and how.

### Why you can trust the text

*Code gets the evidence, the model only phrases it.* A **Verifier** checks every number, player and club in every story against the evidence. A story that fails is repaired once; if it still fails it falls back to a template. Nothing unchecked reaches a viewer, and the share of stories written by the model, repaired and templated is shown live on the Operations page.

### Auto-eventing from video

The challenge asks for a model over a video feed that generates the pass and speed metrics automatically. With no footage provided, Rifinitore renders its own video feed from the tracking, and in a live match the physical analysis reads **only what a vision model saw in the pixels**: a detector finds the players and the ball in each frame, a tracker rebuilds the tracking chunks, and the speeds, sprints, pass difficulty and shot speed are derived from that. A **Video feed** card shows the frame with the detections boxed and the live error against the simulator's truth. Measured over whole matches: player position error 8–10 cm, ball 3.5 cm, player speed 1.5–2.2 km/h, ball speed under 0.5 km/h; "who is who" is the weak spot (64–76% kept, corrected by the event feed), and `docs/vision.md` says so.

### Ask the match, as far as you have seen it

Ask planners choose from an allow-list of tools on our own **MCP server** (20+ match-data tools); code runs them and the answer is verified like the stories. In a live match the tools read the match **only as the viewer has seen it**: an interpreter is rebuilt from the documents that had arrived by the viewer's position, so a question cannot give away a goal or a card that has not happened yet (tested on Azure with the position forced to the end of the match).

### Microsoft and Azure technologies

- **Microsoft Foundry:** 8 registered agents and a hosted agent on gpt-6-luna, evaluations, tracing in the Foundry project.
- **Microsoft Agent Framework:** the agent team and workflow (planner, storyteller, verifier, repairer, recap, ask).
- **Azure Container Apps** (the Brain: REST, MCP, the agents, live matches) and **Container Apps Jobs** (simulator).
- **Azure Functions** (analyse, interpret, dispatch), **Event Grid**, **Cosmos DB change feed**, **Azure SignalR Service**, **Blob Storage**: an event-driven pipeline you can run and watch at `#pipeline`.
- **Azure Static Web Apps** (the web app), **Application Insights / OpenTelemetry**, **Key Vault** (provisioned), managed identities, **Bicep + azd**, GitHub Actions with OIDC, CodeQL and Dependabot.
- Availability test and four alerts (readiness, 5xx, CPU, restarts) in Bicep; `/ready` and `/api/ops`; an in-app **Operations** page.

### Enterprise readiness

Managed identities and role assignments instead of keys, a readiness endpoint, alerts, rate limits and a hard cap on live matches, four levels of graceful degradation (model text, repaired, template, no text), request and quality metrics, supply-chain scanning, and an honest list of limits in `docs/enterprise.md`.

### Scope

All data is synthetic, and the video feed is a synthetic stand-in for broadcast footage. A live match lives in one Brain replica's memory, so a restart ends it. The other known limits (the first live start after a deploy takes about 30 seconds, Key Vault is provisioned but not yet used, there is no end-user sign-in) are listed in `docs/enterprise.md`.

### How to try it (2 minutes)

1. Open the live site and click **Watch it live** on the start page, or **Live** in the menu. The first start may take up to 30 seconds.
2. Watch the moments and stories arrive. Switch viewer (top right) between analyst and casual, or language, and watch the next stories change.
3. Change the speed (bottom left). The match carries on from the same minute.
4. Open **Ask**, and ask "Who controlled the match?" or "How is the pressing going?".
5. **Cloud pipeline** (in the menu) runs the same match through Container Apps Job, Event Grid, Functions, the Brain and SignalR. **Operations** shows latency, errors and story quality, and **Architecture** has the figures.
6. **Replay** is the match center on a recorded match and has the evidence drawer, tactics and numbers tabs.

---

## Pitch (short, for the "Project Pitch" field)

Rifinitore is an AI insights engine for football studios and fans. It ingests synthetic match events as they happen, computes the numbers with code, and has Foundry agents (orchestrated with the Microsoft Agent Framework) pick the key moments and explain why they matter, personalised by viewer type, language, club and player. A verifier checks every claim against the data before it is shown, and a viewer can ask the match questions that are answered only from what has happened so far. It runs on Azure Container Apps, Functions, Event Grid, Cosmos DB, SignalR and Static Web Apps, deployed with Bicep and azd, with monitoring, alerts and an operations page. It solves the problem that a scoreline hides the story: every fan gets the match explained at their level, as it happens, in their language.
