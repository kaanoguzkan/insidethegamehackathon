"""Formations and tactics of modern European football.

A formation is not one shape. Teams change shape with the ball:

* ``base``   the nominal formation (kick-offs, line-ups, the name on the team sheet).
* ``attack`` the shape in possession: fullbacks and wing-backs push on, wide midfielders and
             forwards come inside, so a 4-3-3 builds as a 3-2-5 and a 3-4-3 as a 3-2-5 with
             wing-backs as wingers.
* ``block``  the shape out of possession: a 3-4-3 becomes a 5-4-1 as the wing-backs drop in,
             a 4-3-3 becomes a 4-5-1 as the wingers track back, a 4-2-3-1 a 4-4-1-1.

Each layout lists ``(depth, width)`` for the ten outfield slots in the order of ``base``.
Depth is only an ordering that is stretched between the team's back and front lines each tick
(see ``shape.py``); width is a 0..1 position across the pitch from the team's own left.

On top of the formation, club *tags* choose how the shape is played (fullbacks overlap or
step inside, the pivot drops between the centre-backs, a false nine drops into midfield) and how
set pieces are taken and defended.
"""

from __future__ import annotations

# Tag vocabularies. Every tag is a plain string so league and scenario files stay readable.
FULLBACKS = ("hold", "overlap", "inverted")
PIVOT = ("stay", "drop")
STRIKER = ("target", "false9")
BUILD_UP = ("short", "mixed", "long")
CORNERS = ("mixed", "near", "far", "short", "edge")
CORNER_DEFENCE = ("zonal", "man", "mixed")

TAGS: dict[str, tuple[str, ...]] = {
    "fullbacks": FULLBACKS,
    "pivot": PIVOT,
    "striker": STRIKER,
    "build_up": BUILD_UP,
    "corners": CORNERS,
    "corner_defence": CORNER_DEFENCE,
}

Slot = tuple[str, float, float]
Layout = list[tuple[float, float]]

_GK: Slot = ("GK", 0.03, 0.50)


def _f(base: list[Slot], attack: Layout, block: Layout, *, back: int, blurb: str) -> dict:
    assert len(base) == 10 and len(attack) == 10 and len(block) == 10
    return {
        "base": [_GK, *base],
        "attack": attack,
        "block": block,
        "back": back,  # defenders in the nominal back line (for line labels)
        "blurb": blurb,
    }


