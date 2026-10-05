"""Tunable thresholds for the interpreter.

Everything that decides *what counts as a story* lives here, with the reasoning next to the
number, so the behaviour is inspectable and documented in ``docs/metrics.md``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SECOND = 1000
MINUTE = 60 * SECOND


@dataclass
class InterpreterConfig:
    # --- windows ---------------------------------------------------------------------------
    window_ms: int = 5 * MINUTE  # the "now" window metrics are computed over
    prev_window_ms: int = 10 * MINUTE  # the comparison window right before it
    eval_every_ms: int = 1 * MINUTE  # how often indices and window detectors run
    eval_lag_ms: int = 12 * SECOND  # wait for late physical events (analyzer lag) before evaluating
    min_play_ms: int = 8 * MINUTE  # no window-based moments before this much play
    cooldown_ms: int = 10 * MINUTE  # same moment type + team at most once per this long

    # --- single-event moments -----------------------------------------------------------------
    big_chance_xg: float = 0.30  # a chance this good is a story even if it misses
    top_speed_kmh: float = 33.0  # sprint peak worth a highlight
    speed_badge_kmh: float = 30.0  # sprint peak worth an on-screen speed badge
    fast_shot_kmh: float = 100.0  # fastest shot of the match must also clear this
    key_pass_difficulty: float = 6.5  # completed pass at least this hard gets a card

    # --- pressing ---------------------------------------------------------------------------------
    # PPDA over a few minutes rests on 0-3 defensive actions, so it is far too noisy to trigger on.
    # The detector keys on the *pressure rate* (many events) over longer windows and reports
    # PPDA, shrunk toward the league mean, as supporting evidence.
    # Pressing is read from tracking: how far the nearest defender is from the ball while the team
    # is out of possession. That is measured every frame (hundreds of samples a window), unlike
    # pressure events (about 2 a minute), so a real change stands out from noise.
    # Operating point measured over 24 seeds (see docs/metrics.md): gap >= 2.0 m, corroborated by the
    # pressure-event rate, held for two evaluations: ~4% false alarms per team-match, ~88% detection.
    press_now_ms: int = 8 * MINUTE
    press_prev_ms: int = 15 * MINUTE
    press_gap_m: float = 2.0  # change in nearest-defender distance, metres
    press_corroboration: float = 0.25  # pressure events per minute must move this fraction the same way
    press_min_frames: int = 100  # opponent-half frames needed in each window
    ppda_prior_actions: float = 2.0  # pseudo-actions that shrink PPDA toward the league mean

    # --- momentum -------------------------------------------------------------------------------
    momentum_swing_gap: float = 0.16  # xT+xG gap per window (more than one decent chance)
    momentum_swing_min_prev_gap: float = 0.06  # the old leader must have actually led

    # --- control vs chaos --------------------------------------------------------------------------
    chaos_flip_level: float = 50.0
    chaos_flip_delta: float = 22.0
    chaos_smooth_now: int = 3  # snapshots (minutes) averaged for the current chaos level
    chaos_smooth_prev: int = 10  # snapshots averaged for the comparison level

    # --- rhythm ------------------------------------------------------------------------------------
    rhythm_change: float = 0.30  # relative tempo change versus the previous window

    # --- tactical shape (from tracking) ------------------------------------------------------------
    # Line height varies a lot on its own (sigma about 6 m between a 3-minute and a 10-minute mean),
    # so a tactical shift must be large and must hold at two consecutive evaluations.
    shift_line_m: float = 7.0  # defensive-line height change (defending, ball in the middle zone)
    shift_width_m: float = 10.0  # team width change
    shift_min_frames: int = 100  # defending tracking frames a window needs (20 s at 5 Hz)
    shift_after_ms: int = 3 * MINUTE
    shift_before_ms: int = 10 * MINUTE

    # --- fatigue ---------------------------------------------------------------------------------------
    # Everyone slows in the second half, so a fatigue story needs a drop well beyond the league norm.
    fatigue_drop: float = 0.60  # sprint rate this fraction below the first-half baseline
    fatigue_window_ms: int = 10 * MINUTE
    fatigue_min_minute: int = 55

    # --- salience and repetition ------------------------------------------------------------------------
    max_story_beats_per_10min: int = 3
    cooldown_by_type: dict[str, int] = field(
        default_factory=lambda: {
            "momentum_swing": 20 * MINUTE,
            "fatigue_drop": 20 * MINUTE,
            "chaos_flip": 15 * MINUTE,
            "tactical_shift": 15 * MINUTE,
            "rhythm_break": 15 * MINUTE,
        }
    )  # moment types that repeat more slowly than the default cooldown

    def cooldown_for(self, moment_type: str) -> int:
        return self.cooldown_by_type.get(moment_type, self.cooldown_ms)

    def to_dict(self) -> dict:
        return asdict(self)
