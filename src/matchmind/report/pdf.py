"""Build the match report PDF from a replay package (``meta.json``, ``analytics.json``, ``moments.json`` ...).

The report is deterministic: every sentence is assembled from numbers in the package, so it can be rebuilt at any
time and never says anything the data does not. It has seven parts: the story of the match, the tactics in every
phase of play, every position and the player in it, the analytics views, every player's numbers, the other
formations for comparison and what to trust.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Rect
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Flowable,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents

from ..sim import tactics as TA
from . import content as C
from . import draw as D

PAGE_W, PAGE_H = A4
MARGIN = 16 * mm
CW = PAGE_W - 2 * MARGIN  # content width in points
INK = colors.HexColor("#14201a")
MUTED = colors.HexColor("#5d6b63")
RULE = colors.HexColor("#c9d1cc")
ZEBRA = colors.HexColor("#f4f6f4")
GOLD = colors.HexColor("#f2c14e")
DEEP = colors.HexColor("#14532d")

PHASE_COLORS = {
    "build": colors.HexColor("#6aa7d8"),
    "attack": colors.HexColor("#3f8f5f"),
    "press": colors.HexColor("#e08a3c"),
    "block": colors.HexColor("#8a8f98"),
    "low": colors.HexColor("#4b4f58"),
}

ST = {
    "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=27, leading=31, textColor=INK, spaceAfter=4),
    "sub": ParagraphStyle("sub", fontName="Helvetica", fontSize=12, leading=16, textColor=MUTED, spaceAfter=10),
    "h1": ParagraphStyle("h1", keepWithNext=1, fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=INK, spaceBefore=2, spaceAfter=6),
    "h2": ParagraphStyle("h2", keepWithNext=1, fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=DEEP, spaceBefore=10, spaceAfter=4),
    "h3": ParagraphStyle("h3", keepWithNext=1, fontName="Helvetica-Bold", fontSize=9.5, leading=13, textColor=INK, spaceBefore=6, spaceAfter=2),
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.3, leading=13.2, textColor=INK, alignment=TA_LEFT, spaceAfter=5),
    "what": ParagraphStyle("what", keepWithNext=1, fontName="Helvetica-Oblique", fontSize=8.8, leading=12.4, textColor=MUTED, spaceAfter=6, leftIndent=8, borderPadding=0),
    "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=11, textColor=MUTED),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.2, leading=10.6, textColor=INK),
    "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.2, leading=10.6, textColor=INK),
    "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.3, leading=13.2, textColor=INK, leftIndent=11, bulletIndent=0, spaceAfter=3),
    "toc1": ParagraphStyle("toc1", fontName="Helvetica", fontSize=10.5, leading=17, leftIndent=0, textColor=INK),
}


def P(text: str, style: str = "body") -> Paragraph:
    return Paragraph(text, ST[style])


def esc(s) -> str:
    return escape(str(s)).replace("→", "to").replace("′", "'").replace("’", "'")


def pc(v, d: int = 0) -> str:
    return "n/a" if v is None else f"{v * 100:.{d}f}%"


def f1(v, d: int = 1) -> str:
    return "n/a" if v is None else f"{v:.{d}f}"


def mmss(ms: float) -> str:
    return f"{int(ms // 60000)}:{int(ms % 60000 // 1000):02d}"


class Rule(Flowable):
    def __init__(self, width: float, color=GOLD, thickness: float = 2.2):
        super().__init__()
        self.width, self.color, self.thickness = width, color, thickness
        self.height = thickness + 2

    def draw(self):
        self.canv.setStrokeColor(self.color)
        self.canv.setLineWidth(self.thickness)
        self.canv.line(0, 1, self.width, 1)


def table(rows: list[list], widths: list[float], header: bool = True, align_right_from: int = 1, font: float = 8.2, zebra: bool = True, left: tuple = ()) -> Table:
    cells = []
    for r, row in enumerate(rows):
        out = []
        for c, v in enumerate(row):
            if isinstance(v, (Flowable, Paragraph)):
                out.append(v)
            else:
                style = ParagraphStyle("c", parent=ST["cellb" if (header and r == 0) else "cell"], fontSize=font, leading=font + 2.4, alignment=2 if (c >= align_right_from and align_right_from >= 0 and c not in left) else 0)
                out.append(Paragraph(esc(v), style))
        cells.append(out)
    t = Table(cells, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("LINEBELOW", (0, 0), (-1, -1), 0.3, RULE),
    ]
    if header:
        style += [("LINEBELOW", (0, 0), (-1, 0), 0.9, INK), ("TEXTCOLOR", (0, 0), (-1, 0), INK)]
    if zebra:
        style += [("ROWBACKGROUNDS", (0, 1 if header else 0), (-1, -1), [colors.white, ZEBRA])]
    t.setStyle(TableStyle(style))
    t.spaceAfter = 7
    return t


class ReportDoc(BaseDocTemplate):
    def __init__(self, path: str, title: str, footer: str, **kw):
        super().__init__(path, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=22 * mm, bottomMargin=18 * mm, title=title, author="MatchMind", subject="Match report", **kw)
        self._title, self._footer = title, footer
        self.addPageTemplates([PageTemplate(id="p", frames=[Frame(MARGIN, 18 * mm, CW, PAGE_H - 40 * mm, id="f", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)], onPage=self._decorate)])

    def _decorate(self, canv, doc):
        canv.saveState()
        if doc.page > 1:
            canv.setFont("Helvetica-Bold", 8)
            canv.setFillColor(INK)
            canv.drawString(MARGIN, PAGE_H - 12 * mm, "MatchMind")
            canv.setFont("Helvetica", 8)
            canv.setFillColor(MUTED)
            canv.drawRightString(PAGE_W - MARGIN, PAGE_H - 12 * mm, self._title)
            canv.setStrokeColor(GOLD)
            canv.setLineWidth(1.4)
            canv.line(MARGIN, PAGE_H - 14 * mm, MARGIN + 18 * mm, PAGE_H - 14 * mm)
        canv.setFont("Helvetica", 7.5)
        canv.setFillColor(MUTED)
        canv.drawString(MARGIN, 10 * mm, self._footer)
        canv.drawRightString(PAGE_W - MARGIN, 10 * mm, f"{doc.page}")
        canv.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph) and flowable.style.name == "h1":
            text = flowable.getPlainText()
            key = f"h1-{self.seq.nextf('h1')}"
            self.canv.bookmarkPage(key)
            self.notify("TOCEntry", (0, text, self.page, key))


# ------------------------------------------------------------------------------------------------------------------------


class Data:
    """The replay package, loaded once, with the lookups the report keeps needing."""

    def __init__(self, package: Path):
        rd = lambda n: json.loads((package / n).read_text())  # noqa: E731
        self.meta = rd("meta.json")
        self.a = rd("analytics.json")
        self.moments = rd("moments.json")
        self.events = rd("events.json")
        self.recaps = rd("recaps.json") if (package / "recaps.json").exists() else []
        self.home, self.away = self.meta["home"], self.meta["away"]
        self.clubs = [self.home["id"], self.away["id"]]
        self.team = {self.home["id"]: self.home, self.away["id"]: self.away}
        self.players = {}
        for t in (self.home, self.away):
            for pid, p in t["players"].items():
                self.players[pid] = {**p, "team": t["id"]}
        self.rows = {r["id"]: r for r in self.a["players"]}
        self.end_ms = int(max((e["clock"]["matchMs"] for e in self.events), default=0)) or self.meta["periods"][-1]["endMs"]
        p2 = next((p for p in self.meta["periods"] if p["period"] == 2), None)
        self.p2_start = p2["startMs"] if p2 else None
        self.colors = {c: self.team[c]["colors"]["primary"] for c in self.clubs}

    def name(self, pid) -> str:
        return self.players.get(pid, {}).get("name", str(pid))

    def short(self, club) -> str:
        return self.team[club]["short"]

    def label(self, ms: float) -> str:
        """The match clock as the app shows it: 23', 45+2', 90+1'."""
        if self.p2_start is not None and ms >= self.p2_start:
            m = 45 + int((ms - self.p2_start) // 60000)
            return f"{m}'" if m < 90 else f"90+{m - 89}'"
        m = int(ms // 60000)
        return f"{m}'" if m < 45 else f"45+{m - 44}'"

    def formation_changes(self, club) -> list[dict]:
        return [e for e in self.events if e["type"] == "formation_change" and e["team"] == club]


# ----- sections --------------------------------------------------------------------------------------------------------


def cover(d: Data, story: list) -> None:
    h, a = d.home, d.away
    score = d.meta["score"]
    story += [Spacer(1, 18 * mm), Rule(46 * mm, GOLD, 4), Spacer(1, 6)]
    story += [P("Match report", "sub"), P(f"{esc(h['name'])} {score[h['id']]} - {score[a['id']]} {esc(a['name'])}", "title")]
    scen = d.meta.get("scenario")
    story += [P(f"{esc(d.meta['league'])}. Synthetic match {esc(d.meta['matchId'])}" + (f", scenario {esc(scen)}" if scen else "") + f". Report built {date.today().isoformat()}.", "sub")]
    band = Drawing(CW, 10)
    band.add(Rect(0, 0, CW / 2, 10, fillColor=D._hex(h["colors"]["primary"]), strokeColor=None))
    band.add(Rect(CW / 2, 0, CW / 2, 10, fillColor=D._hex(a["colors"]["primary"]), strokeColor=None))
    story += [band, Spacer(1, 10)]

    sh = d.a["shots"]["teams"]
    wp = d.a["winProbability"]
    potm = d.a.get("playerOfTheMatch")
    bullets = []
    bullets.append(f"<b>Result.</b> {esc(h['short'])} {score[h['id']]} - {score[a['id']]} {esc(a['short'])}. Shots {sh[h['id']]['shots']} to {sh[a['id']]['shots']}, expected goals {sh[h['id']]['xg']:.2f} to {sh[a['id']]['xg']:.2f}.")
    if wp.get("swings"):
        s = max(wp["swings"], key=lambda s: s["swing"])
        bullets.append(f"<b>Biggest swing.</b> The {'goal' if s['kind'] == 'goal' else 'sending-off'} at {d.label(s['matchMs'])} moved the odds by {round(s['swing'] * 100)} points.")
    if potm:
        bullets.append(f"<b>Player of the match.</b> {esc(potm['name'])} ({esc(d.short(potm['team']))}, {esc(potm['pos'])}) by possession value, {potm['value']:+.2f}.")
    for c in d.clubs:
        ph = d.a.get("phases", {}).get(c)
        if ph:
            top = max(C.PHASES, key=lambda p: ph["share"].get(p, 0))
            bullets.append(f"<b>{esc(d.short(c))}</b> played a {esc(d.team[c]['startFormation'])}; it spent most of the match in {esc(C.PHASE_TEXT[top][0].lower())} ({pc(ph['share'][top])} of the time).")
    story += [P("At a glance", "h2")] + [Paragraph(b, ST["bullet"], bulletText="•") for b in bullets]

    full = next((r for r in d.recaps if r["kind"] == "full_time" and r["cohort"].startswith("analyst/en/neutral")), None)
    if full:
        story += [P("The match in the system's words", "h2"), P(esc(full["summary"]))]

    story += [P("How to read this report", "h2"), P("Each part opens with a line in italics saying what the numbers measure, then shows what this match produced. Part 1 tells the story; part 2 shows how each team's shape changed with and without the ball; part 3 explains every position and who played it; part 4 goes through the analytics views one by one; part 5 lists every player; part 6 compares all nine formations; part 7 says how far to trust each number."),
              Spacer(1, 4)]
    toc = TableOfContents()
    toc.levelStyles = [ST["toc1"]]
    toc.dotsMinLevel = 0
    story += [P("Contents", "h2"), toc, PageBreak()]


def story_section(d: Data, story: list) -> None:
    story += [P("1. The story of the match", "h1"), Rule(CW, RULE, 0.6), Spacer(1, 4)]
    a, h, aw = d.a, d.home, d.away
    story += [P("Win probability", "h2"), P(C.WHAT["win"], "what")]
    wp = a["winProbability"]
    story += [D.win_probability_chart(CW, 100, wp["series"], wp["swings"], d.end_ms, d.p2_start, h, aw)]
    legend = Table([[Drawing(8, 8), P(f"{esc(h['short'])} win", "small"), Drawing(8, 8), P("Draw", "small"), Drawing(8, 8), P(f"{esc(aw['short'])} win", "small")]], colWidths=[12, 80, 12, 60, 12, 80])
    for i, col in ((0, D._hex(h["colors"]["primary"])), (2, colors.HexColor("#b9bfbb")), (4, D._hex(aw["colors"]["primary"]))):
        legend._cellvalues[0][i].add(Rect(0, 0, 8, 8, fillColor=col, strokeColor=None))
    story += [Spacer(1, 3), legend]
    if wp.get("preMatch") and wp.get("final"):
        pm, fn = wp["preMatch"], wp["final"]
        story += [P(f"Before kick-off the model gave {esc(h['short'])} {pc(pm['home'])}, a draw {pc(pm['draw'])} and {esc(aw['short'])} {pc(pm['away'])}. At full time: {pc(fn['home'])}, {pc(fn['draw'])}, {pc(fn['away'])}.")]
    if wp["swings"]:
        rows = [["Minute", "Event", f"{h['short']}", "Draw", f"{aw['short']}"]]
        for s in wp["swings"]:
            b, af = s["before"], s["after"]
            rows.append([d.label(s["matchMs"]), "Goal" if s["kind"] == "goal" else "Red card", f"{pc(b['home'])} to {pc(af['home'])}", f"{pc(b['draw'])} to {pc(af['draw'])}", f"{pc(b['away'])} to {pc(af['away'])}"])
        story += [P("What moved the odds", "h3"), table(rows, [50, 70, 128, 128, 128], align_right_from=2)]

    story += [P("Key moments", "h2"), P("The moments the system judged worth telling, with the reason and what it means. Salience is how much a moment deserves attention (0 to 1).", "what")]
    shown = sorted((m for m in d.moments if m["salience"] >= 0.55), key=lambda m: m["detectedAt"]["matchMs"])
    rows = [["Minute", "Moment", "Team", "Why it matters"]]
    for m in shown[:14]:
        ex = m.get("explanation") or {}
        txt = ex.get("so_what") or ex.get("why") or ex.get("what") or ""
        team = d.short(m["subjectTeam"]) if m.get("subjectTeam") in d.team else ""
        rows.append([m["detectedAt"]["label"], m["type"].replace("_", " ").capitalize(), team, P(esc(txt), "cell")])
    story += [table(rows, [38, 92, 52, CW - 182], align_right_from=-1)]

    story += [P("Expected goals through the match", "h2"), P("Cumulative expected goals for each team; steps are shots.", "what")]
    story += [D.xg_race_chart(CW, 75, a["shots"]["race"], d.end_ms, d.p2_start, h, aw)]
    story += [PageBreak()]


def _slots(formation: str, phase: str, style: dict) -> list[tuple[str, float, float]]:
    roles = TA.roles(formation)
    if phase == "attack":
        lay = TA.apply_attack_tags(formation, TA.layout(formation, "attack"), style)
    elif phase == "build":
        lay = TA.apply_attack_tags(formation, TA.layout(formation, "build"), style, build=True)
    else:
        lay = TA.layout(formation, phase)
    return [(r, dpt, w) for r, (dpt, w) in zip(roles, lay, strict=True)]


def tactics_section(d: Data, story: list) -> None:
    story += [P("2. Tactics: the same team with and without the ball", "h1"), Rule(CW, RULE, 0.6), Spacer(1, 4)]
    story += [P("A formation is not one shape. Teams change shape with the ball, and how they press and how they behave in the seconds after winning or losing it depends on the shape they start from. Each team below is shown in six shapes: its nominal formation and the five working phases. The drawings are schematics, attacking left to right.", "body")]
    for c in d.clubs:
        t = d.team[c]
        style = t["style"]
        name = t.get("startFormation") or t["formation"]
        story += [CondPageBreak(150 * mm), P(f"{esc(t['name'])}: {esc(name)}", "h2"), P(esc(t["shapes"].get("blurb", "")).capitalize() + ".", "small"), Spacer(1, 3)]
        ch = d.formation_changes(c)
        if ch:
            story += [P("<b>Formation changes:</b> " + "; ".join(f"{esc(e['attributes']['previous'])} to {esc(e['attributes']['formation'])} at {d.label(e['clock']['matchMs'])}" for e in ch) + ".", "small")]
        gw = (CW - 12) / 3
        cells = []
        sub = {"base": "nominal", "build": t["shapes"]["build"], "attack": t["shapes"]["attack"], "press": t["shapes"]["press"], "block": t["shapes"]["block"], "low": "compact"}
        names = {"base": "Nominal", **{p: C.PHASE_TEXT[p][0] for p in C.PHASES}}
        for ph in ("base", "build", "attack", "press", "block", "low"):
            cells.append(D.shape_diagram(gw, _slots(name, ph, style), t["colors"]["primary"], t["colors"]["secondary"], names[ph], sub[ph]))
        grid = Table([cells[:3], cells[3:]], colWidths=[gw + 6] * 3)
        grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 0)]))
        story += [grid]
        story += [P(f"<b>Rest defence.</b> While the team attacks, {esc(t['shapes']['rest'])} stay behind the ball as cover against a counter.", "body")]

        ph = d.a.get("phases", {}).get(c)
        if ph:
            story += [P("Time in each phase", "h3")]
            tl = D.phase_timeline(CW, ph["segments"], d.end_ms, t["colors"]["primary"], PHASE_COLORS, list(TA.PHASES))
            story += [tl]
            rows = [["Phase", "Share", "Entered", "Line height", "Length", "Width", "What usually sets it off"]]
            for p in C.PHASES:
                m = ph["measured"].get(p, {})
                causes = ph["causes"].get(p, {})
                top = ", ".join(f"{C.CAUSES.get(k, k)} ({v})" for k, v in sorted(causes.items(), key=lambda kv: -kv[1])[:2])
                rows.append([C.PHASE_TEXT[p][0], pc(ph["share"][p]), ph["entries"][p], f"{m['lineHeightM']:.0f} m" if m else "n/a", f"{m['lengthM']:.0f} m" if m else "n/a", f"{m['widthM']:.0f} m" if m else "n/a", P(esc(top or "n/a"), "cell")])
            story += [table(rows, [64, 36, 40, 52, 42, 40, CW - 274], align_right_from=1, left=(6,)), Spacer(1, 3)]
            story += [P("Line height is the average distance of the four deepest outfield players from their own goal, length the distance between the deepest and highest outfield player, width the distance between the widest two. Each is averaged over the time the team spent in that phase.", "small")]

        sp = d.a["shapes"].get(c, {})
        dm, im = (sp.get("def", {}) or {}).get("measured"), (sp.get("ip", {}) or {}).get("measured")
        if dm or im:
            story += [P(f"<b>Designed against measured.</b> Designed: {esc(t['shapes']['block'])} out of possession, {esc(t['shapes']['attack'])} in possession. Measured from the average positions: {esc(dm['label']) if dm else 'n/a'} out of possession, {esc(im['label']) if im else 'n/a'} in possession.", "body")]

        rows = [["Tactic", "Setting", "What it means"]]
        for k in C.TAG_ORDER:
            v = style.get(k)
            rows.append([k.replace("_", " ").capitalize(), str(v), P(esc(C.TAG_TEXT[k].get(str(v), "")), "cell")])
        story += [P("How the club plays it", "h3"), table(rows, [78, 58, CW - 136], align_right_from=-1)]
        dials = [("Press intensity", style["press_intensity"]), ("Press height", style["press_height"]), ("Line height", style["line_height"]), ("Width", style["width"]), ("Tempo", style["tempo"]), ("Directness", style["directness"]), ("Counter bias", style["counter_bias"])]
        story += [Spacer(1, 4), P("Style dials (0 to 1): " + ", ".join(f"{esc(n.lower())} {v:.2f}" for n, v in dials) + ".", "small")]
    story += [P("The five phases", "h2")]
    for p in C.PHASES:
        story += [P(f"<b>{C.PHASE_TEXT[p][0]}.</b> {esc(C.PHASE_TEXT[p][1])}", "body")]
    story += [PageBreak()]


