"""Public data contracts: the shapes other systems (a broadcaster's graphics engine, a fan
app, another team's agents) can rely on.

* ``Overlay``  - one piece of on-screen graphics, timed to the match clock and machine-readable
* ``Profile``  - an anonymous viewer's preferences; viewers with the same settings form a *cohort*
* ``Moment``   - the evidence pack the interpreter produces (loosely typed: it is open-ended)

JSON Schemas are generated from these models into ``schemas/`` (``matchmind export-schemas``)
and a test keeps the committed files in sync.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"

Mode = Literal["analyst", "casual"]
OverlayMode = Literal["analyst", "casual", "any"]  # "any": stat graphics shown to every mode
Language = Literal["en", "es", "tr"]
OverlayKind = Literal[
    "lower_third", "stat_card", "player_tag", "speed_badge", "pass_card", "shot_card",
    "goal_card", "card_badge", "momentum_bar", "control_meter", "recap_card", "ticker", "pitch_graphic",
]  # fmt: skip

SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "es", "tr")
LANGUAGE_NAMES = {"en": "English", "es": "Spanish", "tr": "Turkish"}


class Chip(BaseModel):
    label: str
    value: str


class Cohort(BaseModel):
    """What a group of viewers has in common. Text is generated once per cohort.

    Narrative overlays are written for one cohort. Stat graphics (cards, badges, meters) have no
    narrative, so they are produced once per language with ``mode='any'`` and match every viewer
    who reads that language.
    """

    model_config = ConfigDict(frozen=True)

    mode: OverlayMode = "casual"
    language: Language = "en"
    perspective: str = Field("neutral", description="'neutral' or a club id: tone changes, facts never do")
    focusPlayer: str | None = Field(None, description="player id to follow through the match")

    @property
    def key(self) -> str:
        return f"{self.mode}/{self.language}/{self.perspective}/{self.focusPlayer or '-'}"

    def covers(self, viewer: Cohort) -> bool:
        """Should an overlay written for this cohort be shown to ``viewer``?"""
        return (
            self.language == viewer.language
            and self.mode in ("any", viewer.mode)
            and self.perspective in ("neutral", viewer.perspective)
            and self.focusPlayer in (None, viewer.focusPlayer)
        )


class Accessibility(BaseModel):
    audioDescribed: bool = False
    reducedMotion: bool = False
    highContrast: bool = False


class Profile(BaseModel):
    """An anonymous viewer profile. Contains no personal data."""

    profileId: str
    mode: Mode = "casual"
    language: Language = "en"
    perspective: str = "neutral"
    favoriteClub: str | None = None
    focusPlayer: str | None = None
    metricFocus: list[str] = Field(default_factory=list)
    density: Literal["low", "medium", "high"] = "medium"
    accessibility: Accessibility = Field(default_factory=Accessibility)

    def cohort(self) -> Cohort:
        return Cohort(
            mode=self.mode, language=self.language,
            perspective=self.perspective, focusPlayer=self.focusPlayer,
        )  # fmt: skip


class DisplayAt(BaseModel):
    matchMs: int = Field(description="match clock (ms since kick-off) at which to show the overlay")


class Anchor(BaseModel):
    type: Literal["screen", "player", "pitch"] = "screen"
    region: str | None = Field(None, description="e.g. bottom_left, top_right")
    player: str | None = Field(None, description="player id to follow when type is 'player'")


class Point(BaseModel):
    x: float = Field(description="metres along the pitch, 0 to 105")
    y: float = Field(description="metres across the pitch, 0 to 68")


class Shape(BaseModel):
    """A drawing primitive in pitch metres: a line, an arrow, a polygon, a circle or a text label."""

    shape: Literal["line", "arrow", "polygon", "circle", "text"]
    points: list[Point] = Field(description="line/arrow: from and to (or a polyline); polygon: the ring; circle and text: one point")
    radius: float | None = Field(None, description="circle radius in metres")
    label: str | None = None
    style: Literal["solid", "dashed", "dotted"] = "solid"
    emphasis: Literal["primary", "secondary", "muted"] = "primary"


class Graphic(BaseModel):
    """Geometry for a ``pitch_graphic`` overlay, so any renderer can draw it on its own pitch."""

    type: Literal["offside_line", "run", "line_break", "shot_trace"]
    team: str | None = None
    shapes: list[Shape]


class Provenance(BaseModel):
    agents: list[str] = Field(default_factory=list)
    verified: bool = False
    evidenceRef: str | None = None
    fallbackLevel: int = Field(0, description="0 full narrative, 1 retry, 2 template, 3 stat-only")
    model: str | None = None


class OverlayContent(BaseModel):
    headline: str
    body: str = ""
    chips: list[Chip] = Field(default_factory=list)


class Overlay(BaseModel):
    """One timed, machine-readable graphic. Renderer-agnostic."""

    id: str
    matchId: str
    momentId: str | None = None
    factId: str | None = None
    kind: OverlayKind
    displayAt: DisplayAt
    durationMs: int = 8000
    priority: int = Field(3, ge=1, le=5, description="1 must show ... 5 optional")
    cohort: Cohort
    content: OverlayContent
    anchor: Anchor = Field(default_factory=Anchor)
    graphic: Graphic | None = Field(None, description="pitch geometry, present on pitch_graphic overlays")
    provenance: Provenance = Field(default_factory=Provenance)
    schemaVersion: str = SCHEMA_VERSION


class Claim(BaseModel):
    """One checkable statement an agent makes, with the evidence keys it rests on."""

    text: str
    refs: list[str] = Field(default_factory=list, description="evidence keys, e.g. NOR.pressures_per_min")


class Explanation(BaseModel):
    """The Explainer's output: why a moment matters, grounded in evidence."""

    what: str = Field(description="one sentence: what changed or happened")
    why: str = Field(description="the mechanism: what caused it, citing evidence")
    so_what: str = Field(description="what it means for the match")
    claims: list[Claim]
    tactical_tag: str
    confidence: Literal["low", "medium", "high"] = "medium"
    caveats: list[str] = Field(default_factory=list, description="mixed or contradicting evidence worth admitting")


