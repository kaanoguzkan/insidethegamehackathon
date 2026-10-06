"""Vector drawings for the report: pitches with shapes, shot maps, passing networks and the match-story charts.

Everything is drawn in pitch metres (105 x 68) and scaled to the width asked for, so a diagram looks the same
at any size. The y axis points down the page as it does on screen.
"""

from __future__ import annotations

import math

from reportlab.graphics.shapes import Circle, Drawing, Group, Line, Polygon, PolyLine, Rect, String
from reportlab.lib import colors

L, W, PAD = 105.0, 68.0, 3.0
GRASS = colors.HexColor("#1d6b45")
GRASS_2 = colors.HexColor("#1a6140")
CHALK = colors.Color(1, 1, 1, alpha=0.8)
INK = colors.HexColor("#14201a")
MUTED = colors.HexColor("#5d6b63")
GOLD = colors.HexColor("#f2c14e")


def _hex(c: str) -> colors.Color:
    return colors.HexColor(c)


def lift(c: str, amount: float = 0.0) -> colors.Color:
    """Mix a colour toward white; team colours are often dark and need it on a green pitch."""
    base = _hex(c)
    return colors.Color(base.red + (1 - base.red) * amount, base.green + (1 - base.green) * amount, base.blue + (1 - base.blue) * amount)


class Pitch:
    """A pitch drawing with metre coordinates. ``add`` places shapes in pitch space; ``drawing`` is the result."""

    def __init__(self, width: float, half: bool = False):
        self.half = half
        self.x0 = L / 2 - PAD if half else -PAD
        self.span = (L / 2 + 2 * PAD) if half else (L + 2 * PAD)
        self.s = width / self.span
        self.height = (W + 2 * PAD) * self.s
        self.d = Drawing(width, self.height)
        self.g = self.d
        self._grass()
        self._lines()

    def X(self, x: float) -> float:
        return (x - self.x0) * self.s

    def Y(self, y: float) -> float:
        return self.height - (y + PAD) * self.s

    def _grass(self) -> None:
        self.d.add(Rect(0, 0, self.d.width, self.height, fillColor=GRASS, strokeColor=None))
        n = 7 if self.half else 14
        step = (L / 2 if self.half else L) / n
        start = L / 2 if self.half else 0.0
        for i in range(0, n, 2):
            self.d.add(Rect(self.X(start + i * step), self.Y(W), step * self.s, W * self.s, fillColor=GRASS_2, strokeColor=None))

    def _line(self, x1, y1, x2, y2, w=0.6):
        self.d.add(Line(self.X(x1), self.Y(y1), self.X(x2), self.Y(y2), strokeColor=CHALK, strokeWidth=w))

    def _lines(self) -> None:
        a = 0.0 if not self.half else L / 2
        self.d.add(Rect(self.X(a), self.Y(W), (L - a) * self.s, W * self.s, fillColor=None, strokeColor=CHALK, strokeWidth=0.7))
        if not self.half:
            self._line(L / 2, 0, L / 2, W)
        cx = self.X(L / 2)
        self.d.add(Circle(cx, self.Y(W / 2), 9.15 * self.s, fillColor=None, strokeColor=CHALK, strokeWidth=0.6))
        sides = (1,) if self.half else (0, 1)
        for side in sides:
            x0 = L - 16.5 if side else 0.0
            x6 = L - 5.5 if side else 0.0
            self.d.add(Rect(self.X(x0), self.Y(W / 2 + 20.16), 16.5 * self.s, 40.32 * self.s, fillColor=None, strokeColor=CHALK, strokeWidth=0.6))
            self.d.add(Rect(self.X(x6), self.Y(W / 2 + 9.16), 5.5 * self.s, 18.32 * self.s, fillColor=None, strokeColor=CHALK, strokeWidth=0.6))

    # ----- shapes ------------------------------------------------------------------------------------------

    def dot(self, x, y, r=1.5, fill=colors.white, stroke=None, label: str | None = None, label_color=INK, size: float | None = None):
        self.d.add(Circle(self.X(x), self.Y(y), r * self.s, fillColor=fill, strokeColor=stroke, strokeWidth=0.5))
        if label:
            fs = size or max(4.5, r * self.s * 0.95)
            self.d.add(String(self.X(x), self.Y(y) - fs * 0.34, label, fontName="Helvetica-Bold", fontSize=fs, fillColor=label_color, textAnchor="middle"))

    def line(self, x1, y1, x2, y2, color=colors.white, w=0.8, dash=None):
        ln = Line(self.X(x1), self.Y(y1), self.X(x2), self.Y(y2), strokeColor=color, strokeWidth=w)
        if dash:
            ln.strokeDashArray = dash
        self.d.add(ln)

    def polygon(self, pts, fill=None, stroke=colors.white, w=0.8, dash=None):
        flat = [v for x, y in pts for v in (self.X(x), self.Y(y))]
        p = Polygon(flat, fillColor=fill, strokeColor=stroke, strokeWidth=w)
        if dash:
            p.strokeDashArray = dash
        self.d.add(p)

    def text(self, x, y, s, size=6, color=colors.white, anchor="middle", bold=False):
        self.d.add(String(self.X(x), self.Y(y), s, fontName="Helvetica-Bold" if bold else "Helvetica", fontSize=size, fillColor=color, textAnchor=anchor))


def hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Convex hull (monotone chain)."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lo: list = []
    for p in pts:
        while len(lo) >= 2 and cross(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    up: list = []
    for p in reversed(pts):
        while len(up) >= 2 and cross(up[-2], up[-1], p) <= 0:
            up.pop()
        up.append(p)
    return lo[:-1] + up[:-1]


def shape_diagram(width: float, slots: list[tuple[str, float, float]], color: str, secondary: str, title: str, subtitle: str = "") -> Drawing:
    """One phase of play: the ten outfield slots (role, depth 0..1, width 0..1) and the goalkeeper, attacking left to right.

    Depth is an ordering that is stretched between the team's back and front lines, so the diagram is a schematic
    (who stands level with whom and how wide), not a measurement.
    """
    p = Pitch(width)
    fill = _hex(color)
    pts = []
    for _role, depth, wid in slots:
        x, y = 7 + depth * 80.0, 5 + wid * (W - 10)
        pts.append((x, y))
    h = hull(pts)
    if len(h) >= 3:
        p.polygon(h, fill=colors.Color(1, 1, 1, alpha=0.10), stroke=colors.Color(1, 1, 1, alpha=0.5), w=0.5, dash=[2, 2])
    p.dot(3.5, W / 2, 2.4, fill=lift(secondary, 0.0), stroke=colors.white, label="GK", label_color=fill, size=5)
    for (role, _d, _w), (x, y) in zip(slots, pts, strict=True):
        p.dot(x, y, 2.6, fill=fill, stroke=colors.white, label=role, label_color=colors.white if _lum(color) < 0.6 else INK, size=5.2)
    d = Drawing(width, p.height + 22)
    g = Group(p.d)
    g.translate(0, 0)
    d.add(g)
    d.add(String(0, p.height + 12, title, fontName="Helvetica-Bold", fontSize=8.5, fillColor=INK))
    if subtitle:
        d.add(String(width, p.height + 12, subtitle, fontName="Helvetica", fontSize=7.5, fillColor=MUTED, textAnchor="end"))
    return d


def _lum(hex_color: str) -> float:
    c = _hex(hex_color)
    return 0.2126 * c.red + 0.7152 * c.green + 0.0722 * c.blue


def shot_map(width: float, shots: list[dict], team_colors: dict[str, str], names: dict[str, str]) -> Drawing:
    """Both teams' shots on the attacking half, each attacking the right goal. Size is xG, filled means goal."""
    p = Pitch(width, half=True)
    for s in sorted(shots, key=lambda s: s["xg"]):
        x, y = s["x"], s["y"]
        r = 0.9 + 4.2 * math.sqrt(max(s["xg"], 0.0))
        col = lift(team_colors[s["team"]], 0.25)
        goal = s["outcome"] == "goal"
        p.d.add(Circle(p.X(x), p.Y(y), r * p.s, fillColor=col if goal else colors.Color(col.red, col.green, col.blue, alpha=0.35), strokeColor=colors.white, strokeWidth=0.9 if goal else 0.4))
    return p.d


def passing_network(width: float, net: dict, color: str, secondary: str) -> Drawing:
    """Players at their average pass position, joined by completed passes (thicker means more)."""
    p = Pitch(width)
    nodes = {n["id"]: n for n in net["nodes"]}
    top = max((e["n"] for e in net["edges"]), default=1)
    for e in net["edges"]:
        a, b = nodes.get(e["a"]), nodes.get(e["b"])
        if a and b and e["n"] >= 3:
            p.line(a["x"], a["y"], b["x"], b["y"], color=colors.Color(1, 1, 1, alpha=0.75), w=0.4 + 2.6 * e["n"] / top)
    fill = _hex(color)
    most = max((n["passes"] for n in net["nodes"]), default=1)
    for n in net["nodes"]:
        p.dot(n["x"], n["y"], 1.6 + 1.6 * n["passes"] / most, fill=fill, stroke=colors.white, label=(n["name"] or "").split(" ")[-1][:9], label_color=colors.white if _lum(color) < 0.6 else INK, size=5.2)
    return p.d


def _axis(d: Drawing, x0: float, y0: float, w: float, h: float, total: float, p2_start: float | None) -> None:
    d.add(Rect(x0, y0, w, h, fillColor=colors.HexColor("#f4f6f4"), strokeColor=colors.HexColor("#c9d1cc"), strokeWidth=0.5))
    for m in (15, 30, 45, 60, 75, 90):
        at = m * 60_000 if m <= 45 else (p2_start if p2_start is not None else 45 * 60_000) + (m - 45) * 60_000
        if at >= total:
            continue
        x = x0 + at / total * w
        d.add(Line(x, y0, x, y0 + h, strokeColor=colors.HexColor("#dfe5e1"), strokeWidth=0.4))
        d.add(String(x, y0 - 8, f"{m}'", fontName="Helvetica", fontSize=6.5, fillColor=MUTED, textAnchor="middle"))


def win_probability_chart(width: float, height: float, series: list[dict], swings: list[dict], total: float, p2_start: float | None, home: dict, away: dict) -> Drawing:
    """Home, draw and away probability stacked, with each goal and red card marked by how far it moved the odds."""
    d = Drawing(width, height + 22)
    x0, y0, w, h = 0.0, 14.0, width, height
    _axis(d, x0, y0, w, h, total, p2_start)
    if not series:
        return d

    def X(ms):
        return x0 + ms / total * w

    pts = [(X(s["matchMs"]), s["p"]) for s in series]
    home_top = [(x, y0 + p["home"] * h) for x, p in pts]
    away_bot = [(x, y0 + (1 - p["away"]) * h) for x, p in pts]
    d.add(Rect(x0, y0, w, h, fillColor=colors.HexColor("#b9bfbb"), strokeColor=None))
    d.add(Polygon([v for x, y in [(home_top[0][0], y0), *home_top, (home_top[-1][0], y0)] for v in (x, y)], fillColor=_hex(home["colors"]["primary"]), strokeColor=None))
    d.add(Polygon([v for x, y in [(away_bot[0][0], y0 + h), *away_bot, (away_bot[-1][0], y0 + h)] for v in (x, y)], fillColor=_hex(away["colors"]["primary"]), strokeColor=None))
    d.add(Line(x0, y0 + h / 2, x0 + w, y0 + h / 2, strokeColor=colors.Color(1, 1, 1, alpha=0.6), strokeWidth=0.4, strokeDashArray=[2, 2]))
    for k, sw in enumerate(swings):
        x = X(sw["matchMs"])
        d.add(Line(x, y0, x, y0 + h, strokeColor=colors.white, strokeWidth=0.8, strokeDashArray=[2, 2]))
        label = ("G " if sw["kind"] == "goal" else "R ") + f"{round(sw['swing'] * 100):+d}%"
        d.add(String(min(x + 2, x0 + w - 28), y0 + h - 8 - 8 * (k % 2), label, fontName="Helvetica-Bold", fontSize=6.5, fillColor=colors.white))
    return d


def xg_race_chart(width: float, height: float, race: dict[str, list], total: float, p2_start: float | None, home: dict, away: dict) -> Drawing:
    d = Drawing(width, height + 22)
    x0, y0, w, h = 0.0, 14.0, width, height
    _axis(d, x0, y0, w, h, total, p2_start)
    top = max([pt[1] for v in race.values() for pt in v] + [1.0]) * 1.1
    for club, team in ((home["id"], home), (away["id"], away)):
        pts = race.get(club, [])
        flat: list[float] = []
        prev_y = None
        for ms, xg, _g in pts:
            x, y = x0 + ms / total * w, y0 + xg / top * h
            if prev_y is not None:
                flat += [x, prev_y]
            flat += [x, y]
            prev_y = y
        if len(flat) >= 4:
            d.add(PolyLine(flat, strokeColor=lift(team["colors"]["primary"], 0.0), strokeWidth=1.8))
    for i, (club, team) in enumerate(((home["id"], home), (away["id"], away))):
        d.add(Rect(6 + i * 90, y0 + h - 12, 8, 6, fillColor=_hex(team["colors"]["primary"]), strokeColor=None))
        d.add(String(18 + i * 90, y0 + h - 11, f"{team['short']} {race.get(club, [[0, 0, 0]])[-1][1]:.2f} xG", fontName="Helvetica", fontSize=7, fillColor=INK))
    d.add(String(x0 + 2, y0 + h + 2, f"{top:.1f}", fontName="Helvetica", fontSize=6, fillColor=MUTED))
    return d


def phase_timeline(width: float, segments: list[list], total: float, color: str, palette: dict[str, colors.Color], names: list[str], bucket_ms: int = 90_000) -> Drawing:
    """One team's phases across the match as a coloured bar: each slice shows the phase the team spent most of it in."""
    d = Drawing(width, 14)
    if not segments:
        return d
    n = int(total // bucket_ms) + 1
    spent = [dict.fromkeys(names, 0.0) for _ in range(n)]
    for i, (start, idx) in enumerate(segments):
        stop = segments[i + 1][0] if i + 1 < len(segments) else total
        t = start
        while t < stop:
            b = int(t // bucket_ms)
            nxt = min(stop, (b + 1) * bucket_ms)
            spent[min(b, n - 1)][names[idx]] += nxt - t
            t = nxt
    for b, row in enumerate(spent):
        ph = max(row, key=row.get)
        if row[ph] > 0:
            d.add(Rect(b * bucket_ms / total * width, 0, bucket_ms / total * width + 0.3, 12, fillColor=palette[ph], strokeColor=None))
    return d


def bar(width: float, frac: float, color: colors.Color, h: float = 6.0) -> Drawing:
    d = Drawing(width, h)
    d.add(Rect(0, 0, width, h, fillColor=colors.HexColor("#e6ebe8"), strokeColor=None))
    d.add(Rect(0, 0, width * max(0.0, min(1.0, frac)), h, fillColor=color, strokeColor=None))
    return d


def versus_bar(width: float, a: float, b: float, ca: str, cb: str, h: float = 7.0) -> Drawing:
    d = Drawing(width, h)
    tot = (a + b) or 1.0
    d.add(Rect(0, 0, width * a / tot, h, fillColor=_hex(ca), strokeColor=None))
    d.add(Rect(width * a / tot, 0, width * b / tot, h, fillColor=_hex(cb), strokeColor=None))
    return d