FORMATIONS_FULL: dict[str, dict] = {
    "4-3-3": _f(
        [("LB", .25, .10), ("CB", .22, .36), ("CB", .22, .64), ("RB", .25, .90),
         ("DM", .42, .50), ("CM", .54, .30), ("CM", .54, .70),
         ("LW", .80, .12), ("ST", .88, .50), ("RW", .80, .88)],
        # builds as a 3-2-5: fullbacks step up, the pivot sits between the lines
        [(.40, .08), (.20, .34), (.20, .66), (.40, .92),
         (.46, .50), (.60, .30), (.60, .70),
         (.84, .10), (.92, .50), (.84, .90)],
        # drops into a 4-5-1 / 4-1-4-1: the wingers track back to the midfield line
        [(.25, .14), (.22, .38), (.22, .62), (.25, .86),
         (.38, .50), (.44, .30), (.44, .70),
         (.52, .14), (.74, .50), (.52, .86)],
        back=4, blurb="front three, one pivot, two eights",
    ),
    "4-2-3-1": _f(
        [("LB", .25, .10), ("CB", .22, .36), ("CB", .22, .64), ("RB", .25, .90),
         ("DM", .42, .38), ("DM", .42, .62),
         ("LM", .66, .15), ("AM", .70, .50), ("RM", .66, .85), ("ST", .88, .50)],
        # builds as a 2-4-4 / 3-2-4-1 with the ten between the lines
        [(.42, .08), (.20, .36), (.20, .64), (.42, .92),
         (.46, .40), (.46, .60),
         (.76, .14), (.70, .50), (.76, .86), (.92, .50)],
        # defends as a 4-4-1-1: the ten steps up beside the striker
        [(.25, .14), (.22, .38), (.22, .62), (.25, .86),
         (.40, .38), (.40, .62),
         (.44, .12), (.64, .50), (.44, .88), (.84, .50)],
        back=4, blurb="double pivot, a ten behind one striker",
    ),
    "4-4-2": _f(
        [("LB", .25, .10), ("CB", .22, .36), ("CB", .22, .64), ("RB", .25, .90),
         ("LM", .54, .10), ("CM", .50, .38), ("CM", .50, .62), ("RM", .54, .90),
         ("ST", .84, .40), ("ST", .84, .60)],
        # two banks of four stretch into a 2-4-4 with high fullbacks
        [(.42, .08), (.20, .36), (.20, .64), (.42, .92),
         (.66, .10), (.54, .36), (.54, .64), (.66, .90),
         (.90, .38), (.90, .62)],
        # two flat, narrow, compact banks of four
        [(.25, .18), (.22, .40), (.22, .60), (.25, .82),
         (.44, .16), (.42, .40), (.42, .60), (.44, .84),
         (.70, .42), (.70, .58)],
        back=4, blurb="two banks of four, a strike pair",
    ),
    "4-1-4-1": _f(
        [("LB", .25, .10), ("CB", .22, .36), ("CB", .22, .64), ("RB", .25, .90),
         ("DM", .40, .50),
         ("LM", .60, .12), ("CM", .58, .38), ("CM", .58, .62), ("RM", .60, .88),
         ("ST", .88, .50)],
        [(.42, .08), (.20, .36), (.20, .64), (.42, .92),
         (.44, .50),
         (.72, .12), (.62, .36), (.62, .64), (.72, .88),
         (.92, .50)],
        # a deep 4-5-1 with the screen in front of the back four
        [(.25, .16), (.22, .40), (.22, .60), (.25, .84),
         (.36, .50),
         (.46, .12), (.44, .38), (.44, .62), (.46, .88),
         (.72, .50)],
        back=4, blurb="a lone holding midfielder screening the back four",
    ),
    "3-5-2": _f(
        [("CB", .22, .26), ("CB", .20, .50), ("CB", .22, .74),
         ("LWB", .52, .05), ("CM", .52, .34), ("DM", .42, .50), ("CM", .52, .66), ("RWB", .52, .95),
         ("ST", .84, .40), ("ST", .84, .60)],
        # a 3-3-4 with the wing-backs as wingers
        [(.22, .26), (.20, .50), (.22, .74),
         (.76, .05), (.56, .34), (.46, .50), (.56, .66), (.76, .95),
         (.90, .38), (.90, .62)],
        # the wing-backs drop into a back five: 5-3-2
        [(.22, .30), (.20, .50), (.22, .70),
         (.24, .08), (.42, .34), (.40, .50), (.42, .66), (.24, .92),
         (.70, .42), (.70, .58)],
        back=3, blurb="three centre-backs, wing-backs, two strikers",
    ),
    "3-4-3": _f(
        [("CB", .22, .26), ("CB", .20, .50), ("CB", .22, .74),
         ("LWB", .52, .05), ("CM", .50, .38), ("CM", .50, .62), ("RWB", .52, .95),
         ("LW", .80, .16), ("ST", .88, .50), ("RW", .80, .84)],
        # a 3-2-5: wing-backs high and wide, the wide forwards come inside
        [(.22, .26), (.20, .50), (.22, .74),
         (.74, .05), (.52, .38), (.52, .62), (.74, .95),
         (.86, .24), (.92, .50), (.86, .76)],
        # a 5-4-1: wing-backs into the back line, wide forwards into midfield
        [(.22, .30), (.20, .50), (.22, .70),
         (.24, .08), (.42, .38), (.42, .62), (.24, .92),
         (.46, .18), (.74, .50), (.46, .82)],
        back=3, blurb="back three, wing-backs, a front three",
    ),
    "3-4-2-1": _f(
        [("CB", .22, .26), ("CB", .20, .50), ("CB", .22, .74),
         ("LWB", .52, .05), ("CM", .48, .38), ("CM", .48, .62), ("RWB", .52, .95),
         ("AM", .72, .30), ("AM", .72, .70), ("ST", .88, .50)],
        # two tens in the half-spaces behind a lone striker
        [(.22, .26), (.20, .50), (.22, .74),
         (.74, .05), (.52, .38), (.52, .62), (.74, .95),
         (.78, .28), (.78, .72), (.92, .50)],
        # a 5-4-1 with the tens wide in the midfield line
        [(.22, .30), (.20, .50), (.22, .70),
         (.24, .08), (.42, .38), (.42, .62), (.24, .92),
         (.50, .20), (.50, .80), (.76, .50)],
        back=3, blurb="back three, two tens in the half-spaces",
    ),
    "5-3-2": _f(
        [("CB", .22, .30), ("CB", .20, .50), ("CB", .22, .70),
         ("LWB", .34, .05), ("RWB", .34, .95),
         ("DM", .42, .50), ("CM", .52, .32), ("CM", .52, .68),
         ("ST", .84, .40), ("ST", .84, .60)],
        # a 3-3-4 when the wing-backs get forward
        [(.22, .30), (.20, .50), (.22, .70),
         (.62, .05), (.62, .95),
         (.44, .50), (.56, .30), (.56, .70),
         (.90, .38), (.90, .62)],
        # a compact low block: five at the back, three screening, two to break
        [(.22, .32), (.20, .50), (.22, .68),
         (.24, .10), (.24, .90),
         (.38, .50), (.40, .34), (.40, .66),
         (.68, .42), (.68, .58)],
        back=5, blurb="a back five and a counter-attacking pair",
    ),
    "4-3-1-2": _f(
        [("LB", .25, .10), ("CB", .22, .36), ("CB", .22, .64), ("RB", .25, .90),
         ("DM", .40, .50), ("CM", .52, .28), ("CM", .52, .72),
         ("AM", .70, .50), ("ST", .88, .40), ("ST", .88, .60)],
        # the fullbacks supply the width the diamond lacks
        [(.46, .06), (.20, .36), (.20, .64), (.46, .94),
         (.44, .50), (.56, .30), (.56, .70),
         (.74, .50), (.92, .40), (.92, .60)],
        # narrow and compact: a 4-4-2 in a tight shape
        [(.25, .16), (.22, .40), (.22, .60), (.25, .84),
         (.38, .50), (.44, .30), (.44, .70),
         (.60, .50), (.76, .42), (.76, .58)],
        back=4, blurb="a midfield diamond and two strikers",
    ),
}