def positions_section(d: Data, story: list) -> None:
    story += [P("3. Every position, and who played it", "h1"), Rule(CW, RULE, 0.6), Spacer(1, 4)]
    story += [P("For each of the eleven places in the team: the job in general, what this club asks of it, and the numbers of the player who filled it. Value is possession value: the change in the chance of scoring minus the chance of conceding that the player's actions created.", "what")]
    for c in d.clubs:
        t = d.team[c]
        name = t.get("startFormation") or t["formation"]
        roles = ["GK"] + TA.roles(name)
        lineup = t["lineup"]
        story += [P(f"{esc(t['name'])}: {esc(name)}", "h2")]
        rows = [["Position", "Player", "In possession", "Out of possession"]]
        for role, pid in zip(roles, lineup, strict=False):
            g = C.POSITIONS[role]
            pl = d.players.get(pid, {})
            r = d.rows.get(pid, {})
            listed = pl.get("pos")
            nm = f"<b>{esc(pl.get('name', pid))}</b> #{pl.get('number', '')}"
            if listed and listed != role:
                nm += f"<br/><font size=7 color='#9a5b00'>listed {esc(listed)}, plays {role}</font>"
            stats = []
            if r:
                if r.get("minutes"):
                    stats.append(f"{r['minutes']:.0f} min")
                if r.get("passes"):
                    stats.append(f"{r['passesComplete']}/{r['passes']} passes")
                for k, lab in (("goals", "goals"), ("assists", "assists"), ("tackles", "tackles"), ("interceptions", "interceptions"), ("pressures", "pressures")):
                    if r.get(k):
                        stats.append(f"{r[k]} {lab}")
                if r.get("value") is not None:
                    stats.append(f"value {r['value']:+.2f}")
                if r.get("km"):
                    stats.append(f"{r['km']:.1f} km")
            nm += "<br/><font size=7 color='#5d6b63'>" + esc(", ".join(stats)) + "</font>"
            note = C.role_note(role, t["style"])
            rows.append([P(f"<b>{role}</b><br/><font size=7 color='#5d6b63'>{esc(g['name'])}</font>", "cell"), P(nm, "cell"), P(esc(g["in"]) + (f" <b>This club:</b> {esc(note)}" if note else ""), "cell"), P(esc(g["out"]), "cell")])
        story += [table(rows, [64, 108, (CW - 172) * 0.52, (CW - 172) * 0.48], align_right_from=-1, font=7.8), Spacer(1, 8)]
    story += [PageBreak()]


