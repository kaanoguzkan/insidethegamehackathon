"""What a model call costs, so every answer can say what it cost and the cost can be reduced on evidence.

Prices are US dollars per million tokens and are settings, not facts about the world: the defaults are the published Azure OpenAI
Global Standard list price for ``gpt-4.1-mini`` (0.40 input, 1.60 output) when this was written (October 2026). Change them with
``MATCHMIND_PRICE_IN_PER_M`` and ``MATCHMIND_PRICE_OUT_PER_M`` if the model or the price changes. Cached-input discounts are not applied,
so the figure is an upper bound.
"""

from __future__ import annotations

import os


def prices() -> tuple[float, float]:
    return float(os.environ.get("MATCHMIND_PRICE_IN_PER_M", "0.40")), float(os.environ.get("MATCHMIND_PRICE_OUT_PER_M", "1.60"))


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = prices()
    return round((input_tokens * p_in + output_tokens * p_out) / 1_000_000, 6)