def formation_names() -> list[str]:
    return sorted(FORMATIONS_FULL)


def layout(name: str, phase: str) -> Layout:
    """The ``(depth, width)`` of the ten outfield slots for ``base``, ``attack`` or ``block``."""
    f = FORMATIONS_FULL[name]
    if phase == "base":
        return [(d, w) for _, d, w in f["base"][1:]]
    return list(f[phase])


def roles(name: str) -> list[str]:
    return [r for r, _, _ in FORMATIONS_FULL[name]["base"][1:]]


def apply_attack_tags(name: str, attack: Layout, tags: dict[str, str]) -> Layout:
    """Adjust the in-possession layout for how a club plays it (tags are club dials)."""
    out = [list(p) for p in attack]
    rs = roles(name)
    fb = tags.get("fullbacks", "hold")
    for i, r in enumerate(rs):
        left = out[i][1] < 0.5
        if r in ("LB", "RB"):
            if fb == "overlap":
                out[i] = [max(out[i][0], 0.62), 0.04 if left else 0.96]
            elif fb == "inverted":
                out[i] = [0.48, 0.30 if left else 0.70]
    if fb in ("overlap", "inverted"):
        for i, r in enumerate(rs):
            if r in ("LW", "LM") or r in ("RW", "RM"):
                left = out[i][1] < 0.5
                if fb == "overlap":  # the winger tucks inside to leave the touchline to the fullback
                    out[i][1] = 0.24 if left else 0.76
                else:  # the winger holds the touchline now that the fullback is inside
                    out[i][1] = 0.06 if left else 0.94
                    out[i][0] = min(0.95, out[i][0] + 0.02)
    if tags.get("pivot") == "drop":
        dms = [i for i, r in enumerate(rs) if r == "DM"]
        if len(dms) == 1:  # the lone pivot drops between the centre-backs: a back three in build-up
            out[dms[0]] = [0.22, 0.50]
            for i, r in enumerate(rs):
                if r in ("LB", "RB"):
                    out[i][0] = min(0.80, out[i][0] + 0.10)
        elif len(dms) == 2:  # one of a double pivot drops
            i = min(dms, key=lambda k: out[k][1])
            out[i] = [0.22, 0.50]
            for k, r in enumerate(rs):
                if r in ("LB", "RB"):
                    out[k][0] = min(0.80, out[k][0] + 0.10)
    if tags.get("striker") == "false9":
        sts = [i for i, r in enumerate(rs) if r == "ST"]
        if len(sts) == 1:  # the nine drops into midfield, the wingers attack the space behind
            out[sts[0]][0] = 0.68
            for i, r in enumerate(rs):
                if r in ("LW", "RW", "LM", "RM"):
                    left = out[i][1] < 0.5
                    out[i] = [min(0.96, out[i][0] + 0.06), 0.26 if left else 0.74]
    return [(d, w) for d, w in out]


