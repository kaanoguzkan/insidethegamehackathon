"""The architecture figures (docs/img/architecture-*.svg), drawn from one place so the grid, the colours and the wording stay together.

    uv run python scripts/diagrams.py

Each figure makes one claim (its title) and is plain SVG: no script, no external font or image, a background of its own so it reads on a light or a dark page.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "docs" / "img"
FONT = "Archivo, 'Segoe UI', system-ui, -apple-system, sans-serif"
C = {
    "bg": "#0d1310", "panel": "#141c18", "panel2": "#1b2520", "line": "#3a4a41", "text": "#eef3ee", "muted": "#9fb0a5", "accent": "#f2c14e",
    "azure": "#4aa3ff", "ai": "#b392f0", "data": "#4fd1b0", "ok": "#5bd68a", "bad": "#ff7b7b", "dim": "#5d6e64",
}


# What moves is switched off for a reader who asks their system for less motion; the drawing is complete without it.
FX_DEFS = (
    '<filter id="glow" x="-20%" y="-30%" width="140%" height="160%"><feGaussianBlur stdDeviation="3.5" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>'
    "<style>.dash{animation:df 1.4s linear infinite}@keyframes df{to{stroke-dashoffset:-22}}@media (prefers-reduced-motion:reduce){.fx{display:none}.dash{animation:none}}</style>"
)


class Svg:
    def __init__(self, w: int, h: int, title: str, claim: str) -> None:
        self.w, self.h, self.title, self.claim = w, h, title, claim
        self.parts: list[str] = []
        self.markers: set[str] = set()
        self.fx: list[str] = []  # the moving parts (pulses along arrows, a glow that passes through stages), drawn over everything else
        self.flows = 0

    # ----- primitives -------------------------------------------------------------------------------
    def rect(self, x, y, w, h, *, fill="panel", stroke="line", r=10, sw=1.5, dash: str | None = None, opacity=1.0) -> None:  # noqa: ANN001
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{C.get(fill, fill)}" stroke="{C.get(stroke, stroke)}" stroke-width="{sw}"{d} opacity="{opacity}"/>')

    def text(self, x, y, s, *, size=12, weight=400, fill="text", anchor="start", halo=False) -> None:  # noqa: ANN001
        h = f' stroke="{C["bg"]}" stroke-width="4" paint-order="stroke" stroke-linejoin="round"' if halo else ""
        self.parts.append(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{C.get(fill, fill)}" text-anchor="{anchor}"{h}>{escape(s)}</text>')

    def box(self, x, y, w, h, title, lines, *, stroke="line", fill="panel2", tag=None, tag_fill=None, dash=None) -> None:  # noqa: ANN001
        self.rect(x, y, w, h, fill=fill, stroke=stroke, dash=dash)
        self.text(x + 12, y + 22, title, size=13.5, weight=700)
        for i, ln in enumerate(lines):
            self.text(x + 12, y + 42 + 17 * i, ln, size=11.5, fill="muted")
        if tag:
            tw = 7 * len(tag) + 14
            self.rect(x + w - tw - 8, y + 8, tw, 18, fill=tag_fill or stroke, stroke="none", r=9)
            self.text(x + w - tw / 2 - 8, y + 21, tag, size=10, weight=700, fill="bg", anchor="middle")

    def pill(self, cx, cy, s, *, stroke="line", fill="panel", color="text", size=11.5, weight=600) -> None:  # noqa: ANN001
        w = 6.6 * len(s) + 20
        self.rect(cx - w / 2, cy - 12, w, 24, fill=fill, stroke=stroke, r=12, sw=1.3)
        self.text(cx, cy + 4, s, size=size, weight=weight, fill=color, anchor="middle")

    def arrow(self, pts, *, color="muted", label=None, at=0.5, dash=None, sw=1.8, above=True, dx=0, dy=0, anchor="middle", flow=True) -> None:  # noqa: ANN001
        self.markers.add(color)
        d = f' stroke-dasharray="{dash}" class="dash"' if dash else ""
        p = " ".join(f"{x},{y}" for x, y in pts)
        self.parts.append(f'<polyline points="{p}" fill="none" stroke="{C.get(color, color)}" stroke-width="{sw}"{d} marker-end="url(#a-{color.lstrip("#")})" stroke-linejoin="round"/>')
        if flow and color != "dim":
            self.pulse(pts, color)
        if label:
            # label on the segment that holds ``at`` of the path length (by segment index when at is an int)
            seg = int(at) if isinstance(at, int) else 0
            (x1, y1), (x2, y2) = pts[seg], pts[seg + 1]
            f = 0.5 if isinstance(at, int) else at
            lx, ly = x1 + (x2 - x1) * f + dx, y1 + (y2 - y1) * f + (-7 if above else 16) + dy
            self.text(lx, ly, label, size=11, weight=600, fill=color if color in C and color not in ("muted", "line") else "text", anchor=anchor, halo=True)

    def pulse(self, pts, color) -> None:  # noqa: ANN001
        """A small light that travels along an arrow, over and over: what moves from one box to the next."""
        length = sum(((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False))
        dur = max(1.3, length / 105)
        begin = (self.flows * 0.43) % 3.1
        self.flows += 1
        path = "M" + " L".join(f"{x},{y}" for x, y in pts)
        col = C.get(color, color)
        for r, op in ((7, 0.2), (3.2, 0.95)):
            self.fx.append(f'<circle r="{r}" fill="{col}" opacity="{op}"><animateMotion dur="{dur:.2f}s" begin="{begin:.2f}s" repeatCount="indefinite" path="{path}"/></circle>')

    def glow(self, x, y, w, h, r, color, begin, dur) -> None:  # noqa: ANN001
        """A glow around a box that comes up and fades once per cycle; give the boxes of a row staggered ``begin`` and the light seems to run through them."""
        col = C.get(color, color) if color not in ("line", "dim") else C["accent"]
        self.fx.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="none" stroke="{col}" stroke-width="3" opacity="0" filter="url(#glow)">'
            f'<animate attributeName="opacity" values="0;0.95;0.2;0" keyTimes="0;0.07;0.2;1" dur="{dur}s" begin="{begin:.2f}s" repeatCount="indefinite"/></rect>'
        )

    def header(self, title, sub) -> None:  # noqa: ANN001
        self.text(40, 44, title, size=24, weight=800)
        self.text(40, 68, sub, size=13, fill="muted")

    def render(self) -> str:
        defs = "".join(
            f'<marker id="a-{c.lstrip("#")}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{C.get(c, c)}"/></marker>'
            for c in sorted(self.markers)
        )
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}" role="img" aria-label="{escape(self.claim)}" font-family="{FONT}">'
            f"<title>{escape(self.title)}</title><desc>{escape(self.claim)}</desc><defs>{defs}{FX_DEFS}</defs>"
            f'<rect width="{self.w}" height="{self.h}" fill="{C["bg"]}"/>' + "".join(self.parts) + '<g class="fx">' + "".join(self.fx) + "</g></svg>\n"
        )

    def save(self, name: str) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / name).write_text(self.render())
        print("wrote", OUT / name)


# ====================================================================================================
def fig_stages() -> None:
    s = Svg(1640, 900, "What runs where", "Rifinitore is one pipeline of five stages; code computes every number, models only choose and phrase, and each stage runs on named Azure services.")
    s.header("One match, five stages: what runs where", "Code computes every number; models only choose and phrase; a verifier checks every claim.")
    names = [("1", "Ingest", "code"), ("2", "Interpret", "code"), ("3", "Explain", "models"), ("4", "Render", "code"), ("5", "Personalize", "per viewer")]
    X = [40 + 320 * i for i in range(5)]
    W = 280
    for i, (n, name, kind) in enumerate(names):
        s.rect(X[i], 90, W, 46, fill="panel2", stroke="accent" if kind != "models" else "ai", r=23, sw=2)
        s.text(X[i] + 24, 120, n, size=18, weight=800, fill="accent")
        s.text(X[i] + 48, 120, name, size=17, weight=700)
        s.text(X[i] + W - 20, 119, kind, size=11, weight=700, fill="ai" if kind == "models" else "muted", anchor="end")
        s.glow(X[i], 90, W, 46, 23, "ai" if kind == "models" else "accent", i * 1.1, 7.0)
    pay = ["events + 5 Hz tracking", "evidence packs", "verified overlays"]
    for i, p in enumerate(pay):
        cx = X[i] + W + 20
        s.arrow([(cx - 18, 113), (cx + 18, 113)], color="accent", sw=2.2)
        s.pill(cx, 152, p, stroke="accent", color="accent", size=11)
    # the viewer decides what stage 3 writes and stage 4 shows
    s.arrow([(X[4] + 140, 90), (X[4] + 140, 80), (X[2] + 140, 80), (X[2] + 140, 88)], color="ai", dash="6 4", sw=1.8)
    s.text((X[4] + X[2] + 280) / 2, 76, "viewer cohort: one explanation per viewer type", size=11, weight=600, fill="ai", anchor="middle", halo=True)
    # what each stage is made of
    s.rect(30, 170, 1580, 332, fill="panel", stroke="line", r=14, sw=1)
    s.text(46, 194, "WHAT IT DOES", size=11, weight=800, fill="muted")
    cols = [
        [("Simulator", ["5 Hz agent-based match, 22 players + ball", "six clubs; managers react to the score,", "the clock, a red card and tired legs"], 84, "line"),
         ("Event feed", ["passes, shots, cards, restarts:", "who did what, and where"], 66, "line"),
         ("Video feed  →  Vision", ["rendered from tracking, read from pixels", "detect players + ball, track, rebuild", "tracking chunks (8-10 cm, measured)"], 84, "accent")],
        [("Physical analyzer", ["speeds, sprints, distance", "pass difficulty, shot speed", "reads tracking only"], 84, "line"),
         ("Interpreter", ["control vs chaos, pressure, rhythm", "xG, xT, win probability, shape", "z-scored vs league baselines"], 84, "line"),
         ("Moments + evidence packs", ["detect what matters;", "pack numbers, names, minute"], 66, "line")],
        [("Editor + Router", ["pick the moments, choose viewers"], 52, "ai"),
         ("Explainer · Composer", ["Foundry agents on gpt-6-luna", "one call per viewer, in parallel", "Microsoft Agent Framework workflow"], 84, "ai"),
         ("Verifier → Repairer → Template", ["every number, player, club checked", "fail: repair once, then a template", "nothing unchecked reaches a viewer"], 84, "ok")],
        [("Overlay producer", ["timed lower thirds, tickers,", "pitch graphics, stat cards"], 66, "line"),
         ("3D match center", ["humanoid players, 5 Hz tracking,", "evidence drawer, overlay-only page"], 66, "line"),
         ("Recaps + Ask the match", ["preview, half-time, full-time recaps", "Ask: 23 MCP tools, then verified"], 66, "line")],
        [("Viewer profile", ["analyst or casual", "English, Spanish, Turkish"], 66, "line"),
         ("Club and player", ["favourite club: tone changes,", "facts never do; focus player"], 66, "line"),
         ("Speed and position", ["1x, 5x, 10x while it plays;", "answers use only what you have seen"], 66, "line")],
    ]
    for i, col in enumerate(cols):
        y = 206
        for title, lines, h, st in col:
            s.box(X[i], y, W, h, title, lines, stroke=st)
            y += h + 12
    # on azure
    s.rect(30, 520, 1580, 232, fill="panel", stroke=C["azure"], r=14, sw=1.5)
    s.text(46, 544, "ON AZURE", size=11, weight=800, fill="azure")
    az = [
        [("Container Apps: the Brain", ["2 vCPU, always on; a live match is", "played, read and explained in-process"], "azure"),
         ("Jobs + Blob Storage", ["simulator job writes 5 s chunks;", "BlobCreated raises an Event Grid event"], "azure")],
        [("Event Grid → Functions", ["analyze · interpret · dispatch,", "each woken by the one before"], "azure"),
         ("Cosmos DB + change feed", ["events, moments, overlays; the change", "feed hands work from stage to stage"], "data")],
        [("Microsoft Foundry", ["8 registered agents + a hosted agent,", "evaluations, traces in the project"], "ai"),
         ("Beat cache (Cosmos DB)", ["same moment + same viewer type =", "instant verified text for the next viewer"], "data")],
        [("Azure SignalR", ["pushes each overlay to the page", "as soon as it is stored"], "azure"),
         ("Static Web Apps", ["match center, #ops, #pipeline,", "#architecture; GitHub Pages mirror"], "azure")],
        [("Managed identity", ["roles per service; no connection", "strings or keys in code or image"], "azure"),
         ("Guard rails", ["12 live matches at once, rate limits,", "429/503 with Retry-After"], "azure")],
    ]
    for i, col in enumerate(az):
        y = 558
        for title, lines, st in col:
            s.box(X[i], y, W, 84, title, lines, stroke=st, fill="panel2")
            y += 96
    # operate and ship
    s.rect(30, 770, 1580, 112, fill="panel", stroke="line", r=14, sw=1)
    s.text(46, 794, "OPERATE AND SHIP", size=11, weight=800, fill="muted")
    chips = [("App Insights + OpenTelemetry", "ok"), ("Availability test + 4 alerts", "ok"), ("/ready · /api/ops · #ops page", "ok"), ("Bicep + azd, one command", "azure"), ("GitHub Actions · OIDC · CodeQL · Dependabot", "azure"), ("Key Vault: provisioned, not used yet", "dim")]
    x = 46
    for label, st in chips:
        w = 6.7 * len(label) + 26
        s.rect(x, 808, w, 34, fill="panel2", stroke=st, r=17, sw=1.4, dash="5 4" if st == "dim" else None)
        s.text(x + w / 2, 830, label, size=12, weight=600, fill="muted" if st == "dim" else "text", anchor="middle")
        x += w + 12
    s.text(46, 868, "Operations page shows, live: requests, latency, how every story was made (model / repaired / template), claims verified, cache hits, live matches against capacity.", size=11.5, fill="muted")
    s.save("architecture-stages.svg")


# ====================================================================================================
def lane(s: Svg, y: int, nodes: list, labels: list[str], *, w: int = 150, gap: int = 50, h: int = 96, step: float = 0.45, cycle: float = 5.0) -> list[int]:
    """A row of boxes joined by labelled arrows; returns the x of each box."""
    xs = []
    for i, (title, lines, st) in enumerate(nodes):
        x = 40 + (w + gap) * i
        xs.append(x)
        s.box(x, y, w, h, title, lines, stroke=st)
        s.glow(x, y, w, h, 10, st, i * step, cycle)
    for i, lab in enumerate(labels):
        x1 = xs[i] + w
        s.arrow([(x1 + 2, y + h / 2), (x1 + gap - 3, y + h / 2)], color="accent", label=lab, dy=-1, sw=2)
    return xs


def fig_paths() -> None:
    s = Svg(1640, 740, "Two live paths", "The same stages run in two shapes: in one process for a viewer who is watching, or as events across Azure services for the cloud-native demonstration.")
    s.header("Two live paths, the same stages", "What changes is the transport between the stages, not the stages: in memory for the viewer's match, events across Azure for the cloud pipeline.")
    s.rect(30, 96, 1580, 250, fill="panel", stroke="accent", r=14, sw=1.5)
    s.text(46, 122, "WATCH LIVE   one viewer, one process, own clock (the match center's button)", size=12, weight=800, fill="accent")
    n1 = [("Match player", ["plays the demo at", "1x, 5x or 10x"], "line"), ("Video feed", ["render, detect, track;", "skips if it falls behind"], "accent"),
          ("Analyzer", ["speeds, sprints, pass", "difficulty, shot speed"], "line"), ("Interpreter", ["metrics, moments,", "evidence packs"], "line"),
          ("Dispatcher", ["one verified story per", "viewer; beat cache"], "line"), ("Foundry agents", ["Composer, Verifier", "gpt-6-luna"], "ai"),
          ("Session store", ["in memory: only what", "the clock has reached"], "data"), ("Browser", ["polls the feed ~0.7 s", "pitch and overlays"], "line")]
    xs1 = lane(s, 142, n1, ["chunks", "tracking", "facts", "moments", "evidence", "stories", "poll"], step=0.3, cycle=4.0)  # in memory: the light runs through quickly
    s.text(46, 282, "0 network hops between stages: every stage is a function call inside the Brain (Azure Container Apps, 2 vCPU).", size=12.5, weight=600)
    s.text(46, 304, "A viewer's match has its own store and clock, so nothing from their future can be in it. Measured on Azure: about 2 s from a moment to its story when warm.", size=12, fill="muted")
    s.text(46, 324, "Cost of the choice: a live match lives in one replica's memory, so the Brain is one always-on replica with at most 12 live matches.", size=12, fill="muted")

    s.rect(30, 440, 1580, 270, fill="panel", stroke=C["azure"], r=14, sw=1.5)
    s.text(46, 466, "CLOUD PIPELINE   event-driven across Azure services, one match at a time (#pipeline)", size=12, weight=800, fill="azure")
    n2 = [("Container Apps Job", ["plays the match,", "~20 s to start"], "azure"), ("Cosmos + Blob", ["events in Cosmos DB,", "5 s chunks in Blob"], "data"),
          ("Event Grid", ["BlobCreated wakes", "the analyzer"], "azure"), ("Functions", ["analyze, interpret,", "dispatch, push"], "azure"),
          ("Brain /beats", ["fast path: one verified", "story per viewer"], "azure"), ("Foundry agents", ["Composer, Verifier", "gpt-6-luna"], "ai"),
          ("Azure SignalR", ["pushes each overlay", "as it is stored"], "azure"), ("Browser", ["#pipeline page,", "stage counters"], "line")]
    xs2 = lane(s, 486, n2, ["events", "created", "trigger", "request", "calls", "stored", "push"], step=0.8, cycle=8.0)  # seven hops: it takes longer
    s.text(46, 626, "7 network hops: every stage is its own service that scales, retries and fails on its own, and hands the next one work through a change feed or an event.", size=12.5, weight=600)
    s.text(46, 648, "Slower to start and about 12 s from a moment to its story, but it is the production shape: events in, nothing shared in memory, the stages replaceable one by one.", size=12, fill="muted")
    s.parts.append(f'<circle cx="52" cy="665" r="5.5" fill="{C["accent"]}"/>')
    s.text(64, 669, "Same code in both lanes: the analyzer, the interpreter, the agents and the Verifier are imported by the Brain's stream session and by the Functions alike.", size=12, fill="muted")
    # the stages that are the same code in both lanes carry a gold dot
    for xs, idx in ((xs1, (2, 3, 4, 5)), (xs2, (3, 4, 5))):
        y0 = 142 if xs is xs1 else 486
        for i in idx:
            s.parts.append(f'<circle cx="{xs[i] + 150 - 14}" cy="{y0 + 14}" r="5.5" fill="{C["accent"]}"/>')
    s.save("architecture-paths.svg")


def fig_story() -> None:
    s = Svg(1640, 850, "A story's path", "A moment becomes a story only after a verifier has checked every number and name against the evidence; Ask a live match reads only what the viewer has seen.")
    s.header("How a story is made, and how a wrong one is stopped", "Code finds the moment and packs the evidence. A model phrases it for one viewer. A verifier decides whether it is shown.")
    y = 140
    s.box(40, y, 180, 100, "Moment detected", ["by code, from the event", "feed and the tracking"], stroke="line")
    s.box(262, y, 190, 100, "Evidence pack", ["numbers, players, minute:", "the only facts allowed"], stroke="data")
    s.box(494, y, 190, 100, "Beat cache", ["same moment + same", "viewer type already done?"], stroke="data")
    s.box(726, y, 200, 100, "Composer", ["Foundry agent, one call", "per viewer: mode, language,", "club, focus player"], stroke="ai")
    s.box(968, y, 190, 100, "Verifier", ["every number, name and", "club must be in the pack"], stroke="ok")
    s.arrow([(222, y + 50), (260, y + 50)], color="accent", label="pack", sw=2)
    s.arrow([(454, y + 50), (492, y + 50)], color="accent", label="look up", sw=2)
    s.arrow([(686, y + 50), (724, y + 50)], color="accent", label="miss", sw=2)
    s.arrow([(928, y + 50), (966, y + 50)], color="accent", label="draft", sw=2)
    # outcomes: the Verifier either passes the draft, sends it to the Repairer once, or the Template stands in
    ox, ow = 1290, 180
    s.box(ox, 96, ow, 74, "Passes", ["written by the model,", "shown as it is"], stroke="ok")
    s.box(ox, 196, ow, 74, "Repairer, once", ["cut or fix the claim", "that is not in the pack"], stroke="accent")
    s.box(ox, 296, ow, 74, "Template", ["rule-based text from", "the pack: always right"], stroke="line")
    s.arrow([(1160, 190), (1190, 190), (1190, 133), (ox - 2, 133)], color="ok")
    s.arrow([(1190, 190), (1190, 233), (ox - 2, 233)], color="accent")
    s.arrow([(1190, 190), (1190, 333), (ox - 2, 333)], color="dim", dash="5 4")
    s.text(ox - 8, 126, "all in pack", size=10.5, weight=700, fill="ok", anchor="end", halo=True)
    s.text(ox - 8, 226, "not in pack", size=10.5, weight=700, fill="accent", anchor="end", halo=True)
    s.text(ox - 8, 326, "model late", size=10.5, weight=700, fill="muted", anchor="end", halo=True)
    s.arrow([(ox + ow / 2, 270), (ox + ow / 2, 294)], color="bad", sw=1.6)
    s.text(ox + ow / 2 + 8, 286, "still fails", size=10.5, weight=700, fill="bad")
    s.box(1514, 187, 108, 92, "On screen", ["lower third", "on the 3D pitch"], stroke="accent")
    s.arrow([(ox + ow, 133), (1496, 133), (1496, 233), (1512, 233)], color="accent", sw=1.6)
    s.arrow([(ox + ow, 233), (1512, 233)], color="accent", sw=1.6)
    s.arrow([(ox + ow, 333), (1496, 333), (1496, 233)], color="accent", sw=1.6)
    s.arrow([(589, y), (589, 84), (1568, 84), (1568, 185)], color="data", dash="5 4", label="hit: instant verified text, the model is skipped", at=1, dy=-2)
    s.text(40, 392, "Counted on the Operations page: how many stories were model-written, repaired or templated, and how many claims were verified. A story is never silently wrong.", size=12, fill="muted")

    # Ask live
    s.rect(30, 430, 1580, 392, fill="panel", stroke="line", r=14, sw=1)
    s.text(46, 456, "ASK THE MATCH WHILE IT IS PLAYED   the answer can only use what you have already seen", size=12, weight=800, fill="accent")
    y2 = 480
    s.box(46, y2, 140, 84, "Question", ["typed or a chip"], stroke="line")
    s.box(228, y2, 200, 84, "Planner", ["picks up to 3 of 23 tools", "from an allow-list"], stroke="ai")
    s.box(470, y2, 260, 84, "Tools, run by code", ["MCP server over the match", "as seen at your position"], stroke="accent")
    s.box(772, y2, 200, 84, "Answerer", ["Foundry agent writes", "from the tool results only"], stroke="ai")
    s.box(1014, y2, 190, 84, "Verifier", ["same check as stories"], stroke="ok")
    s.box(1246, y2, 170, 84, "Answer", ["with the tools it used", "and a verified mark"], stroke="line")
    for x1, x2, lab in ((188, 226, "ask"), (430, 468, "plan"), (732, 770, "facts"), (974, 1012, "draft"), (1206, 1244, "ok")):
        s.arrow([(x1, y2 + 42), (x2, y2 + 42)], color="accent", label=lab, sw=2)
    # the timeline that makes it spoiler-proof
    tx0, tx1, ty = 120, 1500, 704
    s.text(46, 614, "WHAT THE TOOLS CAN SEE", size=12, weight=800)
    s.text(46, 634, "an interpreter rebuilt from only the documents", size=12, fill="muted")
    s.text(46, 652, "that had arrived by your position, never past the clock", size=12, fill="muted")
    s.rect(tx0, ty - 14, 760, 28, fill="data", stroke="none", r=6, opacity=0.35)
    s.rect(880, ty - 14, 200, 28, fill="panel2", stroke=C["dim"], r=6, dash="4 4")
    s.rect(1080, ty - 14, 420, 28, fill="bad", stroke="none", r=6, opacity=0.18)
    s.text(500, ty + 5, "used for answers", size=12, weight=700, fill="data", anchor="middle")
    s.text(980, ty + 5, "shown late", size=11, fill="muted", anchor="middle")
    s.text(1290, ty + 5, "never loaded: a goal or red card you have not seen", size=11.5, weight=600, fill="bad", anchor="middle")
    s.arrow([(880, ty - 40), (880, ty - 18)], color="accent", sw=2)
    s.text(880, ty - 46, "your position (the picture)", size=11.5, weight=700, fill="accent", anchor="middle", halo=True)
    s.arrow([(1080, ty + 46), (1080, ty + 18)], color="muted", sw=2)
    s.text(1080, ty + 62, "match clock on the server (the live edge)", size=11.5, weight=600, fill="muted", anchor="middle", halo=True)
    s.text(tx0, ty + 40, "kick-off", size=11, fill="muted", anchor="middle")
    s.text(tx1, ty + 40, "full time", size=11, fill="muted", anchor="end")
    s.arrow([(600, ty - 14), (600, 566)], color="accent", dash="5 4")
    s.text(612, 664, "read by the tools", size=11, weight=600, fill="accent")
    s.text(46, 806, "Checked on Azure: a red card at minute 45, the match clock at minute 4, the position forced to minute 133. The answer came from minute 4 and did not mention it.", size=12, fill="muted")
    s.save("architecture-story.svg")


def zone(s: Svg, x, y, w, h, title, stroke="line") -> None:  # noqa: ANN001
    s.rect(x, y, w, h, fill="panel", stroke=stroke, r=14, sw=1.3)
    s.text(x + 14, y + 22, title, size=11, weight=800, fill=stroke if stroke in C and stroke not in ("line", "dim") else "muted")


def badge(s: Svg, x, y, n, color="accent") -> None:  # noqa: ANN001
    s.parts.append(f'<circle cx="{x}" cy="{y}" r="10.5" fill="{C["bg"]}" stroke="{C.get(color, color)}" stroke-width="1.8"/>')
    s.text(x, y + 4, str(n), size=11.5, weight=800, fill=color, anchor="middle")


def fig_azure() -> None:
    s = Svg(1640, 990, "The Azure map", "Which Azure resources Rifinitore uses, which talk to which, and how it is operated and shipped.")
    s.header("The Azure map", "Eleven Azure services, one identity, one command to deploy. Numbers follow a match through the cloud pipeline.")
    zone(s, 40, 110, 200, 320, "CLIENT")
    s.box(56, 146, 168, 84, "Static Web Apps", ["match center, #ops,", "#pipeline, #architecture"], stroke="azure")
    s.box(56, 300, 168, 110, "Browser", ["React + three.js", "polls the feed,", "WebSocket for push"], stroke="line")
    zone(s, 280, 110, 360, 330, "AZURE CONTAINER APPS", "azure")
    s.box(296, 146, 328, 160, "The Brain", ["2 vCPU, always on, one replica", "REST API + MCP server (25 tools)", "live matches in memory (12 at most)", "Agent Framework agents + Verifier", "streams, Ask, Operations, vision"], stroke="azure")
    s.box(296, 322, 328, 102, "Container Apps Job", ["the simulator: plays a demo match", "into Cosmos DB and Blob Storage"], stroke="azure")
    zone(s, 280, 470, 360, 240, "AZURE FUNCTIONS (FLEX CONSUMPTION)", "azure")
    s.box(296, 506, 328, 184, "Event-driven stages", ["analyze: tracking chunk → physical facts", "interpret: change feed → moments", "dispatch: moment → the Brain's /beats", "push: stored overlay → SignalR", "negotiate: a SignalR token for the page"], stroke="azure")
    s.box(296, 740, 328, 84, "Azure SignalR Service", ["WebSocket push of each stored", "overlay (free tier, 20 connections)"], stroke="azure")
    zone(s, 720, 110, 330, 490, "DATA AND EVENTS", "data")
    s.box(736, 146, 298, 170, "Cosmos DB for NoSQL", ["events, moments, overlays, state", "beats: shared cache of verified text", "(a repeated moment is instant)", "change feed hands work between", "the Functions, stage to stage"], stroke="data")
    s.box(736, 332, 298, 86, "Blob Storage", ["frames: the 5 s tracking chunks", "checkpoints, packs, replay files"], stroke="data")
    s.box(736, 436, 298, 70, "Event Grid system topic", ["BlobCreated on the frames container"], stroke="azure")
    zone(s, 1090, 110, 510, 220, "AI", "ai")
    s.box(1106, 146, 478, 164, "Microsoft Foundry project (Sweden Central)", ["gpt-6-luna: the model every agent uses", "8 registered prompt agents + a hosted agent", "evaluations of the text; agent traces in the project", "reached with the Brain's managed identity: no key"], stroke="ai")
    zone(s, 720, 630, 880, 160, "OPERATE", "ok")
    s.box(736, 666, 260, 104, "App Insights + OpenTelemetry", ["traces and metrics from the", "Brain and Functions; a span per", "agent call and verification"], stroke="ok")
    s.box(1012, 666, 300, 104, "Availability test + alerts", ["a test on /ready from 2 regions;", "alerts: readiness, 5xx, CPU, restarts", "→ an action group (email)"], stroke="ok")
    s.box(1328, 666, 256, 104, "Key Vault", ["provisioned, not used yet:", "the two operator keys are still", "Container Apps secrets"], stroke="dim", dash="5 4")
    s.rect(720, 804, 880, 38, fill="panel2", stroke=C["azure"], r=19, sw=1.3)
    s.text(1160, 828, "One user-assigned managed identity: roles for Blob, Queue, Table, Cosmos data, registry pull and SignalR. No keys in code or image.", size=12, weight=600, anchor="middle")
    # flows
    s.arrow([(140, 232), (140, 298)], color="accent")
    badge(s, 140, 265, 1)
    s.arrow([(224, 360), (256, 360), (256, 226), (294, 226)], color="accent")
    badge(s, 256, 300, 2)
    s.arrow([(460, 146), (460, 92), (1340, 92), (1340, 144)], color="ai")
    badge(s, 900, 92, 3, "ai")
    s.text(930, 96, "agent calls", size=11, weight=600, fill="ai", halo=True)
    s.arrow([(626, 230), (734, 230)], color="data")
    badge(s, 680, 230, 4, "data")
    s.arrow([(626, 375), (734, 375)], color="data")
    badge(s, 708, 375, 5, "data")
    s.arrow([(885, 418), (885, 434)], color="azure")
    badge(s, 912, 426, 6, "azure")
    s.arrow([(734, 470), (700, 470), (700, 560), (626, 560)], color="azure")
    badge(s, 700, 515, 7, "azure")
    s.arrow([(626, 520), (672, 520), (672, 262), (734, 262)], color="data")
    s.arrow([(734, 280), (684, 280), (684, 532), (626, 532)], color="data", sw=1.4)
    badge(s, 678, 322, 8, "data")
    s.arrow([(296, 650), (268, 650), (268, 266), (294, 266)], color="azure")
    badge(s, 268, 460, 9, "azure")
    s.arrow([(460, 692), (460, 738)], color="ok")
    s.arrow([(296, 790), (140, 790), (140, 412)], color="ok")
    badge(s, 460, 715, 10, "ok")
    badge(s, 140, 600, 10, "ok")
    # reading the arrows
    zone(s, 1090, 350, 510, 266, "FOLLOW ONE MATCH THROUGH THE CLOUD PIPELINE")
    steps = [
        (1, "serves the app; the page asks the Brain to start a match"), (2, "the page starts a match, polls the feed, asks questions (REST)"),
        (3, "the Brain calls the Foundry agents to write and verify stories"), (4, "verified text is shared: the next viewer's identical moment is instant"),
        (5, "the job writes 5 s tracking chunks into Blob Storage"), (6, "each new chunk raises a BlobCreated event"),
        (7, "Event Grid wakes the analyze Function"), (8, "events in Cosmos DB wake interpret, then dispatch (change feed)"),
        (9, "dispatch asks the Brain for the story of each new moment"), (10, "push sends each stored overlay through SignalR to the page"),
    ]
    for i, (n, t) in enumerate(steps):
        yy = 398 + i * 20
        badge(s, 1114, yy - 4, n, "accent")
        s.text(1134, yy, t, size=11.5, fill="text")
    # ship
    zone(s, 40, 866, 1560, 104, "SHIP")
    chips = [("git push", "line"), ("GitHub Actions: CI, CodeQL, Dependabot", "azure"), ("azd + Bicep, OIDC login (no stored secrets)", "azure"), ("Container Registry", "azure"), ("Container Apps · Functions · Static Web Apps", "azure")]
    x = 56
    for i, (label, st) in enumerate(chips):
        w = 7.0 * len(label) + 28
        s.rect(x, 898, w, 50, fill="panel2", stroke=st, r=12, sw=1.4)
        s.text(x + w / 2, 928, label, size=12.5, weight=600, anchor="middle")
        if i < len(chips) - 1:
            s.arrow([(x + w + 3, 923), (x + w + 22, 923)], color="accent", sw=2)
        x += w + 26
    s.save("architecture-azure.svg")


if __name__ == "__main__":
    fig_stages()
    fig_paths()
    fig_story()
    fig_azure()
