"""Overlay Producer: verified text in, timed machine-readable overlays out.

Pure code, no model. It decides *when* things appear (offsets from the match clock), *how long*,
*where*, and resolves collisions so the screen never gets crowded: one lower-third at a time,
cards queued by priority, anything more than 15 seconds late dropped (must-show items are kept
as tickers instead of vanishing).
"""

from __future__ import annotations

from collections import defaultdict

from ..core.contracts import (
    Anchor,
    Chip,
    Cohort,
    DisplayAt,
    Overlay,
    OverlayContent,
    Provenance,
    StoryVariant,
)
from . import templates as T
from .prompts import PROMPT_VERSION

LEAD_MS = {"goal": 1500, "red_card": 1500, "penalty": 1500}
DEFAULT_LEAD_MS = 2500
DURATION_MS = {"lower_third": 9000, "goal": 12000, "card": 6000, "badge": 4500, "ticker": 7000}
LANE = {
    "lower_third": "lower_third", "goal_card": "lower_third", "recap_card": "lower_third",
    "stat_card": "card", "shot_card": "card", "pass_card": "card", "card_badge": "card",
    "speed_badge": "badge", "player_tag": "badge",
}  # fmt: skip
MAX_DELAY_MS = 15_000


def slug(cohort: Cohort) -> str:
    """Cohort key made safe for document ids (Cosmos DB ids may not contain '/')."""
    return cohort.key.replace("/", ".")


def lower_third(
    pack: dict,
    variant: StoryVariant,
    cohort: Cohort,
    *,
    priority: int,
    level: int,
    agents: list[str],
    verified: bool,
    model: str = "offline-template",
) -> Overlay:
    t = pack["type"]
    lead = LEAD_MS.get(t, DEFAULT_LEAD_MS)
    duration = DURATION_MS["goal"] if t in ("goal", "red_card") else DURATION_MS["lower_third"]
    return Overlay(
        id=f"{pack['id']}.ov.{slug(cohort)}",
        matchId=pack["matchId"],
        momentId=pack["id"],
        kind="lower_third",
        displayAt=DisplayAt(matchMs=pack["detectedAt"]["matchMs"] + lead),
        durationMs=duration,
        priority=priority,
        cohort=cohort,
        content=_content(variant),
        anchor=Anchor(type="screen", region="bottom_left"),
        provenance=Provenance(
            agents=agents, verified=verified, evidenceRef=pack["id"], fallbackLevel=level,
            model=f"{model}@{PROMPT_VERSION}",
        ),
    )


def ticker(pack: dict, variant: StoryVariant, cohort: Cohort, *, priority: int = 5) -> Overlay:
    """A low-key one-liner for moments the Editor did not make a story beat."""
    return Overlay(
        id=f"{pack['id']}.tk.{slug(cohort)}",
        matchId=pack["matchId"],
        momentId=pack["id"],
        kind="ticker",
        displayAt=DisplayAt(matchMs=pack["detectedAt"]["matchMs"] + DEFAULT_LEAD_MS),
        durationMs=DURATION_MS["ticker"],
        priority=priority,
        cohort=cohort,
        content=OverlayContent(headline=variant.headline, body=""),
        anchor=Anchor(type="screen", region="top_right"),
        provenance=Provenance(agents=["template"], verified=True, evidenceRef=pack["id"], fallbackLevel=2),
    )


def _content(v: StoryVariant) -> OverlayContent:
    return OverlayContent(headline=v.headline, body=v.body, chips=list(v.chips))


