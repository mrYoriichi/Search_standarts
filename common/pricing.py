"""OpenAI prices and call-cost calculation.

Two levels:
1. Raw per-1M-token prices — exact cost of a run from actual token usage.
2. Derived averages ($/page), measured on real documents — used by
   cli/forecast.py to predict processing cost without calling the LLM.

Update this file when OpenAI prices or models change.
Source: https://openai.com/pricing
"""

# Per-1M-token prices per model: (input, output).
MODEL_PRICES_PER_M: dict[str, tuple[float, float]] = {
    "gpt-5.6-sol": (5.0, 30.0),
    "gpt-5.6-luna": (0.20, 1.20),
    # Сняты с использования 2026-08-09 (заменены на sol и luna), но цены
    # остаются: у пользователей со старой версией эти модели могли остаться
    # в настройках и в истории запросов, иначе model_cost упадёт.
    "gpt-5.5": (5.0, 30.0),
    "gpt-5.4-mini": (0.75, 4.50),
}

# text-embedding-3-large
EMBEDDING_PRICE_PER_M: float | None = 0.13


def model_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """USD for one LLM call, from actual token usage and model."""
    prices = MODEL_PRICES_PER_M.get(model)
    if prices is None:
        raise RuntimeError(
            f"pricing.py has no prices for model {model!r}. "
            f"Add it to MODEL_PRICES_PER_M."
        )
    input_price, output_price = prices
    return (
        prompt_tokens * input_price / 1_000_000
        + completion_tokens * output_price / 1_000_000
    )


def embedding_cost(total_tokens: int) -> float:
    """USD for one embeddings call, from actual token usage."""
    if EMBEDDING_PRICE_PER_M is None:
        raise RuntimeError(
            "EMBEDDING_PRICE_PER_M is not set in pricing.py. "
            "Fill in the current OpenAI price."
        )
    return total_tokens * EMBEDDING_PRICE_PER_M / 1_000_000


# Averages for the no-LLM forecast: $/page with figures/tables, per vision
# model. Measured 2026-08-09 on MVL_649 (47 pages, 27 with figures/tables);
# both models saw identical input tokens, so the pair is directly comparable.
# Text-only pages are free (vision never sees them) and are NOT averaged in.
AVG_VISION_COST_PER_IMAGE_PAGE: dict[str, float] = {
    "gpt-5.6-luna": 0.0014,
    "gpt-5.6-sol": 0.036,
}
AVG_EMBEDDING_COST_PER_PAGE: float | None = 0.00014  # $/page, text-embedding-3-large
