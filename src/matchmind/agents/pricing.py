"""What a model call costs, so every answer can say what it cost and the cost can be reduced on evidence.

Prices are US dollars per million tokens and are settings, not facts about the world: the table holds the published Azure OpenAI
Global Standard list prices of the deployments this project has used, as they were when this was written (October 2026), and the model is
the one named by ``MATCHMIND_LLM_MODEL``. Override with ``MATCHMIND_PRICE_IN_PER_M`` and ``MATCHMIND_PRICE_OUT_PER_M`` if the model or the
price changes. Cached-input discounts are not applied, so the figure is an upper bound.
"""

from __future__ import annotations

import os

# (input, output) per million tokens
LIST_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-6-luna": (0.10, 0.50),
    "gpt-6.1-sol": (2.00, 10.00),
}
DEFAULT_PRICE = LIST_PRICES["gpt-4.1-mini"]


def prices() -> tuple[float, float]:
    p_in, p_out = LIST_PRICES.get(os.environ.get("MATCHMIND_LLM_MODEL", ""), DEFAULT_PRICE)
    return float(os.environ.get("MATCHMIND_PRICE_IN_PER_M", p_in)), float(os.environ.get("MATCHMIND_PRICE_OUT_PER_M", p_out))


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = prices()
    return round((input_tokens * p_in + output_tokens * p_out) / 1_000_000, 6)
