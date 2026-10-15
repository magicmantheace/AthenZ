"""Privacy-safe aggregate statistics for paired decision prediction.

Operate on counts only; never handle owner choices, prompts, or model text.
Statistical tests assume independent held-out cases, which lexical dedupe
alone cannot establish.
"""
from __future__ import annotations

from math import comb, sqrt


def exact_paired_sign_test(twin_only: int, neutral_only: int) -> float | None:
    """Two-sided exact McNemar/binomial p under equal discordant success.

    A p-value is deliberately absent when no prediction outcomes disagree.
    Total discordant pairs are bounded by evaluation's 1000 case limit.
    """
    if (type(twin_only) is not int or type(neutral_only) is not int
            or min(twin_only, neutral_only) < 0
            or twin_only + neutral_only > 1000):
        raise ValueError("Invalid paired contingency counts")
    discordant = twin_only + neutral_only
    if not discordant:
        return None
    tail = sum(comb(discordant, k)
               for k in range(min(twin_only, neutral_only) + 1))
    return min(1.0, 2 * (tail / (2 ** discordant)))


def discordant_win_interval(twin_only: int, neutral_only: int) -> list[float] | None:
    """Descriptive 95% Wilson interval for wins among discordant pairs."""
    if (type(twin_only) is not int or type(neutral_only) is not int
            or min(twin_only, neutral_only) < 0
            or twin_only + neutral_only > 1000):
        raise ValueError("Invalid paired contingency counts")
    n = twin_only + neutral_only
    if n == 0:
        return None
    z = 1.959963984540054
    p = twin_only / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = (z * sqrt((p * (1 - p) / n) + z * z / (4 * n * n))) / denominator
    return [max(0.0, center - radius), min(1.0, center + radius)]