class StoryVariant(BaseModel):
    cohort: str = Field(description="cohort key this text is for")
    headline: str
    body: str
    chips: list[Chip] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)


class StoryOut(BaseModel):
    variants: list[StoryVariant]


class BeatChoice(BaseModel):
    momentId: str
    keep: bool
    priority: int = Field(3, ge=1, le=5)
    storyline: str | None = None
    mergeWith: list[str] = Field(default_factory=list)
    reason: str = ""


class EditorOut(BaseModel):
    beats: list[BeatChoice]


class ToolCall(BaseModel):
    """One match-data tool the planner wants run. ``args`` is a JSON object as text (a free-form object is not allowed in a strict schema)."""

    name: str
    args: str = "{}"


class Plan(BaseModel):
    """The planner's answer to a viewer's question: which tools to run, or a refusal if it is not about this match."""

    tools: list[ToolCall] = Field(default_factory=list, max_length=3)
    refuse: bool = False
    reason: str = ""


class ChatAnswer(BaseModel):
    """The answerer's reply, written only from tool results."""

    answer: str
    used: list[str] = Field(default_factory=list, description="names of the tools the answer relies on")


class Recap(BaseModel):
    cohort: str
    kind: Literal["preview", "story_so_far", "half_time", "full_time"]
    headline: str
    summary: str
    key_moments: list[dict[str, Any]] = Field(default_factory=list)
    player_of_the_match: dict[str, Any] | None = None
    stats: list[Chip] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)


def schema_models() -> dict[str, type[BaseModel]]:
    """Models exported as JSON Schema files."""
    return {
        "overlay": Overlay,
        "profile": Profile,
        "explanation": Explanation,
        "story": StoryOut,
        "editor": EditorOut,
        "recap": Recap,
    }
