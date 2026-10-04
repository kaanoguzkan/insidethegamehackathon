"""Match clock helpers.

``matchMs`` is monotonic feed time since kick-off (the half-time break is not simulated).
The *display* clock is what viewers see: the second half restarts at 45:00 whatever stoppage
time the first half had.
"""

from __future__ import annotations


def clock_from_ms(ms: int, p2_start_ms: int | None) -> dict:
    if p2_start_ms is None or ms < p2_start_ms:
        period, sec = 1, ms / 1000.0
    else:
        period, sec = 2, 45 * 60 + (ms - p2_start_ms) / 1000.0
    return {"period": period, "minute": int(sec // 60), "second": int(sec % 60), "matchMs": int(ms)}


def display_minute(clock: dict) -> int:
    return int(clock["minute"])


def label(clock: dict) -> str:
    """Short viewer-facing label such as ``63'`` or ``45+2'``."""
    m, p = int(clock["minute"]), int(clock["period"])
    if p == 1 and m > 45:
        return f"45+{m - 45}'"
    if p == 2 and m > 90:
        return f"90+{m - 90}'"
    return f"{m}'"
