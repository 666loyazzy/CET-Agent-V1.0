"""Deterministic chart evidence from private measurements, not model-generated scores."""

from __future__ import annotations

import math
from statistics import mean, median


def finite(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def bins(result: dict) -> list[float | None]:
    """Use observed frames only: never interpolate across an unvoiced gap."""
    groups = [[] for _ in range(60)]
    selection = result.get("selection", {})
    start, end = selection.get("start_s", 0), selection.get("end_s", 0)
    if end <= start:
        return [None] * 60
    chart = result.get("chart", {})
    for time_s, value in zip(chart.get("time_s", []), chart.get("semitones", [])):
        if finite(time_s) and finite(value) and start <= time_s <= end:
            groups[min(59, int(60 * (time_s - start) / (end - start)))].append(value)
    return [median(group) if group else None for group in groups]


def chart_evidence(result: dict) -> dict:
    chart, quality = result.get("chart", {}), result.get("quality", {})
    selection = result.get("selection", {})
    start, end = selection.get("start_s", 0), selection.get("end_s", 0)
    total, valid = quality.get("total_frames", 0), quality.get("valid_frames", 0)
    coverage = round(100 * valid / total, 1) if total else 0
    regions = []
    for index, label in enumerate(("前段", "中段", "后段")):
        lo, hi = start + (end - start) * index / 3, start + (end - start) * (index + 1) / 3
        values = [
            hz
            for t, hz in zip(chart.get("time_s", []), chart.get("f0_hz", []))
            if finite(t) and lo <= t and (t < hi or index == 2 and t <= hi)
        ]
        voiced = [v for v in values if finite(v) and v > 0]
        regions.append(
            {
                "label": label,
                "start_s": lo,
                "end_s": hi,
                "valid_frames": len(voiced),
                "total_frames": len(values),
                "median_f0_hz": round(median(voiced), 1) if len(voiced) >= 3 else None,
            }
        )
    reference = result.get("reference", {}).get("result")
    reason = "无参照音，仅展示本次观测。"
    pairs = []
    if reference:
        reason = "有效对照帧不足，暂不计算轮廓差。"
        # Alignment failure must never become a flattering score for a different script.
        if (
            result.get("words")
            and reference.get("words")
            and not quality.get("octave_jumps")
            and not reference.get("quality", {}).get("octave_jumps")
        ):
            pairs = [
                (i, abs(a - b))
                for i, (a, b) in enumerate(zip(bins(result), bins(reference)))
                if a is not None and b is not None
            ]
            if len(pairs) >= 6:
                reason = (
                    "按完整选区归一化时间，比较双方都有有效 F0 的时间格；差值越小表示轮廓越接近。"
                )
            else:
                pairs = []
        else:
            reason = "词语定位未完成或音高有倍频跳变，暂不计算参照偏差；曲线保留供回听。"
    deviations = []
    for index, region in enumerate(regions):
        differences = [value for i, value in pairs if index * 20 <= i < (index + 1) * 20]
        deviations.append(
            {
                "label": region["label"],
                "value": round(mean(differences), 2) if differences else None,
                "paired_bins": len(differences),
            }
        )

    def dimensions(data):
        q, f, s = data.get("quality", {}), data.get("features", {}), data.get("selection", {})
        return [
            f.get("pitch_range_st"),
            s.get("end_s", 0) - s.get("start_s", 0),
            round(100 * q.get("valid_frames", 0) / q["total_frames"], 1)
            if q.get("total_frames")
            else None,
            abs(f["ending_delta_st"]) if finite(f.get("ending_delta_st")) else None,
        ]

    current, target = dimensions(result), dimensions(reference) if reference else [None] * 4
    return {
        "version": "observed-charts-1.0",
        "coverage_percent": coverage,
        "regions": regions,
        "contour_mae_st": round(mean(value for _, value in pairs), 2) if pairs else None,
        "paired_bins": len(pairs),
        "comparison_note": reason,
        "deviations": deviations,
        "dimensions": [
            {"label": label, "unit": unit, "value": current[i], "reference": target[i]}
            for i, (label, unit) in enumerate(
                (("音域跨度", "半音"), ("选区时长", "秒"), ("有效 F0", "%"), ("收尾幅度", "半音"))
            )
        ],
    }
