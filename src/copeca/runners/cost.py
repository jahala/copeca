"""Cost computation — pure function for tokens × pricing → USD.

Architecture: domain logic. No I/O, no imports from runners/repos/results/orchestration.
"""


def compute_cost(tokens: dict[str, int], pricing: dict[str, float]) -> float:
    """Compute USD cost from token counts × per-million pricing rates.

    Formula: (input_tokens × input + cache_creation_tokens × cache_creation
              + cache_read_tokens × cache_read + output_tokens × output) / 1_000_000

    Args:
        tokens: Dict with keys: input_tokens, output_tokens,
                cache_creation_tokens, cache_read_tokens
        pricing: Dict with keys: input, cache_creation, cache_read, output
                 (USD per 1M tokens)

    Returns:
        Cost in USD as a float.

    Raises:
        KeyError: If required keys are missing from tokens or pricing dicts.
    """
    numerator = (
        tokens["input_tokens"] * pricing["input"]
        + tokens["cache_creation_tokens"] * pricing["cache_creation"]
        + tokens["cache_read_tokens"] * pricing["cache_read"]
        + tokens["output_tokens"] * pricing["output"]
    )
    return numerator / 1_000_000