def fact_overlay(fact: dict, cohort: Cohort, names: dict[str, str]) -> Overlay | None:
    """A template overlay (stat card, speed badge ...) from an interpreter fact: no model call."""
    card = T.fact_card(fact, cohort.language, names)
    if card is None:
        return None
    headline, body, chips, kind = card
    t = fact["type"]
    lane = LANE.get(kind, "card")
    dur = DURATION_MS["badge"] if lane == "badge" else DURATION_MS["card"]
    on_player = kind in ("speed_badge", "player_tag")
    return Overlay(
        id=f"{fact['id']}.{slug(cohort)}",
        matchId=fact["matchId"],
        factId=fact["id"],
        kind=kind,
        displayAt=DisplayAt(matchMs=fact["matchMs"] + (800 if t in ("shot_card", "pass_card") else 0)),
        durationMs=dur,
        priority=fact["priority"],
        cohort=cohort,
        content=OverlayContent(headline=headline, body=body, chips=chips),
        anchor=Anchor(type="player", player=fact.get("player")) if on_player and fact.get("player")
        else Anchor(type="screen", region="bottom_right"),
        provenance=Provenance(agents=["template"], verified=True, evidenceRef=fact["id"], fallbackLevel=3),
    )


def momentum_overlays(snapshot: dict, short: dict[str, str], cohort: Cohort) -> list[Overlay]:
    """The always-on momentum bar and control meter, from a per-minute snapshot."""
    ms = snapshot["matchMs"]
    mo = snapshot["momentum"]
    clubs = list(mo)
    lang = cohort.language
    lab = {"en": ("Momentum", "Control"), "es": ("Impulso", "Control"), "tr": ("Momentum", "Kontrol")}[lang]
    bar = Overlay(
        id=f"{snapshot['id']}.mo.{slug(cohort)}", matchId=snapshot["matchId"], kind="momentum_bar",
        displayAt=DisplayAt(matchMs=ms), durationMs=60_000, priority=4, cohort=cohort,
        content=OverlayContent(
            headline=lab[0],
            chips=[Chip(label=short.get(c, c), value=f"{round(mo[c] * 100)}%") for c in clubs],
        ),
        anchor=Anchor(type="screen", region="top_left"),
        provenance=Provenance(agents=["interpreter"], verified=True, evidenceRef=snapshot["id"], fallbackLevel=3),
    )
    ctl = snapshot["control"]
    meter = Overlay(
        id=f"{snapshot['id']}.ct.{slug(cohort)}", matchId=snapshot["matchId"], kind="control_meter",
        displayAt=DisplayAt(matchMs=ms), durationMs=60_000, priority=5, cohort=cohort,
        content=OverlayContent(
            headline=lab[1],
            chips=[Chip(label=short.get(ctl["controller"], ctl["controller"]), value=f"{round(snapshot['chaos'])}/100")],
        ),
        anchor=Anchor(type="screen", region="top_left"),
        provenance=Provenance(agents=["interpreter"], verified=True, evidenceRef=snapshot["id"], fallbackLevel=3),
    )
    return [bar, meter]


def resolve_collisions(overlays: list[Overlay], max_delay_ms: int = MAX_DELAY_MS) -> list[Overlay]:
    """One lower-third at a time per cohort; cards and badges queue in their own lanes.

    A late overlay slides back (at most ``max_delay_ms``). If it cannot, must-show items
    (priority 1-2) become tickers and the rest are dropped.
    """
    by_lane: dict[tuple[str, str], list[Overlay]] = defaultdict(list)
    passthrough: list[Overlay] = []
    for o in overlays:
        lane = LANE.get(o.kind)
        if lane is None:
            passthrough.append(o)
        else:
            by_lane[(o.cohort.key, lane)].append(o)
    out = list(passthrough)
    for items in by_lane.values():
        free_at = -1
        for o in sorted(items, key=lambda o: (o.displayAt.matchMs, o.priority)):
            start = o.displayAt.matchMs
            if start < free_at:
                if free_at - start > max_delay_ms:
                    if o.priority <= 2:
                        out.append(o.model_copy(update={"kind": "ticker", "anchor": Anchor(type="screen", region="top_right")}))
                    continue
                o = o.model_copy(update={"displayAt": DisplayAt(matchMs=free_at)})
                start = free_at
            free_at = start + o.durationMs
            out.append(o)
    return sorted(out, key=lambda o: (o.displayAt.matchMs, o.priority, o.id))