def _team_pair(d: Data, label: str, vals: list, fmt=lambda v: str(v)) -> list:
    return [label, fmt(vals[0]), fmt(vals[1])]


def analytics_section(d: Data, story: list) -> None:
    a, h, aw = d.a, d.home, d.away
    hc, ac = h["id"], aw["id"]
    story += [P("4. The analytics, view by view", "h1"), Rule(CW, RULE, 0.6), Spacer(1, 4)]
    w3 = [CW - 140, 70, 70]

    # shots
    sh = a["shots"]
    story += [P("Shots and expected goals", "h2"), P(C.WHAT["shots"], "what")]
    rows = [["", h["short"], aw["short"]]]
    for lab, key, fmt in (("Shots", "shots", str), ("On target", "onTarget", str), ("Goals", "goals", str), ("Expected goals (xG)", "xg", lambda v: f"{v:.2f}"), ("Post-shot xG (xGOT)", "xgot", lambda v: f"{v:.2f}"), ("Big chances", "bigChances", str)):
        rows.append(_team_pair(d, lab, [sh["teams"][hc][key], sh["teams"][ac][key]], fmt))
    story += [table(rows, w3)]
    shots = sh["shots"]
    if shots:
        best = max(shots, key=lambda s: s["xg"])
        story += [P(f"The best chance was {esc(d.name(best['player']))}'s ({esc(d.short(best['team']))}, {d.label(best['ms'])}), worth {best['xg']:.2f} xG and {'scored' if best['outcome'] == 'goal' else best['outcome']}.", "body")]
        goals = sum(1 for s in shots if s["outcome"] == "goal")
        story += [D.shot_map(CW * 0.5, shots, d.colors, {}), P(f"Shot map: both teams are drawn attacking the right-hand goal. Bigger circle, bigger chance; a solid circle is a goal ({goals} in this match).", "small")]

    # value
    pv = a["possessionValue"]
    story += [P("Possession value: the actions that mattered", "h2"), P(C.WHAT["value"], "what")]
    if pv.get("available") and pv.get("best"):
        rows = [["Minute", "Player", "Team", "Action", "Value"]]
        for r in pv["best"][:6]:
            rows.append([d.label(r["ms"]), r["name"] or d.name(r["player"]), d.short(r["team"]), r["type"].replace("_", " "), f"{r['value']:+.3f}"])
        story += [table(rows, [44, 140, 70, CW - 304, 50], align_right_from=4)]
        top = sorted((r for r in a["players"] if r.get("value") is not None), key=lambda r: -r["value"])[:5]
        story += [P("Most valuable players: " + ", ".join(f"{esc(r['name'])} ({r['value']:+.2f})" for r in top) + ".", "body")]

    # space
    sp = a["space"]["teams"]
    story += [P("Space and pitch control", "h2"), P(C.WHAT["space"], "what")]
    rows = [["", h["short"], aw["short"]]]
    rows += [["Pitch control share", pc(sp[hc]["controlShare"]), pc(sp[ac]["controlShare"])], ["Final-third control", pc(sp[hc]["finalThirdControl"]), pc(sp[ac]["finalThirdControl"])],
             ["Defensive block area (m2)", f1(sp[hc].get("blockAreaM2"), 0), f1(sp[ac].get("blockAreaM2"), 0)], ["Space behind the line (m2)", f1(sp[hc]["spaceBehindM2"], 0), f1(sp[ac]["spaceBehindM2"], 0)]]
    story += [table(rows, w3)]
    story += [D.versus_bar(CW, sp[hc]["controlShare"] or 0.5, sp[ac]["controlShare"] or 0.5, h["colors"]["primary"], aw["colors"]["primary"])]

    # line breaks
    lb = a["lineBreaks"]
    story += [P("Packing and line-breaking passes", "h2"), P(C.WHAT["breaks"], "what")]
    rows = [["", h["short"], aw["short"]]]
    for lab, key in (("Completed forward passes counted", "completed"), ("Opponents bypassed (packing)", "packing"), ("Passes through a line", "lineBreaks"), ("Passes through all three lines", "threeLines")):
        rows.append(_team_pair(d, lab, [lb["teams"][hc][key], lb["teams"][ac][key]]))
    story += [table(rows, w3)]
    if lb["best"]:
        b = lb["best"][0]
        story += [P(f"The most damaging pass: {esc(b['player'] if ' ' in str(b['player']) else d.name(b['player']))} to {esc(d.name(b['receiver']) if b.get('receiver') else 'a teammate')} at {d.label(b['ms'])} took {b['bypassed']} opponents out of the game and broke {b['lines']} line{'s' if b['lines'] != 1 else ''}.", "body")]

    # networks
    story += [PageBreak(), P("Passing networks", "h2"), P(C.WHAT["network"], "what")]
    for c in d.clubs:
        net = a["networks"][c]["full"]
        st = net["stats"]
        extra = f" The strongest link is {esc(d.name(st['strongestLink']['a']))} and {esc(d.name(st['strongestLink']['b']))} ({st['strongestLink']['n']} passes)." if st.get("strongestLink") else ""
        story += [KeepTogether([P(f"{esc(d.team[c]['name'])}", "h3"), D.passing_network(CW * 0.78, net, d.team[c]["colors"]["primary"], d.team[c]["colors"]["secondary"]),
                                P(f"{st['completedPasses']} completed passes, average length {f1(st['avgPassLengthM'])} m, average position {f1(st['avgX'], 0)} m from the own goal.{extra}", "small")])]

    # runs
    rn = a["runs"]["teams"]
    story += [P("Off-ball runs", "h2"), P(C.WHAT["runs"], "what")]
    rows = [["Run", h["short"], aw["short"]]]
    for kind, lab in (("in_behind", "In behind"), ("overlap", "Overlap"), ("drop", "Drop into midfield")):
        hv, av = rn.get(hc, {}).get(kind, {"n": 0, "ballPlayed": 0}), rn.get(ac, {}).get(kind, {"n": 0, "ballPlayed": 0})
        rows.append([lab, f"{hv['n']} ({hv['ballPlayed']} found)", f"{av['n']} ({av['ballPlayed']} found)"])
    story += [table(rows, w3)]

    # load
    story += [P("Physical load", "h2"), P(C.WHAT["load"], "what")]
    rows = [["Player", "Team", "Distance km", "High speed m", "Sprint m", "Accelerations"]]
    for r in a["load"]["top"][:8]:
        rows.append([r["name"], d.short(r["team"]), f"{r['km']:.1f}", f"{r['hsrM']:.0f}", f"{r['sprintM']:.0f}", str(r["acc"])])
    story += [table(rows, [CW - 270, 60, 60, 60, 50, 40], align_right_from=2)]

    # transitions + pressing
    tr = a["transitions"]
    story += [PageBreak(), P("Transitions and pressing", "h2"), P(C.WHAT["trans"], "what")]
    rows = [["", h["short"], aw["short"]]]
    for lab, key, fmt in (("Possessions lost", "lost", str), ("Won back within 5 s", "regained5s", str), ("Counter-press success", "counterpressRate", lambda v: pc(v)), ("High turnovers", "highTurnovers", str), ("Shots from high turnovers", "highTurnoverShots", str), ("Fast breaks", "fastBreaks", str), ("Fast-break xG", "fastBreakXg", lambda v: f"{v:.2f}")):
        rows.append(_team_pair(d, lab, [tr[hc][key], tr[ac][key]], lambda v, f=fmt: "n/a" if v is None else f(v)))
    story += [table(rows, w3)]
    pr = a["pressing"]
    story += [P(C.WHAT["press"], "what")]
    rows = [["", h["short"], aw["short"]]]
    rows.append(["Pressures", str(pr[hc]["pressures"]), str(pr[ac]["pressures"])])
    for z, lab in (("high", "PPDA, opponent's third"), ("middle", "PPDA, middle third"), ("low", "PPDA, own third")):
        rows.append([lab, f1(pr[hc]["ppdaByZone"].get(z)), f1(pr[ac]["ppdaByZone"].get(z))])
    for k, lab in (("backPass", "Press set off by a back pass"), ("badPass", "Press set off by a poor pass"), ("other", "Press set off by something else")):
        rows.append([lab, pc(pr[hc]["triggerShare"].get(k)), pc(pr[ac]["triggerShare"].get(k))])
    story += [table(rows, w3)]

    # set pieces
    sps = a["setPieces"]["teams"]
    story += [P("Set pieces", "h2"), P(C.WHAT["set"], "what")]
    rows = [["Team", "Kind", "Routine", "Taken", "Shots", "xG", "Goals"]]
    for c in d.clubs:
        for kind, routines in sps[c]["taken"].items():
            for rt, s in routines.items():
                rows.append([d.short(c), kind.replace("_", " "), rt.replace("_", " "), str(s["n"]), str(s["shots"]), f"{s['xg']:.2f}", str(s["goals"])])
    if len(rows) > 1:
        story += [table(rows[:26], [60, 80, 90, 50, 50, 50, CW - 380], align_right_from=3)]
    story += [P(f"Corner defence: {esc(d.short(hc))} {esc(sps[hc]['defence'])}, {esc(d.short(ac))} {esc(sps[ac]['defence'])}.", "body")]

    # goalkeepers
    gk = a["goalkeepers"]
    story += [P("Goalkeepers", "h2"), P(C.WHAT["gk"], "what")]
    rows = [["Keeper", "Faced", "Saves", "Conceded", "xGOT faced", "Prevented", "Claims", "Pass %"]]
    for c in d.clubs:
        k = gk[c]
        rows.append([f"{k['name']} ({d.short(c)})", str(k["shotsFaced"]), str(k["saves"]), str(k["goalsConceded"]), f"{k['xgotFaced']:.2f}", f"{k['goalsPrevented']:+.2f}", str(k["claims"]), pc(k["passCompletion"])])
    story += [table(rows, [CW - 330, 38, 38, 48, 52, 52, 40, 40], align_right_from=1)]

    # season
    se = a.get("season")
    if se:
        story += [PageBreak(), P("Season context and prediction", "h2"), P(C.WHAT["season"], "what")]
        rows = [["Pos", "Club", "P", "W", "D", "L", "GF", "GA", "GD", "Pts", "Form"]]
        for r in se["standings"]:
            nm = d.team[r["club"]]["name"] if r["club"] in d.team else r["club"]
            rows.append([str(r["pos"]), nm, str(r["played"]), str(r["won"]), str(r["drawn"]), str(r["lost"]), str(r["gf"]), str(r["ga"]), f"{r['gd']:+d}", str(r["pts"]), se["form"].get(r["club"], "")])
        story += [table(rows, [28, CW - 262, 24, 24, 24, 24, 28, 28, 30, 30, 20 + 0], align_right_from=2)]
        pre = se["prediction"]
        story += [P(f"Before the match the model gave {esc(h['short'])} {pc(pre['home'])}, a draw {pc(pre['draw'])} and {esc(aw['short'])} {pc(pre['away'])}, with expected goals {pre['xg'].get(hc, 0):.2f} to {pre['xg'].get(ac, 0):.2f}. The likeliest scores were " + ", ".join(f"{s['score'][0]}-{s['score'][1]} ({pc(s['p'])})" for s in pre["scores"][:3]) + ".", "body")]
        h2h = se["headToHead"]["meetings"]
        if h2h:
            story += [P("Earlier meetings: " + "; ".join(f"{esc(d.short(m['home']))} {m['score'][0]}-{m['score'][1]} {esc(d.short(m['away']))} (round {m['round']})" for m in h2h[:3]) + ".", "body")]
    story += [PageBreak()]


