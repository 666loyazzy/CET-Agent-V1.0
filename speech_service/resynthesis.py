# SPDX-License-Identifier: GPL-3.0-or-later
"""A pitch-only listening experiment; timing, articulation and energy are unchanged."""

import tempfile
from pathlib import Path

import numpy as np
import parselmouth
from parselmouth.praat import call

from .engine import LOCK, AudioError, decode


def synthesize(data: bytes, result: dict) -> bytes:
    reference = result.get("reference", {}).get("result")
    if not reference or result["quality"]["octave_jumps"]:
        raise AudioError("请先完成有可用参照且无倍频跳变的分析。")
    samples = decode(data)
    selected = result["selection"]
    algorithm = result["algorithm"]
    current_times = np.asarray(result["chart"]["time_s"])
    current_f0 = result["chart"]["f0_hz"]
    reference_times = np.asarray(reference["chart"]["time_s"])
    reference_st = reference["chart"]["semitones"]
    points = []
    # Only interpolate adjacent voiced reference frames inside matched words.
    for current_word, target_word in zip(result["words"], reference["words"]):
        duration = current_word["end_s"] - current_word["start_s"]
        target_duration = target_word["end_s"] - target_word["start_s"]
        for index in np.flatnonzero(
            (current_times >= current_word["start_s"]) & (current_times <= current_word["end_s"])
        ):
            if current_f0[index] is None:
                continue
            target_time = (
                target_word["start_s"]
                + (current_times[index] - current_word["start_s"]) / duration * target_duration
            )
            right = int(np.searchsorted(reference_times, target_time))
            hz = current_f0[index]
            if (
                0 < right < len(reference_times)
                and reference_st[right - 1] is not None
                and reference_st[right] is not None
            ):
                value = np.interp(
                    target_time,
                    reference_times[right - 1 : right + 1],
                    reference_st[right - 1 : right + 1],
                )
                hz = float(
                    np.clip(
                        result["features"]["median_f0_hz"] * 2 ** (value / 12),
                        algorithm["pitch_floor"],
                        algorithm["pitch_ceiling"],
                    )
                )
            points.append((float(current_times[index] - selected["start_s"]), hz))
    if len(points) < 6:
        raise AudioError("有效对照点不足，无法生成语调调整试听。")
    with LOCK, tempfile.TemporaryDirectory(prefix="cet-pitch-demo-") as folder:
        sound = parselmouth.Sound(samples, 16000).extract_part(
            selected["start_s"], selected["end_s"], preserve_times=False
        )
        manipulation = call(
            sound, "To Manipulation", 0.01, algorithm["pitch_floor"], algorithm["pitch_ceiling"]
        )
        tier = call(manipulation, "Extract pitch tier")
        call(tier, "Remove points between", sound.xmin, sound.xmax)
        for time_s, hz in sorted(dict(points).items()):
            call(tier, "Add point", time_s, hz)
        call([tier, manipulation], "Replace pitch tier")
        altered = call(manipulation, "Get resynthesis (overlap-add)")
        destination = Path(folder) / "pitch-demo.wav"
        altered.save(str(destination), parselmouth.SoundFileFormat.WAV)
        return destination.read_bytes()
