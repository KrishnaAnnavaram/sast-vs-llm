"""Detection metrics with Wilson intervals, and the consistency of repeated runs."""

from __future__ import annotations

import math
from itertools import combinations


def wilson(successes: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95 % Wilson score interval of a proportion. (nan, nan) when ``total`` is 0."""
    if total <= 0:
        return float("nan"), float("nan")
    p = successes / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else float("nan")
    recall = tp / (tp + fn) if tp + fn else float("nan")
    if not (tp + fp) or not (tp + fn):
        f1 = float("nan")
    elif tp == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    p_lo, p_hi = wilson(tp, tp + fp)
    r_lo, r_hi = wilson(tp, tp + fn)
    return {"tp": tp, "fp": fp, "fn": fn, "precision": precision, "recall": recall, "f1": f1,
            "precision_ci": (p_lo, p_hi), "recall_ci": (r_lo, r_hi)}


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def mean_pairwise_jaccard(runs: list[set]) -> float:
    """Mean Jaccard similarity over all pairs of repeated runs (1.0 = identical runs)."""
    if len(runs) < 2:
        return float("nan")
    values = [jaccard(a, b) for a, b in combinations(runs, 2)]
    return sum(values) / len(values)
