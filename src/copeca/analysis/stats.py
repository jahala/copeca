"""Statistical functions — pure computation on lists of dicts (JSONL records).

Architecture: domain. No I/O, no imports from runners/repos/results/orchestration.
"""

import math
import random
from statistics import median as _median
from typing import Any


def compute_stats(records: list[dict[str, Any]], field: str = "total_cost_usd") -> dict[str, float]:
    """Return median, mean, stdev, min, max for a numeric field across records.

    Records missing the field or with None values are skipped.

    Args:
        records: List of dicts (JSONL records).
        field: The numeric field to compute stats over.

    Returns:
        Dict with keys: median, mean, stdev, min, max, count.
        All stats are 0.0 for an empty result set.
    """
    values: list[float] = []
    for r in records:
        v = r.get(field)
        if v is not None:
            values.append(float(v))

    if not values:
        return {
            "median": 0.0,
            "mean": 0.0,
            "stdev": 0.0,
            "min": 0.0,
            "max": 0.0,
            "count": 0,
        }

    count = len(values)
    mean_val = sum(values) / count
    min_val = min(values)
    max_val = max(values)
    med_val = _median(values)

    if count > 1:
        variance = sum((x - mean_val) ** 2 for x in values) / count
        stdev_val = math.sqrt(variance)
    else:
        stdev_val = 0.0

    return {
        "median": med_val,
        "mean": mean_val,
        "stdev": stdev_val,
        "min": min_val,
        "max": max_val,
        "count": count,
    }


def cost_per_correct(records: list[dict[str, Any]]) -> float | None:
    """Total cost divided by number of correct answers.

    Args:
        records: List of dicts with 'total_cost_usd' and 'correct' fields.

    Returns:
        USD cost per correct answer, or None if no correct answers (metric undefined).
    """
    correct_count = 0
    total_cost = 0.0
    for r in records:
        total_cost += float(r.get("total_cost_usd", 0.0))
        if r.get("correct"):
            correct_count += 1

    if correct_count == 0:
        return None

    return total_cost / correct_count


def group_by(records: list[dict[str, Any]], key: str) -> dict[Any, list[dict[str, Any]]]:
    """Group records by a key field (e.g. 'task', 'mode').

    Records missing the key are placed under None.

    Args:
        records: List of dicts (JSONL records).
        key: The field name to group by.

    Returns:
        Dict mapping key values to lists of records.
    """
    groups: dict[Any, list[dict[str, Any]]] = {}
    for r in records:
        group_val = r.get(key)
        if group_val not in groups:
            groups[group_val] = []
        groups[group_val].append(r)
    return groups


_TILES = " ▁▂▃▄▅▆▇█"


def ascii_sparkline(values: list[float], width: int = 20) -> str:
    """Render an ASCII sparkline for a sequence of values.

    Maps each value to a character in the tile set based on its position
    between min and max. Uses Unicode block elements for smooth rendering.

    Args:
        values: Sequence of numeric values.
        width: Number of characters in the output sparkline.

    Returns:
        ASCII sparkline string. Empty string if values is empty.
    """
    if not values:
        return ""

    mn = min(values)
    mx = max(values)
    rng = mx - mn

    # Sample evenly across the values to produce exactly `width` characters
    n = len(values)
    chars: list[str] = []
    for i in range(width):
        idx = int(i * (n - 1) / (width - 1)) if width > 1 else 0
        v = values[idx]
        if rng == 0:
            chars.append("─")
        else:
            bucket = int((v - mn) / rng * (len(_TILES) - 1))
            # Clamp to valid tile range (defensive against float edge cases)
            bucket = max(0, min(bucket, len(_TILES) - 1))
            chars.append(_TILES[bucket])

    return "".join(chars)


def bootstrap_ci(
    values: list[float], n_resamples: int = 10000, alpha: float = 0.05
) -> tuple[float, float, float, float]:
    """Bootstrapped confidence interval using the percentile method.

    Resamples with replacement from the input values, computes the mean of
    each resample, then takes the (alpha/2) and (1-alpha/2) percentiles
    as the confidence bounds.

    Args:
        values: List of numeric values to bootstrap.
        n_resamples: Number of bootstrap resamples (default 10000).
        alpha: Significance level (default 0.05 for 95% CI).

    Returns:
        Tuple of (lower_bound, upper_bound, median, mean).
        All values are 0.0 if the input list is empty.
    """
    if not values:
        return (0.0, 0.0, 0.0, 0.0)

    n = len(values)

    if n == 1:
        v = values[0]
        return (v, v, v, v)

    means: list[float] = []
    for _ in range(n_resamples):
        sample = random.choices(values, k=n)
        means.append(sum(sample) / n)

    means.sort()
    lower_idx = int(n_resamples * (alpha / 2))
    upper_idx = int(n_resamples * (1 - alpha / 2))
    lower = means[lower_idx]
    upper = means[min(upper_idx, n_resamples - 1)]

    med = _median(means)
    avg = sum(means) / n_resamples

    return (lower, upper, med, avg)
