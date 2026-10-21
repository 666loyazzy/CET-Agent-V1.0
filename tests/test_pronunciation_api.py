import json
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import speaking


@pytest.fixture
def clients(tmp_path, monkeypatch):
    monkeypatch.setattr(speaking.settings, "data_dir", tmp_path)
    monkeypatch.setattr(speaking.settings, "speaking_api_key", "")
    monkeypatch.setattr(speaking.settings, "writing_api_key", "")
    app = FastAPI()
    app.include_router(speaking.router, prefix="/api")
    speaking.initialize()
    with TestClient(app) as a, TestClient(app) as b:
        a.get("/api/speaking/catalog")
        b.get("/api/speaking/catalog")
        yield a, b


@pytest.fixture
def measured(monkeypatch):
    async def measure(data, exercise_id, options, on_trace=None):
        trace = [{"id": "audio.decode", "status": "running", "started_at": 1}]
        if on_trace:
            on_trace(trace)
        trace[0].update(status="completed", finished_at=2)
        return {
            "version": "test-1",
            "exercise_id": exercise_id,
            "algorithm": {
                "pitch_floor": options.get("pitch_floor", 60),
                "pitch_ceiling": options.get("pitch_ceiling", 600),
            },
            "chart": {"time_s": [0.1, 0.2], "f0_hz": [100, None]},
            "trace": trace,
            "quality": {"warnings": []},
            "metrics": [],
            "findings": [
                {
                    "issue_code": "word_stress",
                    "state": "adjust",
                    "evidence": "Test measured evidence.",
                    "suggestion": "Read and compare.",
                }
            ],
        }

    monkeypatch.setattr(speaking, "measure", measure)


def submit(client, **fields):
    return client.post(
        "/api/speaking/analyses",
        data={
            "exercise_id": "present-noun",
            "read_confirmed": "true",
            "reference_id": "none",
            **fields,
        },
        files={"file": ("sample.wav", b"fixed fixture audio", "audio/wav")},
    )


def test_private_history_audio_reference_coach_and_delete(clients, measured):
    a, b = clients
    response = submit(a)
    assert response.status_code == 202
    practice_id = response.json()["id"]
    detail = a.get(f"/api/speaking/practices/{practice_id}").json()
    assert detail["status"] == "completed"
    assert detail["trace"][-1]["id"] == "memory.update"
    assert all(step["status"] == "completed" for step in detail["trace"])
    assert a.get(detail["audio_url"]).content == b"fixed fixture audio"
    assert b.get("/api/speaking/practices").json() == []
    assert b.get(f"/api/speaking/practices/{practice_id}").status_code == 404
    assert b.get(detail["audio_url"]).status_code == 404
    assert b.post(f"/api/speaking/practices/{practice_id}/reference").status_code == 404
    assert b.delete(f"/api/speaking/practices/{practice_id}").status_code == 404
    coached = a.post(f"/api/speaking/practices/{practice_id}/coach-stream", json={})
    assert "event: result" in coached.text and "coach.save" in coached.text
    assert a.get(f"/api/speaking/practices/{practice_id}/coaching").json()[0]["source"] == "local"
    assert b.get(f"/api/speaking/practices/{practice_id}/coaching").status_code == 404
    assert a.get("/api/speaking/memory").json()["patterns"]["word_stress"] == 1
    assert a.delete(f"/api/speaking/practices/{practice_id}").status_code == 204
    assert a.get("/api/speaking/memory").json()["facts"] == []
    assert not list(speaking.root().glob("*.audio"))


def test_memory_disable_and_clear_do_not_delete_history(clients, measured):
    a, _ = clients
    submit(a)
    assert len(a.get("/api/speaking/memory").json()["facts"]) == 1
    assert a.put("/api/speaking/memory", json={"enabled": False}).json()["facts"] == []
    submit(a)
    a.put("/api/speaking/memory", json={"enabled": True})
    assert len(a.get("/api/speaking/memory").json()["facts"]) == 1
    assert a.put("/api/speaking/memory", json={"clear": True}).json()["facts"] == []
    assert len(a.get("/api/speaking/practices").json()) == 2


