"""Formations and tactics of modern European football.

A formation is not one shape. Teams change shape with the ball:

* ``base``   the nominal formation (kick-offs, line-ups, the name on the team sheet).
* ``attack`` the shape in possession: fullbacks and wing-backs push on, wide midfielders and
             forwards come inside, so a 4-3-3 builds as a 3-2-5 and a 3-4-3 as a 3-2-5 with
             wing-backs as wingers.
* ``block``  the shape out of possession: a 3-4-3 becomes a 5-4-1 as the wing-backs drop in,
             a 4-3-3 becomes a 4-5-1 as the wingers track back, a 4-2-3-1 a 4-4-1-1.
* ``build``  the shape of the first phase of build-up, with the ball in the own third: the centre-backs
             split, the pivot drops, the fullbacks and forwards hold their width (a 4-3-3 starts as a 4-1-2-3).
* ``press``  the shape when the team presses high: the front line is pushed up and angled to cut passing
             lanes (a 4-2-3-1 presses as a 4-4-2, the wing-backs of a 3-4-3 jump onto the fullbacks).
* ``low``    a compact low block, derived from ``block`` (used when protecting a lead or by cautious clubs).

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
# How the team presses: by zone, funnelling play to the touchline and jumping on the ball there, or man for man.
PRESS_SCHEME = ("zonal", "wide_trap", "man")
# The first five seconds after losing the ball: swarm it, or drop straight back into shape.
ON_LOSS = ("counterpress", "regroup")
# The first seven seconds after winning it: break at once, or keep the shape and build.
ON_WIN = ("counter", "keep")

TAGS: dict[str, tuple[str, ...]] = {
    "fullbacks": FULLBACKS,
    "pivot": PIVOT,
    "striker": STRIKER,
    "build_up": BUILD_UP,
    "corners": CORNERS,
    "corner_defence": CORNER_DEFENCE,
    "press_scheme": PRESS_SCHEME,
    "on_loss": ON_LOSS,
    "on_win": ON_WIN,
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


# Build-up and pressing shapes for every formation, in the slot order of ``base``. The depths are only an
# ordering (see shape.py); what matters is who is level with whom and how wide each line stands.
PHASE_LAYOUTS: dict[str, dict[str, Layout]] = {
    "4-3-3": {
        # 4-1-2-3: split centre-backs, a single pivot, two eights in the half-spaces, the front three pinning
        "build": [(.28, .08), (.18, .30), (.18, .70), (.28, .92), (.34, .50), (.46, .26), (.46, .74), (.74, .10), (.86, .50), (.74, .90)],
        # front-three press: the wingers curve in to shadow the fullbacks, the nine screens the pivot
        "press": [(.30, .12), (.24, .38), (.24, .62), (.30, .88), (.46, .50), (.58, .32), (.58, .68), (.84, .22), (.92, .50), (.84, .78)],
    },
    "4-2-3-1": {
        "build": [(.30, .08), (.18, .32), (.18, .68), (.30, .92), (.36, .38), (.36, .62), (.60, .12), (.58, .50), (.60, .88), (.84, .50)],
        # the ten steps up beside the striker: a 4-4-2 press
        "press": [(.28, .12), (.24, .38), (.24, .62), (.28, .88), (.44, .38), (.44, .62), (.62, .16), (.86, .40), (.62, .84), (.88, .60)],
    },
    "4-4-2": {
        "build": [(.30, .06), (.18, .34), (.18, .66), (.30, .94), (.50, .10), (.40, .40), (.40, .60), (.50, .90), (.78, .40), (.78, .60)],
        # the pair split the centre-backs, the banks step up together
        "press": [(.28, .18), (.24, .40), (.24, .60), (.28, .82), (.50, .18), (.48, .40), (.48, .60), (.50, .82), (.88, .36), (.88, .64)],
    },
    "4-1-4-1": {
        "build": [(.30, .08), (.18, .34), (.18, .66), (.30, .92), (.34, .50), (.54, .12), (.46, .34), (.46, .66), (.54, .88), (.82, .50)],
        "press": [(.28, .14), (.24, .38), (.24, .62), (.28, .86), (.44, .50), (.64, .14), (.58, .36), (.58, .64), (.64, .86), (.90, .50)],
    },
    "3-5-2": {
        # a wide back three with the pivot between, the wing-backs level with the eights
        "build": [(.22, .20), (.18, .50), (.22, .80), (.46, .05), (.50, .30), (.34, .50), (.50, .70), (.46, .95), (.80, .40), (.80, .60)],
        # the wing-backs jump onto the fullbacks and the back three stays tight behind them
        "press": [(.24, .28), (.22, .50), (.24, .72), (.58, .06), (.56, .34), (.46, .50), (.56, .66), (.58, .94), (.90, .38), (.90, .62)],
    },
    "3-4-3": {
        "build": [(.22, .22), (.18, .50), (.22, .78), (.40, .05), (.40, .38), (.40, .62), (.40, .95), (.72, .14), (.84, .50), (.72, .86)],
        # a mirror press: every opposing line is matched by one of ours
        "press": [(.26, .28), (.22, .50), (.26, .72), (.62, .06), (.54, .36), (.54, .64), (.62, .94), (.86, .18), (.94, .50), (.86, .82)],
    },
    "3-4-2-1": {
        "build": [(.22, .22), (.18, .50), (.22, .78), (.42, .05), (.40, .38), (.40, .62), (.42, .95), (.62, .30), (.62, .70), (.82, .50)],
        "press": [(.26, .28), (.22, .50), (.26, .72), (.58, .06), (.52, .38), (.52, .62), (.58, .94), (.78, .34), (.78, .66), (.92, .50)],
    },
    "5-3-2": {
        "build": [(.22, .24), (.18, .50), (.22, .76), (.40, .05), (.40, .95), (.34, .50), (.46, .32), (.46, .68), (.78, .40), (.78, .60)],
        # a trigger press from a back five: the wing-backs hold until the cue
        "press": [(.24, .32), (.22, .50), (.24, .68), (.40, .08), (.40, .92), (.42, .50), (.52, .34), (.52, .66), (.84, .40), (.84, .60)],
    },
    "4-3-1-2": {
        "build": [(.30, .06), (.18, .34), (.18, .66), (.30, .94), (.34, .50), (.46, .28), (.46, .72), (.64, .50), (.80, .40), (.80, .60)],
        # a narrow diamond press: it shuts the middle and invites play wide, where the fullbacks jump
        "press": [(.28, .16), (.24, .40), (.24, .60), (.28, .84), (.44, .50), (.56, .30), (.56, .70), (.76, .50), (.90, .42), (.90, .58)],
    },
}
assert set(PHASE_LAYOUTS) == set(FORMATIONS_FULL)

LAYOUT_PHASES = ("base", "attack", "block", "build", "press", "low")
# The five phases a team works in: two with the ball (build-up in the own third, then the settled attack)
# and three without it (press, mid block, low block). Order matters: it indexes the blend weights.
PHASES = ("build", "attack", "press", "block", "low")
BUILD_ZONE = 36.0  # metres from the own goal: the ball is still in the first phase of build-up


def formation_names() -> list[str]:
    return sorted(FORMATIONS_FULL)


def layout(name: str, phase: str) -> Layout:
    """The ``(depth, width)`` of the ten outfield slots for ``base``, ``attack`` or ``block``."""
    f = FORMATIONS_FULL[name]
    if phase == "base":
        return [(d, w) for _, d, w in f["base"][1:]]
    if phase in ("build", "press"):
        return list(PHASE_LAYOUTS[name][phase])
    if phase == "low":  # the block, squeezed: shorter and narrower, everyone within reach of the box
        return [(d * 0.82, 0.5 + (w - 0.5) * 0.86) for d, w in f["block"]]
    return list(f[phase])


def roles(name: str) -> list[str]:
    return [r for r, _, _ in FORMATIONS_FULL[name]["base"][1:]]


def apply_attack_tags(name: str, attack: Layout, tags: dict[str, str], build: bool = False) -> Layout:
    """Adjust an in-possession layout for how a club plays it (tags are club dials).

    ``build`` is the first phase of build-up, where the same tags read differently: the fullbacks stay deeper
    (inverted ones tuck in beside the pivot rather than level with the eights) and the false nine has already
    dropped to link play.
    """
    out = [list(p) for p in attack]
    rs = roles(name)
    fb = tags.get("fullbacks", "hold")
    for i, r in enumerate(rs):
        left = out[i][1] < 0.5
        if r in ("LB", "RB"):
            if fb == "overlap":
                out[i] = [max(out[i][0], 0.44 if build else 0.62), 0.04 if left else 0.96]
            elif fb == "inverted":
                out[i] = [0.36 if build else 0.48, 0.30 if left else 0.70]
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
            out[sts[0]][0] = 0.60 if build else 0.68
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
    build = BUILD_LABEL[name]
    if tags.get("pivot") == "drop":
        build = BUILD_LABEL_PIVOT_DROP.get(name, build)
    return {
        "base": name,
        "attack": attack,
        "block": _line_label(roles(name), layout(name, "block")),
        "build": build,
        "press": PRESS_LABEL[name],
        "rest": rest_defence(name),
        "blurb": f["blurb"],
    }


# How analysts name the first phase of build-up, and the shape the team presses in. Pressing mostly keeps the
# nominal shape (what changes is how high it stands and who jumps), except where a player changes line.
BUILD_LABEL = {
    "4-3-3": "4-1-2-3", "4-2-3-1": "4-2-3-1", "4-4-2": "4-4-2", "4-1-4-1": "4-1-4-1", "4-3-1-2": "4-1-2-1-2",
    "3-5-2": "3-1-4-2", "3-4-3": "3-4-3", "3-4-2-1": "3-4-2-1", "5-3-2": "3-1-4-2",
}  # fmt: skip
PRESS_LABEL = {
    "4-3-3": "4-3-3", "4-2-3-1": "4-4-2", "4-4-2": "4-4-2", "4-1-4-1": "4-1-4-1", "4-3-1-2": "4-3-1-2",
    "3-5-2": "3-5-2", "3-4-3": "3-4-3", "3-4-2-1": "3-4-2-1", "5-3-2": "5-3-2",
}  # fmt: skip
# With the lone pivot dropping between the centre-backs the first phase of build-up is a back three.
BUILD_LABEL_PIVOT_DROP = {"4-3-3": "3-2-2-3", "4-2-3-1": "3-2-1-3-1", "4-1-4-1": "3-2-4-1", "4-3-1-2": "3-2-2-1-2"}


def rest_defence(name: str) -> str:
    """Who stays behind the ball when the team attacks, as role codes (``CB CB DM``): the cover against the counter."""
    lay = layout(name, "attack")
    rs = roles(name)
    deep = sorted(range(10), key=lambda i: lay[i][0])
    keep = [i for i in deep if lay[i][0] <= 0.30 or (rs[i] == "DM" and lay[i][0] <= 0.47)]
    return " ".join(rs[i] for i in keep)


def _line_label(rs: list[str], lay: Layout, gap: float = 0.10) -> str:
    """Cluster outfield players into lines by depth gaps and write them like '3-2-5'."""
    order = sorted(range(len(lay)), key=lambda i: lay[i][0])
    lines: list[int] = []
    prev = None
    for i in order:
        d = lay[i][0]
        if prev is None or d - prev > gap:
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
