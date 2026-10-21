import io
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

np = pytest.importorskip("numpy")
pytest.importorskip("parselmouth")
pytest.importorskip("pocketsphinx")

from speech_service.app import app
from speech_service.catalog import EXERCISES
from speech_service.engine import AudioError, analyze

SAMPLES = Path(__file__).resolve().parents[1] / "speech_service" / "samples"


@pytest.mark.parametrize("exercise", EXERCISES, ids=lambda e: e["id"])
def test_fixed_samples_align_and_keep_real_evidence(exercise):
    events = []
    result = analyze(
        (SAMPLES / f"{exercise['id']}.wav").read_bytes(), exercise, on_trace=events.append
    )
    assert [word["text"] for word in result["words"]] == exercise["text"].lower().replace(
        ".", ""
    ).replace(",", "").replace("?", "").split()
    assert all(
        word["start_s"] < word["end_s"] <= result["duration_s"] + 0.02 for word in result["words"]
    )
    assert len(result["chart"]["time_s"]) == len(result["chart"]["f0_hz"])
    assert None in result["chart"]["f0_hz"]  # Preserve unvoiced intervals.
    assert any(e[-1]["status"] == "running" for e in events)
    assert all(e["status"] == "completed" for e in result["trace"])
    if exercise["kind"] == "word_stress":
        assert len(result["syllables"]) == 2


def wav_bytes(samples):
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return data.getvalue()


def test_invalid_audio_quality_and_selection_never_produce_scores():
    for data in (b"not audio", wav_bytes(np.zeros(16000)), wav_bytes(np.ones(16000) * 32767)):
        with pytest.raises(AudioError):
            analyze(data, EXERCISES[0])
    with pytest.raises(AudioError):
        analyze((SAMPLES / "present-noun.wav").read_bytes(), EXERCISES[0], start=10, end=20)


def test_stream_emits_running_completed_and_result():
    with TestClient(app) as client:
        response = client.post(
            "/analyze-stream",
            data={"exercise_id": "present-noun"},
            files={"file": ("audio.wav", (SAMPLES / "present-noun.wav").read_bytes())},
        )
        assert response.status_code == 200
        assert "event: trace" in response.text and '"status": "running"' in response.text
        assert "event: result" in response.text and "event: done" in response.text


def test_stream_failure_stops_before_later_stages():
    with TestClient(app) as client:
        response = client.post(
            "/analyze-stream",
            data={"exercise_id": "present-noun"},
            files={"file": ("empty.wav", wav_bytes(np.zeros(16000)))},
        )
        assert "event: error" in response.text
        assert "event: result" not in response.text
        assert "prosody.assess" not in response.text


@pytest.mark.parametrize("exercise", [EXERCISES[0], EXERCISES[4]], ids=lambda e: e["id"])
def test_pitch_only_resynthesis_is_real_audio_with_same_duration(exercise):
    from speech_service.engine import decode
    from speech_service.resynthesis import synthesize

    data = (SAMPLES / f"{exercise['id']}.wav").read_bytes()
    result = analyze(data, exercise)
    target = dict(result)
    result["reference"] = {"result": target}
    changed = synthesize(data, result)
    assert changed.startswith(b"RIFF")
    assert abs(len(decode(changed)) - len(decode(data))) <= 160
