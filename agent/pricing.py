"""agent/pricing.py — turn tokens into dollars, at read time.

Philosophy borrowed from waku-agent: the ledger stores TOKENS (they never
change), and dollar cost is derived from these tables on every read. Fixing a
wrong rate here silently corrects every past turn's displayed cost.

Rates are $/1M tokens (input, output). Values are standard list prices from
OpenRouter's catalog — verify against openrouter.ai/models when models change.
"""

from __future__ import annotations

# Exact per-model rates for CHAT_MODELS / CUSTOM_MODELS entries (config.py)
MODEL_PRICING = {
    "google/gemini-3.8-flash": (0.825, 4.125),  # Flash / Vision
    "google/gemini-3.1-pro-preview": (2.00, 12.00),  # Deep Think
    "google/gemma-4-31b-it": (0.20, 0.40),  # SITREP pipeline default
    # CUSTOM_MODELS
    "deepseek/deepseek-chat": (0.257, 1.029),
    "openai/gpt-5.1": (1.25, 10.00),
    "z-ai/glm-4.6": (0.50, 2.00),
    "openai/gpt-4o-mini": (0.15, 0.60),
    "anthropic/claude-sonnet-4.5": (3.00, 15.00),
    "openai/gpt-4o": (2.50, 10.00),
}

# Rough mid-catalog guess for any OpenRouter model not listed above
DEFAULT_PRICING = (1.0, 3.0)

# Self-hosted models cost nothing per token
FREE_PRICING = (0.0, 0.0)


def price_for(model: str, provider: str = "") -> tuple[float, float]:
    """$/M tokens (in, out) for one model id, with an honest fallback."""
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    if provider == "ollama":
        return FREE_PRICING
    return DEFAULT_PRICING


def compute_cost(tokens_in: int, tokens_out: int, model: str, provider: str = "") -> float:
    """Dollar cost of one turn (or a set of calls) from token counts."""
    pin, pout = price_for(model, provider)
    return tokens_in / 1e6 * pin + tokens_out / 1e6 * pout
