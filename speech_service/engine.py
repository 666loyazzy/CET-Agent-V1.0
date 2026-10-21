# SPDX-License-Identifier: GPL-3.0-or-later
"""Measured prosody and approximate forced alignment, never a phoneme accuracy score."""

from __future__ import annotations

import hashlib
import re
import subprocess
import tempfile
import threading
import time
import wave
from pathlib import Path

import imageio_ffmpeg
import numpy as np
import parselmouth
from pocketsphinx import Decoder

from .catalog import VERSION

LOCK = threading.Lock()
VOWELS = {"AA", "AE", "AH", "AO", "AW", "AY", "EH", "ER", "EY", "IH", "IY", "OW", "OY", "UH", "UW"}
STAGES = (
    "audio.decode",
    "audio.quality",
    "praat.extract",
    "text.align",
    "prosody.features",
    "prosody.assess",
    "chart.validate",
)


class AudioError(ValueError):
    pass


def decode(data: bytes) -> np.ndarray:
    with tempfile.TemporaryDirectory(prefix="cet-speech-") as folder:
        source, output = Path(folder) / "source.audio", Path(folder) / "audio.wav"
        source.write_bytes(data)
        try:
            proc = subprocess.run(
                [
                    imageio_ffmpeg.get_ffmpeg_exe(),
                    "-nostdin",
                    "-v",
                    "error",
                    "-protocol_whitelist",
                    "file,pipe",
                    "-i",
                    str(source),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-t",
                    "30.1",
                    "-c:a",
                    "pcm_s16le",
                    "-threads",
                    "1",
                    str(output),
                ],
                capture_output=True,
                timeout=20,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AudioError("音频解码超时或 FFmpeg 不可用，请重新录制。") from exc
        if proc.returncode:
            raise AudioError("无法解码音频，请上传完整的 WAV、WebM、M4A、MP3 或 OGG。")
        with wave.open(str(output), "rb") as audio:
            samples = (
                np.frombuffer(audio.readframes(audio.getnframes()), dtype="<i2").astype(float)
                / 32768
            )
    if not 0.25 <= len(samples) / 16000 <= 30:
        raise AudioError("每次录音需要在 0.25–30 秒之间。")
    return samples


def align(samples: np.ndarray, exercise: dict, offset: float) -> list[dict]:
    decoder = Decoder(lm=None, samprate=16000, loglevel="ERROR")
    tokens = re.findall(r"[a-z]+(?:'[a-z]+)?", exercise["text"].lower())
    if exercise.get("pronunciation"):
        tokens[0] = "cet" + exercise["id"].replace("-", "")
        decoder.add_word(tokens[0], exercise["pronunciation"], update=True)
    decoder.set_align_text(" ".join(tokens))
    raw = np.clip(samples * 32767, -32768, 32767).astype("<i2").tobytes()
    phone_level = exercise["kind"] == "word_stress"
    for subwords in (False, True) if phone_level else (False,):
        if subwords:
            decoder.set_alignment()
        decoder.start_utt()
        decoder.process_raw(raw, full_utt=True)
        decoder.end_utt()
    alignment = decoder.get_alignment() if phone_level else list(decoder.seg())
    if alignment is None:
        raise AudioError("未能定位词语，请按题目完整跟读，或手动调整选区。")
    words = []
    for word in alignment:
        name = word.name if phone_level else word.word
        frame_start = word.start if phone_level else word.start_frame
        frame_end = word.start + word.duration if phone_level else word.end_frame + 1
        if name not in {"<sil>", "<s>", "</s>", "[SPEECH]", "+NSN+"}:
            words.append(
                {
                    "text": exercise["text"].lower()
                    if exercise.get("pronunciation")
                    else re.sub(r"\(\d+\)$", "", name),
                    "start_s": round(offset + frame_start / 100, 3),
                    "end_s": round(offset + frame_end / 100, 3),
                    "phones": [
                        {
                            "phone": phone.name,
                            "start_s": round(offset + phone.start / 100, 3),
                            "end_s": round(offset + (phone.start + phone.duration) / 100, 3),
                        }
                        for phone in (word if phone_level else [])
                    ],
                }
            )
    if len(words) != len(tokens) or any(w["end_s"] - w["start_s"] < 0.03 for w in words):
        raise AudioError("词语定位不完整，请回听确认读完全部文本，再调整选区或重录。")
    return words


def _measure_interval(samples, times, pitch, start, end, offset):
    section = samples[max(0, int((start - offset) * 16000)) : max(0, int((end - offset) * 16000))]
    frequencies = pitch[(times >= start) & (times <= end) & (pitch > 0)]
    return {
        "duration_s": round(end - start, 3),
        "energy_dbfs": round(
            float(20 * np.log10(max(np.sqrt(np.mean(section**2)) if len(section) else 0, 1e-6))), 2
        ),
        "median_f0_hz": round(float(np.median(frequencies)), 2) if len(frequencies) else None,
    }


def assess(
    exercise: dict, words: list[dict], syllables: list[dict], ending: float | None
) -> tuple[list[dict], list[dict]]:
    metrics, findings = [], []

    def add(code, label, state, value, unit, detail, start, end):
        metrics.append(
            {
                "code": code,
                "label": label,
                "state": state,
                "value": value,
                "unit": unit,
                "detail": detail,
            }
        )
        findings.append(
            {
                "issue_code": code,
                "state": state,
                "start_s": start,
                "end_s": end,
                "evidence": detail,
                "suggestion": exercise["tip"],
            }
        )

    if exercise["kind"] == "word_stress":
        expected = len(exercise["syllables"])
        if len(syllables) != expected or any(s["duration_s"] < 0.035 for s in syllables):
            add(
                "word_stress",
                "音节重音",
                "uncertain",
                None,
                "",
                "元音定位不足，先回听并调整选区。",
                words[0]["start_s"],
                words[-1]["end_s"],
            )
        else:
            # Heuristic prominence uses nucleus duration and relative energy, not calibrated probability.
            energy = np.array([s["energy_dbfs"] for s in syllables])
            durations = np.array([s["duration_s"] for s in syllables])
            salience = (energy - energy.mean()) / 6 + np.log(
                np.maximum(durations, 0.01) / np.median(durations)
            )
            expected_i, observed_i = exercise["stress_index"], int(np.argmax(salience))
            state = (
                "close"
                if float(np.ptp(salience)) < 0.3
                else "matched"
                if observed_i == expected_i
                else "adjust"
            )
            detail = f"目标为第 {expected_i + 1} 音节；时长与相对能量线索在第 {observed_i + 1} 音节更突出。"
            add(
                "word_stress",
                "音节重音",
                state,
                observed_i + 1,
                "音节",
                detail,
                words[0]["start_s"],
                words[-1]["end_s"],
            )
    elif exercise["kind"] == "sentence_stress":
        levels = np.array([w["energy_dbfs"] for w in words])
        target_i = exercise["target_index"]
        observed_i = int(np.argmax(levels))
        difference = float(levels[target_i] - np.median(levels))
        state = (
            "matched"
            if observed_i == target_i and difference >= 1
            else "close"
            if difference >= 0
            else "adjust"
        )
        add(
            "sentence_stress",
            "目标词突出程度",
            state,
            round(difference, 1),
            "dB",
            f"目标词 {words[target_i]['text']} 相对句内词语能量中位数为 {difference:+.1f} dB；这是突出程度线索，需结合回听。",
            words[target_i]["start_s"],
            words[target_i]["end_s"],
        )
    elif exercise["kind"] == "intonation":
        desired = 1 if exercise["direction"] == "rise" else -1
        state = (
            "uncertain"
            if ending is None
            else "matched"
            if ending * desired >= 1
            else "close"
            if ending * desired >= 0
            else "adjust"
        )
        add(
            "intonation",
            "收尾音高变化",
            state,
            ending,
            "半音",
            "收尾有效 F0 不足，暂不判断走势。"
            if ending is None
            else f"最后一段有效音高首尾变化 {ending:+.1f} 半音；本题指定{'上升' if desired == 1 else '下降'}收尾。",
            words[-1]["start_s"],
            words[-1]["end_s"],
        )
    else:
        index = exercise["boundary_after"]
        gap = round(max(0, words[index + 1]["start_s"] - words[index]["end_s"]), 3)
        state = "matched" if 0.08 <= gap <= 0.65 else "close" if gap < 0.08 else "adjust"
        add(
            "phrase_boundary",
            "意群边界间隔",
            state,
            gap,
            "秒",
            f"{words[index]['text']} 后的对齐间隔为 {gap:.2f} 秒；短间隔也可能通过句末延长形成边界，需要回听确认。",
            words[index]["end_s"],
            words[index + 1]["start_s"],
        )
    return metrics, findings


def analyze(
    data: bytes,
    exercise: dict,
    start: float | None = None,
    end: float | None = None,
    floor: float = 60,
    ceiling: float = 600,
    on_trace=None,
) -> dict:
    trace = []
    protocol = Path(__file__).with_name("protocol.md").read_text(encoding="utf-8")
    if any(name not in protocol for name in STAGES):
        raise AudioError("声学流程规范不完整。")
    skill_version = hashlib.sha256(protocol.encode()).hexdigest()[:12]

    def publish():
        if on_trace:
            on_trace([dict(entry) for entry in trace])

    def stage(name, operation):
        if len(trace) >= len(STAGES) or STAGES[len(trace)] != name:
            raise AudioError("分析执行顺序异常。")
        entry = {
            "id": name,
            "status": "running",
            "started_at": time.time(),
            "skill_version": skill_version,
        }
        trace.append(entry)
        publish()
        try:
            result = operation()
        except Exception:
            entry.update(status="failed", finished_at=time.time())
            publish()
            raise
        entry.update(status="completed", finished_at=time.time())
        publish()
        return result

    samples = stage("audio.decode", lambda: decode(data))
    duration = len(samples) / 16000

    def inspect():
        if (start is None) != (end is None):
            raise AudioError("请同时填写选区起点和终点，或都留空。")
        first, last = (0.0, duration) if start is None else (start, end)
        if (
            not np.all(np.isfinite([first, last, floor, ceiling]))
            or not (0 <= first < last <= duration + 0.001)
            or last - first < 0.2
        ):
            raise AudioError("选区需要在录音范围内，且至少 0.2 秒。")
        if not 50 <= floor < ceiling <= 1000:
            raise AudioError("音高范围需要满足 50 ≤ 下限 < 上限 ≤ 1000 Hz。")
        selected = samples[int(first * 16000) : int(last * 16000)]
        rms = float(np.sqrt(np.mean(selected**2)))
        clipped = float(np.mean(np.abs(selected) >= 0.995))
        quality = {
            "rms_dbfs": round(20 * np.log10(max(rms, 1e-6)), 2),
            "clipped_fraction": round(clipped, 5),
            "warnings": [],
        }
        if rms < 0.003:
            raise AudioError("录音接近静音，请靠近麦克风并确认音量后重录。")
        if clipped > 0.01:
            raise AudioError("录音削波较多，请降低输入音量后重录。")
        if rms < 0.01:
            quality["warnings"].append("录音音量偏低，请回听确认。")
        return selected, first, last, quality

    selected, start, end, quality = stage("audio.quality", inspect)

    def extract_pitch():
        pitch = parselmouth.Sound(selected, 16000).to_pitch_ac(
            time_step=0.01, pitch_floor=floor, pitch_ceiling=ceiling
        )
        if (pitch.selected_array["frequency"] > 0).sum() < 6:
            raise AudioError("有效音高不足，请检查录音、选区和音高范围后重试。")
        return pitch

    with LOCK:
        pitch = stage("praat.extract", extract_pitch)
        times = pitch.xs() + start
        values = pitch.selected_array["frequency"].copy()
        words = stage("text.align", lambda: align(selected, exercise, start))

    def features():
        for word in words:
            word.update(
                _measure_interval(selected, times, values, word["start_s"], word["end_s"], start)
            )
        syllables = []
        if exercise["kind"] == "word_stress":
            for phone in words[0]["phones"]:
                if re.sub(r"\d", "", phone["phone"]) in VOWELS:
                    i = len(syllables)
                    syllables.append(
                        {
                            "label": exercise["syllables"][i]
                            if i < len(exercise["syllables"])
                            else phone["phone"],
                            **phone,
                            **_measure_interval(
                                selected, times, values, phone["start_s"], phone["end_s"], start
                            ),
                        }
                    )
        return syllables

    syllables = stage("prosody.features", features)
    voiced = values > 0
    center = float(np.median(values[voiced]))
    relative = np.full(len(values), np.nan)
    relative[voiced] = 12 * np.log2(values[voiced] / center)
    terminal = values[(times >= max(words[-1]["start_s"], end - 0.8)) & voiced]
    delta = None
    if len(terminal) >= 6:
        count = max(2, len(terminal) // 4)
        delta = round(
            float(12 * np.log2(np.median(terminal[-count:]) / np.median(terminal[:count]))), 2
        )
    metrics, findings = stage("prosody.assess", lambda: assess(exercise, words, syllables, delta))
    adjacent = voiced[1:] & voiced[:-1]
    jumps = int(np.sum(adjacent & (np.abs(np.diff(relative)) >= 11)))
    if jumps:
        quality["warnings"].append("音高存在倍频跳变，请调整音高范围后复测；本次专项判断暂缓。")
        for metric in metrics:
            metric["state"] = "uncertain"
        for finding in findings:
            finding["state"] = "uncertain"
    quality.update(valid_frames=int(voiced.sum()), total_frames=len(values), octave_jumps=jumps)
    quality["warnings"].append("词语位置为固定文本的近似强制对齐，不代表已验证漏读或音素准确性。")
    size = max(1, len(samples) // 400)
    waveform = [
        [
            round(i / 16000, 4),
            round(float(np.min(samples[i : i + size])), 4),
            round(float(np.max(samples[i : i + size])), 4),
        ]
        for i in range(0, len(samples), size)
    ]
    energy = [
        _measure_interval(selected, times, values, max(start, t - 0.01), min(end, t + 0.01), start)[
            "energy_dbfs"
        ]
        for t in times
    ]
    result = {
        "version": VERSION,
        "exercise_id": exercise["id"],
        "duration_s": round(duration, 4),
        "selection": {"start_s": start, "end_s": end},
        "quality": quality,
        "words": words,
        "syllables": syllables,
        "metrics": metrics,
        "findings": findings,
        "trace": trace,
        "chart": {
            "time_s": np.round(times, 4).tolist(),
            "f0_hz": [round(float(v), 2) if v > 0 else None for v in values],
            "semitones": [round(float(v), 3) if np.isfinite(v) else None for v in relative],
            "energy_dbfs": energy,
            "waveform": waveform,
        },
        "features": {
            "median_f0_hz": round(center, 2),
            "pitch_range_st": round(
                float(np.percentile(relative[voiced], 90) - np.percentile(relative[voiced], 10)), 2
            ),
            "ending_delta_st": delta,
            "word_rate_per_minute": round(
                60 * len(words) / (words[-1]["end_s"] - words[0]["start_s"]), 1
            ),
        },
        "algorithm": {
            "alignment": "pocketsphinx-5.1.1-en-US",
            "pitch": "raw_autocorrelation",
            "praat": parselmouth.PRAAT_VERSION,
            "parselmouth": parselmouth.__version__,
            "pitch_floor": floor,
            "pitch_ceiling": ceiling,
            "step_s": 0.01,
        },
    }

    def validate_chart():
        if (
            len(times) != len(values)
            or not np.all(np.isfinite(times))
            or not np.all(np.diff(times) > 0)
        ):
            raise AudioError("图表时间异常。")

    stage("chart.validate", validate_chart)
    return result
