from __future__ import annotations

import math
import statistics
from collections import Counter
from typing import Iterable

from backend.writing.schemas import score_band


def _median(values: Iterable[int]) -> float:
    return float(statistics.median(values))


def _mad(values: list[int]) -> float:
    center = _median(values)
    return float(statistics.median(abs(value - center) for value in values))


def _entropy(values: list[int]) -> float:
    counts = Counter(values)
    size = len(values)
    return -sum((count / size) * math.log2(count / size) for count in counts.values())


def _side(scores: list[int]) -> dict:
    bands = [score_band(score) for score in scores]
    return {
        "scores": scores,
        "median": _median(scores),
        "mad": _mad(scores),
        "range": max(scores) - min(scores),
        "bands": bands,
        "band_entropy": _entropy(bands),
        "cross_band": len(set(bands)) > 1,
    }


def assess_reliability(strict: list[dict], lenient: list[dict]) -> dict:
    strict_stats = _side([item["score"] for item in strict])
    lenient_stats = _side([item["score"] for item in lenient])
    median_gap = abs(strict_stats["median"] - lenient_stats["median"])
    strict_band = score_band(round(strict_stats["median"]))
    lenient_band = score_band(round(lenient_stats["median"]))
    band_centers = [2, 5, 8, 11, 14]
    band_distance = abs(band_centers.index(strict_band) - band_centers.index(lenient_band))

    stable = (
        median_gap <= 1
        and strict_stats["mad"] <= 0.5
        and lenient_stats["mad"] <= 0.5
        and strict_stats["range"] <= 2
        and lenient_stats["range"] <= 2
        and not strict_stats["cross_band"]
        and not lenient_stats["cross_band"]
    )
    severe = (
        median_gap >= 3
        or band_distance >= 2
        or (strict_stats["mad"] > 1 and lenient_stats["mad"] > 1)
        or strict_stats["range"] >= 4
        or lenient_stats["range"] >= 4
    )
    return {
        "strict": strict_stats,
        "lenient": lenient_stats,
        "median_gap": median_gap,
        "band_distance": band_distance,
        "stable": stable,
        "review_level": "none" if stable else ("full" if severe else "light"),
    }