def players_section(d: Data, story: list) -> None:
    story += [P("5. Every player", "h1"), Rule(CW, RULE, 0.6), Spacer(1, 4)]
    story += [P("Impact combines possession value with goals and assists. Packing and line breaks count forward passes that took opponents out of the game; xG and xA are expected goals and expected assists from the player's shots and key passes.", "what")]
    for c in d.clubs:
        t = d.team[c]
        rows = [["Player", "Pos", "Min", "Pass", "G", "A", "xG", "xA", "Tkl", "Int", "Press", "Pack", "Value", "Km"]]
        mine = sorted((r for r in d.a["players"] if r["team"] == c), key=lambda r: -r["impact"])
        for r in mine:
            rows.append([r["name"], r["pos"], f1(r["minutes"], 0), f"{r['passesComplete']}/{r['passes']}", str(r["goals"]), str(r["assists"]), f"{r['xg']:.2f}", f"{r['xa']:.2f}", str(r["tackles"]), str(r["interceptions"]), str(r["pressures"]), str(r["packing"]), "n/a" if r["value"] is None else f"{r['value']:+.2f}", f1(r["km"])])
        story += [P(esc(t["name"]), "h2"), table(rows, [CW - 330, 26, 26, 38, 16, 16, 28, 28, 22, 22, 28, 28, 36, 26], align_right_from=1, font=7.3)]
    story += [PageBreak()]