def test_reference_ownership_exercise_and_parameter_guards(clients, measured):
    a, b = clients
    first = submit(a).json()["id"]
    assert a.post(f"/api/speaking/practices/{first}/reference").status_code == 200
    second = submit(a, reference_id=first).json()["id"]
    assert a.get(f"/api/speaking/practices/{second}").json()["status"] == "completed"
    for client, fields in [
        (b, {"reference_id": first}),
        (a, {"reference_id": first, "exercise_id": "record-noun"}),
        (a, {"reference_id": first, "pitch_floor": "80"}),
    ]:
        wrong = submit(client, **fields).json()["id"]
        assert client.get(f"/api/speaking/practices/{wrong}").json()["status"] == "failed"


def test_validation_and_csrf(clients):
    a, _ = clients
    assert submit(a, exercise_id="unknown").status_code == 404
    assert submit(a, read_confirmed="false").status_code == 422
    assert submit(a, start_s="0").status_code == 422
    assert submit(a, pitch_floor="nan").status_code == 422
    assert (
        a.post("/api/speaking/analyses", headers={"origin": "https://other.example"}).status_code
        == 403
    )


def test_failure_keeps_real_trace_and_original_audio(clients, monkeypatch):
    a, _ = clients

    async def fail(data, exercise_id, options, on_trace=None):
        on_trace([{"id": "audio.quality", "status": "running", "started_at": 1}])
        raise HTTPException(422, "Recording is silent.")

    monkeypatch.setattr(speaking, "measure", fail)
    practice_id = submit(a).json()["id"]
    result = a.get(f"/api/speaking/practices/{practice_id}").json()
    assert result["status"] == "failed" and result["trace"][0]["status"] == "failed"
    assert result["result"] is None
    assert a.get(result["audio_url"]).status_code == 200


def test_restart_marks_interrupted_jobs_and_cleans_expired_audio(clients):
    a, _ = clients
    with speaking.database() as db:
        for key, created in [("expired", 0), ("unfinished", 9999999999)]:
            db.execute(
                "INSERT INTO practices(id,owner,exercise,created,status,media_type) VALUES(?,?,?,?,?,?)",
                (key, "test", "present-noun", created, "processing", "audio/wav"),
            )
            (speaking.root() / f"{key}.audio").write_bytes(b"fixture")
    speaking.initialize()
    with speaking.database() as db:
        assert (
            db.execute("SELECT status FROM practices WHERE id=?", ("unfinished",)).fetchone()[0]
            == "failed"
        )
        assert db.execute("SELECT * FROM practices WHERE id=?", ("expired",)).fetchone() is None
    assert not (speaking.root() / "expired.audio").exists()


@pytest.mark.parametrize("mode", ["success", "unsupported_number", "provider_failure"])
def test_model_contract_and_private_failure_fallback(clients, measured, monkeypatch, mode):
    from types import SimpleNamespace

    a, _ = clients
    practice_id = submit(a).json()["id"]
    monkeypatch.setattr(speaking.settings, "speaking_api_key", "offline-fixture-token")
    seen = {}

    class ModelClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def create(self, **kwargs):
            seen.update(kwargs)
            if mode == "provider_failure":
                raise RuntimeError("offline-fixture-token")
            answer = (
                "Your pitch was 99999 Hz."
                if mode == "unsupported_number"
                else "Listen to the first syllable, then read the word again."
            )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=answer))]
            )

    monkeypatch.setattr(speaking, "AsyncOpenAI", ModelClient)
    a.put("/api/speaking/memory", json={"enabled": False})
    response = a.post(
        f"/api/speaking/practices/{practice_id}/coach", json={"model": "deepseek-v4-pro"}
    )
    assert response.status_code == 200
    assert response.json()["source"] == ("model" if mode == "success" else "local")
    assert "offline-fixture-token" not in response.text
    assert seen["model"] == "deepseek-v4-pro"
    assert json.loads(seen["messages"][1]["content"])["memory"]["facts"] == []
    assert (
        a.post(
            f"/api/speaking/practices/{practice_id}/coach", json={"model": "unknown"}
        ).status_code
        == 422
    )