# How analysts name the in-possession shape (fullbacks and wing-backs high), and the variant when the
# lone pivot drops between the centre-backs to make a back three in build-up.
ATTACK_LABEL = {
    "4-3-3": "2-3-5", "4-2-3-1": "2-4-4", "4-4-2": "2-4-4", "4-1-4-1": "2-3-5", "4-3-1-2": "2-3-3-2",
    "3-5-2": "3-3-4", "3-4-3": "3-2-5", "3-4-2-1": "3-2-4-1", "5-3-2": "3-3-4",
}  # fmt: skip
ATTACK_LABEL_PIVOT_DROP = {"4-3-3": "3-2-5", "4-2-3-1": "3-3-4", "4-1-4-1": "3-2-5", "4-3-1-2": "3-2-3-2"}


def describe_shapes(name: str, tags: dict[str, str]) -> dict[str, str]:
    """Human-readable names for the in- and out-of-possession shapes (for the UI and the docs)."""
    f = FORMATIONS_FULL[name]
    attack = ATTACK_LABEL[name]
    if tags.get("pivot") == "drop":
        attack = ATTACK_LABEL_PIVOT_DROP.get(name, attack)
    return {
        "base": name,
        "attack": attack,
        "block": _line_label(roles(name), layout(name, "block")),
        "blurb": f["blurb"],
    }


def _line_label(rs: list[str], lay: Layout) -> str:
    """Cluster outfield players into lines by depth gaps and write them like '3-2-5'."""
    order = sorted(range(len(lay)), key=lambda i: lay[i][0])
    lines: list[int] = []
    prev = None
    for i in order:
        d = lay[i][0]
        if prev is None or d - prev > 0.10:
            lines.append(0)
        lines[-1] += 1
        prev = d
    return "-".join(str(n) for n in lines)


def assign(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment of rows to columns (Hungarian algorithm); returns the column per row."""
    n = len(cost)
    inf = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (n + 1)
    p, way = [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [inf] * (n + 1)
        used = [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], inf, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    out = [0] * n
    for j in range(1, n + 1):
        out[p[j] - 1] = j - 1
    return out