def formations_section(d: Data, story: list) -> None:
    story += [P("6. All nine formations compared", "h1"), Rule(CW, RULE, 0.6), Spacer(1, 4)]
    story += [P("How the formations the simulator knows differ in each phase. Numbers read from the deepest line to the front; the last column lists who stays back as cover when the team attacks. The two formations played in this match are in bold.", "what")]
    playing = {d.team[c].get("startFormation") or d.team[c]["formation"] for c in d.clubs}
    rows = [["Formation", "Idea", "Build-up", "Attack", "Press", "Block", "Rest defence"]]
    for n in TA.formation_names():
        s = TA.describe_shapes(n, {})
        b = f"<b>{n}</b>" if n in playing else n
        rows.append([P(b, "cell"), P(esc(s["blurb"]), "cell"), s["build"], s["attack"], s["press"], s["block"], s["rest"]])
    story += [table(rows, [48, CW - 296, 46, 40, 40, 40, 82], align_right_from=-1, font=7.8)]
    story += [P("Club tags change these shapes: a lone pivot that drops makes the build-up a back three, inverted fullbacks narrow it, a false nine drops the front line into midfield, and a back-three side presses and defends with its wing-backs dropping in.", "body")]
    story += [P("Press schemes and transitions", "h2")]
    for k in ("press_scheme", "on_loss", "on_win"):
        for v, text in C.TAG_TEXT[k].items():
            story += [Paragraph(f"<b>{esc(k.replace('_', ' ').capitalize())}: {esc(v)}.</b> The team {esc(text)}.", ST["bullet"], bulletText="•")]
    story += [PageBreak()]


def method_section(d: Data, story: list) -> None:
    story += [P("7. What to trust", "h1"), Rule(CW, RULE, 0.6), Spacer(1, 4)]
    for line in C.TRUST:
        story += [Paragraph(esc(line), ST["bullet"], bulletText="•")]
    mod = d.a["winProbability"].get("model")
    if mod:
        story += [P("The win-probability model", "h2"), P(f"Goals follow a Poisson process at a league rate of {mod['goal_rate']:.4f} per team-minute over {mod['match_minutes']:.1f} minutes, blended with the match's own expected goals as if the prior were {mod['prior_minutes']:.0f} minutes of evidence. A red card multiplies the ten-man side's scoring rate by {mod['red_own']} and the other side's by {mod['red_opp']}; those two are priors, not fitted. Penalties count as goals but not as expected-goals evidence.")]
    story += [P("Where the numbers come from", "h2"), P("Events and tracking come from the 5 Hz simulator (or any feed in the same format). Code derives every metric; the report is assembled from the replay package and contains no model-written text. The same package drives the match center, the MCP tools and the on-screen graphics, so a number here matches the number there.")]


def build_report(package: Path, out: Path | None = None) -> Path:
    """Write ``report.pdf`` for the replay package at ``package`` (or to ``out``) and return its path."""
    package = Path(package)
    d = Data(package)
    out = Path(out) if out else package / "report.pdf"
    title = f"{d.home['name']} v {d.away['name']}"
    doc = ReportDoc(str(out), title, f"All data is synthetic. Clubs and players are fictional. Match {d.meta['matchId']}.")
    story: list = []
    cover(d, story)
    story_section(d, story)
    tactics_section(d, story)
    positions_section(d, story)
    analytics_section(d, story)
    players_section(d, story)
    formations_section(d, story)
    method_section(d, story)
    doc.multiBuild(story)
    return out
