"""Same-origin API for private English pronunciation practices and a local acoustic worker."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.responses import Response as AudioResponse
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from backend.config import PROJECT_ROOT, settings
from backend.speaking_visuals import chart_evidence
from speech_service.catalog import BY_ID, EXERCISES, VERSION

router = APIRouter(prefix="/speaking", tags=["speaking"])
MAX_BYTES = 12 * 1024 * 1024
QUEUE = asyncio.Semaphore(2)
SAMPLES = PROJECT_ROOT / "speech_service" / "samples"


def root() -> Path:
    folder = settings.data_dir / "speaking"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


@contextmanager
def database():
    with sqlite3.connect(root() / "practices.sqlite3", timeout=10) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("""CREATE TABLE IF NOT EXISTS practices (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, exercise TEXT NOT NULL, created REAL NOT NULL,
            status TEXT NOT NULL, result TEXT, error TEXT, media_type TEXT NOT NULL, is_reference INTEGER NOT NULL DEFAULT 0)""")
        conn.execute("CREATE INDEX IF NOT EXISTS owner_practices ON practices(owner, created)")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS preferences (owner TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1, since REAL NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS coaching (id TEXT PRIMARY KEY, practice TEXT NOT NULL, owner TEXT NOT NULL, created REAL NOT NULL, question TEXT NOT NULL, answer TEXT NOT NULL, source TEXT NOT NULL, trace TEXT NOT NULL)"
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(practices)")}
        if "memory_eligible" not in columns:
            conn.execute(
                "ALTER TABLE practices ADD COLUMN memory_eligible INTEGER NOT NULL DEFAULT 1"
            )
        yield conn


def initialize():
    with database() as db:
        db.execute(
            "UPDATE practices SET status='failed', error='服务已重启，请重新提交录音。' WHERE status IN ('queued','processing')"
        )
        old = db.execute(
            "SELECT id FROM practices WHERE created < ?", (time.time() - 30 * 86400,)
        ).fetchall()
        for row in old:
            (root() / (row["id"] + ".audio")).unlink(missing_ok=True)
            db.execute("DELETE FROM coaching WHERE practice=?", (row["id"],))
        db.execute("DELETE FROM practices WHERE created < ?", (time.time() - 30 * 86400,))


def owner(request: Request, response: Response) -> str:
    if request.method not in ("GET", "HEAD"):
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "请从本站页面提交练习。")
    token = request.cookies.get("cet-speaking-session", "")
    if not re.fullmatch(r"[0-9a-f]{64}", token):
        token = secrets.token_hex(32)
        response.set_cookie(
            "cet-speaking-session",
            token,
            max_age=30 * 86400,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="strict",
        )
    return hashlib.sha256(token.encode()).hexdigest()


def practice(practice_id: str, user: str) -> dict:
    with database() as db:
        row = db.execute(
            "SELECT * FROM practices WHERE id=? AND owner=?", (practice_id, user)
        ).fetchone()
    if not row:
        raise HTTPException(404, "练习不存在或不属于当前会话。")
    return dict(row)


def unpack(row: dict) -> dict:
    result = json.loads(row["result"]) if row.get("result") else None
    observations = None
    if result and "chart" in result:
        result["visuals"] = chart_evidence(result)
        observations = {
            "comparison_key": result.get("comparison_key"),
            "contour_mae_st": result["visuals"]["contour_mae_st"],
            "coverage_percent": result["visuals"]["coverage_percent"],
            "pitch_range_st": result.get("features", {}).get("pitch_range_st"),
            "duration_s": result.get("selection", {}).get("end_s", 0)
            - result.get("selection", {}).get("start_s", 0),
        }
    return {
        "id": row["id"],
        "exercise_id": row["exercise"],
        "created_at": row["created"],
        "status": row["status"],
        "result": result if result and "chart" in result else None,
        "trace": result.get("trace", []) if result else [],
        "error": row.get("error"),
        "audio_url": f"/api/speaking/practices/{row['id']}/audio",
        "is_reference": bool(row["is_reference"]),
        "observations": observations,
    }


async def uploaded(file: UploadFile) -> bytes:
    data = await file.read(MAX_BYTES + 1)
    if not data or len(data) > MAX_BYTES:
        raise HTTPException(413, "录音不能为空，且最多 12 MB。")
    return data


async def measure(data: bytes, exercise_id: str, options: dict, on_trace=None) -> dict:
    try:
        async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
            async with client.stream(
                "POST",
                settings.speaking_service_url.rstrip("/") + "/analyze-stream",
                data={
                    "exercise_id": exercise_id,
                    **{k: str(v) for k, v in options.items() if v is not None},
                },
                files={"file": ("recording.audio", data, "application/octet-stream")},
            ) as upstream:
                upstream.raise_for_status()
                event, result = "", None
                async for line in upstream.aiter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        payload = json.loads(line[6:])
                        if event == "trace" and on_trace:
                            on_trace(payload["trace"])
                        elif event == "result":
                            result = payload
                        elif event == "error":
                            raise HTTPException(422, payload["message"])
                if result is None:
                    raise HTTPException(503, "声学服务未返回完整结果，请重试。")
                return result
    except httpx.HTTPError as exc:
        raise HTTPException(503, "声学服务暂不可用，请启动英语发音分析服务后重试。") from exc


@router.get("/catalog")
def catalog(user: str = Depends(owner)):
    return {
        "version": VERSION,
        "exercises": [
            dict(item, reference_available=(SAMPLES / f"{item['id']}.wav").exists())
            for item in EXERCISES
        ],
        "max_seconds": 30,
        "max_bytes": MAX_BYTES,
        "retention_days": 30,
    }


@router.get("/status")
async def status(user: str = Depends(owner)):
    try:
        async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
            response = await client.get(settings.speaking_service_url.rstrip("/") + "/health")
            response.raise_for_status()
        return {"available": True, "version": response.json().get("version")}
    except (httpx.HTTPError, ValueError):
        return {"available": False, "message": "声学分析服务尚未启动；仍可听示范、录音和回听。"}


@router.get("/samples/{exercise_id}")
def sample_audio(exercise_id: str):
    if exercise_id not in BY_ID or not (SAMPLES / f"{exercise_id}.wav").exists():
        raise HTTPException(404, "此题暂无内置示范，可使用浏览器朗读或上传参照音。")
    return FileResponse(SAMPLES / f"{exercise_id}.wav", media_type="audio/wav")


async def run_analysis(practice_id: str, user: str, options: dict, reference_id: str):
    async with QUEUE:
        try:
            row = practice(practice_id, user)
            with database() as db:
                db.execute("UPDATE practices SET status='processing' WHERE id=?", (practice_id,))

            def progress(trace):
                with database() as db:
                    db.execute(
                        "UPDATE practices SET result=? WHERE id=?",
                        (json.dumps({"trace": trace}), practice_id),
                    )

            result = await measure(
                (root() / f"{practice_id}.audio").read_bytes(), row["exercise"], options, progress
            )
            result["trace"].append(
                {
                    "id": "reference.compare",
                    "status": "running",
                    "started_at": time.time(),
                    "skill_version": result["trace"][0].get("skill_version", VERSION),
                }
            )
            progress(result["trace"])
            reference = None
            reference_key = "none"
            if reference_id == "builtin" and (SAMPLES / f"{row['exercise']}.wav").exists():
                reference = await measure(
                    (SAMPLES / f"{row['exercise']}.wav").read_bytes(),
                    row["exercise"],
                    {
                        "pitch_floor": options["pitch_floor"],
                        "pitch_ceiling": options["pitch_ceiling"],
                    },
                )
                reference_key = hashlib.sha256(
                    (SAMPLES / f"{row['exercise']}.wav").read_bytes()
                ).hexdigest()[:16]
                result["reference"] = {
                    "label": "合成练习示范（非教师金标）",
                    "result": reference,
                    "audio_url": f"/api/speaking/samples/{row['exercise']}",
                }
            elif reference_id not in ("builtin", "none"):
                reference_row = practice(reference_id, user)
                if (
                    reference_row["exercise"] != row["exercise"]
                    or reference_row["status"] != "completed"
                    or not reference_row["is_reference"]
                ):
                    raise HTTPException(422, "参照音与当前题目不匹配。")
                reference = json.loads(reference_row["result"])
                reference.pop("reference", None)
                if reference["algorithm"] != result["algorithm"]:
                    raise HTTPException(422, "参照音的音高参数不同，请使用相同参数重新上传。")
                if reference.get("alignment", {}).get("status") == "unavailable":
                    raise HTTPException(422, "参照音的词语定位不足，请选择完整跟读的参照录音。")
                reference_key = reference_id
                result["reference"] = {
                    "label": "本人上传的参照音",
                    "result": reference,
                    "audio_url": f"/api/speaking/practices/{reference_id}/audio",
                }
            key = [row["exercise"], result["version"], result["algorithm"], reference_key]
            result["comparison_key"] = hashlib.sha256(
                json.dumps(key, sort_keys=True).encode()
            ).hexdigest()[:20]
            result["summary"] = (
                "词语定位未完成，已保留真实声学观测；请完整跟读当前题目后复测。"
                if result.get("alignment", {}).get("status") == "unavailable"
                else BY_ID[row["exercise"]]["tip"]
            )
            result["trace"][-1].update(status="completed", finished_at=time.time())
            result["trace"].append(
                {
                    "id": "memory.update",
                    "status": "running",
                    "started_at": time.time(),
                    "skill_version": result["trace"][0].get("skill_version", VERSION),
                }
            )
            progress(result["trace"])
            with database() as db:
                result["trace"][-1].update(status="completed", finished_at=time.time())
                prefs = db.execute(
                    "SELECT enabled FROM preferences WHERE owner=?", (user,)
                ).fetchone()
                db.execute(
                    "UPDATE practices SET status='completed', result=?, memory_eligible=? WHERE id=?",
                    (
                        json.dumps(result, ensure_ascii=False, allow_nan=False),
                        int(prefs is None or prefs["enabled"]),
                        practice_id,
                    ),
                )
        except HTTPException as exc:
            fail_practice(practice_id, str(exc.detail))
        except Exception:
            fail_practice(practice_id, "分析未完成，请重试；原录音已保留。")


def fail_practice(practice_id: str, message: str):
    with database() as db:
        row = db.execute("SELECT result FROM practices WHERE id=?", (practice_id,)).fetchone()
        payload = json.loads(row["result"]) if row and row["result"] else {"trace": []}
        for step in payload["trace"]:
            if step["status"] == "running":
                step.update(status="failed", finished_at=time.time())
        db.execute(
            "UPDATE practices SET status='failed', error=?, result=? WHERE id=?",
            (message, json.dumps(payload), practice_id),
        )


@router.post("/analyses", status_code=202)
async def submit(
    background: BackgroundTasks,
    exercise_id: str = Form(...),
    file: UploadFile = File(...),
    read_confirmed: bool = Form(False),
    start_s: float | None = Form(None),
    end_s: float | None = Form(None),
    pitch_floor: float = Form(60),
    pitch_ceiling: float = Form(600),
    reference_id: str = Form("builtin"),
    user: str = Depends(owner),
):
    if exercise_id not in BY_ID:
        raise HTTPException(404, "练习不存在。")
    if not read_confirmed:
        raise HTTPException(422, "请先回听并确认录音读的是当前题目。")
    if (start_s is None) != (end_s is None) or not 50 <= pitch_floor < pitch_ceiling <= 1000:
        raise HTTPException(422, "请检查选区和音高范围。")
    data = await uploaded(file)
    practice_id = str(uuid4())
    with database() as db:
        queued = db.execute(
            "SELECT COUNT(*) FROM practices WHERE owner=? AND status IN ('queued','processing')",
            (user,),
        ).fetchone()[0]
        if queued >= 2:
            raise HTTPException(429, "已有两次练习等待分析，请完成后再提交。")
        total = db.execute(
            "SELECT COUNT(*) FROM practices WHERE owner=? AND created>?",
            (user, time.time() - 86400),
        ).fetchone()[0]
        if total >= 100:
            raise HTTPException(429, "今天的录音数量已达到 100 次，请明天继续。")
        media = file.content_type or "application/octet-stream"
        db.execute(
            "INSERT INTO practices(id,owner,exercise,created,status,media_type) VALUES(?,?,?,?,?,?)",
            (
                practice_id,
                user,
                exercise_id,
                time.time(),
                "queued",
                media if media.startswith("audio/") else "application/octet-stream",
            ),
        )
        (root() / f"{practice_id}.audio").write_bytes(data)
    background.add_task(
        run_analysis,
        practice_id,
        user,
        {
            "start_s": start_s,
            "end_s": end_s,
            "pitch_floor": pitch_floor,
            "pitch_ceiling": pitch_ceiling,
        },
        reference_id,
    )
    return {"id": practice_id, "status": "queued"}


@router.get("/practices")
def history(user: str = Depends(owner)):
    with database() as db:
        rows = db.execute(
            "SELECT * FROM practices WHERE owner=? ORDER BY created DESC LIMIT 100", (user,)
        ).fetchall()
    return [{k: v for k, v in unpack(dict(row)).items() if k != "result"} for row in rows]


@router.get("/practices/{practice_id}")
def detail(practice_id: str, user: str = Depends(owner)):
    return unpack(practice(practice_id, user))


@router.get("/practices/{practice_id}/audio")
def audio(practice_id: str, user: str = Depends(owner)):
    row = practice(practice_id, user)
    path = root() / f"{row['id']}.audio"
    if not path.exists():
        raise HTTPException(410, "录音已清理。")
    return FileResponse(
        path,
        media_type=row["media_type"],
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.delete("/practices/{practice_id}", status_code=204)
def delete(practice_id: str, user: str = Depends(owner)):
    row = practice(practice_id, user)
    if row["status"] in ("queued", "processing"):
        raise HTTPException(409, "请等待分析结束后再删除。")
    with database() as db:
        db.execute("DELETE FROM practices WHERE id=? AND owner=?", (practice_id, user))
        db.execute("DELETE FROM coaching WHERE practice=? AND owner=?", (practice_id, user))
        (root() / f"{practice_id}.audio").unlink(missing_ok=True)


@router.post("/practices/{practice_id}/reference")
def use_as_reference(practice_id: str, user: str = Depends(owner)):
    row = practice(practice_id, user)
    if row["status"] != "completed":
        raise HTTPException(422, "分析成功的录音才可用作参照。")
    if json.loads(row["result"]).get("alignment", {}).get("status") == "unavailable":
        raise HTTPException(422, "词语未能完整定位，请重新跟读分析后再设为参照。")
    with database() as db:
        db.execute(
            "UPDATE practices SET is_reference=1 WHERE id=? AND owner=?", (practice_id, user)
        )
    return {"id": practice_id, "label": "本人选择的参照音（非教师认证）"}


@router.get("/memory")
def memory(user: str = Depends(owner)):
    with database() as db:
        db.execute("INSERT OR IGNORE INTO preferences(owner) VALUES(?)", (user,))
        prefs = db.execute("SELECT * FROM preferences WHERE owner=?", (user,)).fetchone()
        rows = (
            db.execute(
                "SELECT * FROM practices WHERE owner=? AND status='completed' AND is_reference=0 AND memory_eligible=1 AND created>? ORDER BY created DESC LIMIT 20",
                (user, prefs["since"]),
            ).fetchall()
            if prefs["enabled"]
            else []
        )
    counts = {}
    facts = []
    for row in rows:
        result = json.loads(row["result"])
        for finding in result["findings"]:
            if finding["state"] == "adjust":
                code = finding["issue_code"]
                counts[code] = counts.get(code, 0) + 1
        facts.append(
            {
                "practice_id": row["id"],
                "exercise_id": row["exercise"],
                "version": result["version"],
                "summary": result["summary"],
                "created_at": row["created"],
                "metrics": result["metrics"],
                "features": result.get("features", {}),
                "comparison_key": result["comparison_key"],
            }
        )
    return {"enabled": bool(prefs["enabled"]), "patterns": counts, "facts": facts}


class MemoryUpdate(BaseModel):
    enabled: bool | None = None
    clear: bool = False


@router.put("/memory")
def update_memory(update: MemoryUpdate, user: str = Depends(owner)):
    with database() as db:
        db.execute("INSERT OR IGNORE INTO preferences(owner) VALUES(?)", (user,))
        if update.enabled is not None:
            db.execute(
                "UPDATE preferences SET enabled=? WHERE owner=?", (int(update.enabled), user)
            )
        if update.clear:
            db.execute("UPDATE preferences SET since=? WHERE owner=?", (time.time(), user))
    return memory(user)


class TutorInput(BaseModel):
    question: str = Field(default="这次应该如何改进？", min_length=1, max_length=1000)
    model: str = Field(default="deepseek-flash", pattern=r"^(deepseek-flash|deepseek-v4-pro)$")


@router.post("/practices/{practice_id}/coach")
async def coach(practice_id: str, body: TutorInput, user: str = Depends(owner)):
    result = None
    async for event, payload in coaching_events(practice_id, body, user):
        if event == "result":
            result = payload
    return result


async def coaching_events(practice_id: str, body: TutorInput, user: str):
    trace = []

    def begin(name, **extra):
        trace.append({"id": name, "status": "running", "started_at": time.time(), **extra})

    def finish():
        trace[-1].update(status="completed", finished_at=time.time())

    begin("coach.context")
    yield "trace", {"trace": trace}
    row = practice(practice_id, user)
    if row["status"] != "completed":
        raise HTTPException(422, "请先完成录音分析。")
    result = json.loads(row["result"])
    evidence = {
        "exercise": BY_ID[row["exercise"]],
        "metrics": result["metrics"],
        "quality": result["quality"],
        "alignment": result.get("alignment"),
        "findings": result["findings"],
        "memory": memory(user),
        "question": body.question,
    }
    fallback = "\n".join(f["evidence"] + "\n" + f["suggestion"] for f in result["findings"])
    finish()
    instruction = (PROJECT_ROOT / "skill" / "speaking-coach.md").read_text(encoding="utf-8")
    begin("coach.skills", skill_version=hashlib.sha256(instruction.encode()).hexdigest()[:12])
    yield "trace", {"trace": trace}
    finish()
    begin("coach.generate")
    yield "trace", {"trace": trace}
    api_key = settings.speaking_api_key or settings.writing_api_key
    source, text, notice = "local", fallback, ""
    if api_key:
        try:
            async with AsyncOpenAI(
                api_key=api_key,
                base_url=settings.speaking_base_url or settings.writing_base_url,
                timeout=45,
                max_retries=0,
            ) as client:
                answer = await client.chat.completions.create(
                    model=body.model,
                    messages=[
                        {"role": "system", "content": instruction},
                        {"role": "user", "content": json.dumps(evidence, ensure_ascii=False)},
                    ],
                    max_tokens=1600,
                    extra_body={"thinking": {"type": "disabled"}},
                )
            text = answer.choices[0].message.content or ""
            if not text.strip():
                raise ValueError("empty")
            source = "model"
        except Exception:
            notice = "模型讲解暂不可用，以下为实测结果对应的本地建议。"
            text = fallback
    finish()
    begin("coach.validate")
    yield "trace", {"trace": trace}
    serialized = json.dumps(evidence, ensure_ascii=False)
    measured_numbers = re.findall(
        r"(\d+(?:\.\d+)?)\s*(?:Hz|赫兹|dBFS|dB|半音|秒)", text, re.IGNORECASE
    )
    if source == "model" and (
        any(number not in serialized for number in measured_numbers)
        or re.search(r"(?:准确率|CET.{0,6}成绩)\s*[:：]?\s*\d", text)
    ):
        text, source, notice = fallback, "local", "模型输出含未获实测支持的数值，已改用本地建议。"
    finish()
    begin("coach.save")
    yield "trace", {"trace": trace}
    with database() as db:
        finish()
        db.execute(
            "INSERT INTO coaching VALUES(?,?,?,?,?,?,?,?)",
            (
                str(uuid4()),
                practice_id,
                user,
                time.time(),
                body.question,
                text,
                source,
                json.dumps(trace),
            ),
        )
    yield "trace", {"trace": trace}
    yield (
        "result",
        {
            "source": source,
            "model": body.model if source == "model" else None,
            "answer": text,
            "notice": notice,
        },
    )


@router.get("/practices/{practice_id}/coaching")
def coaching_history(practice_id: str, user: str = Depends(owner)):
    practice(practice_id, user)
    with database() as db:
        rows = db.execute(
            "SELECT question,answer,source,trace,created FROM coaching WHERE practice=? AND owner=? ORDER BY created DESC LIMIT 20",
            (practice_id, user),
        ).fetchall()
    return [{**dict(row), "trace": json.loads(row["trace"])} for row in rows]


@router.post("/practices/{practice_id}/coach-stream")
async def coach_stream(practice_id: str, body: TutorInput, user: str = Depends(owner)):
    row = practice(practice_id, user)
    if row["status"] != "completed":
        raise HTTPException(422, "请先完成录音分析。")

    async def events():
        try:
            async for event, payload in coaching_events(practice_id, body, user):
                yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
        except Exception:
            yield 'event: error\ndata: {"message":"教学建议未完成，请重试。"}\n\n'

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.post("/practices/{practice_id}/resynthesis")
async def resynthesis(practice_id: str, user: str = Depends(owner)):
    row = practice(practice_id, user)
    if row["status"] != "completed":
        raise HTTPException(422, "请先完成录音分析。")
    result = json.loads(row["result"])
    if not result.get("reference") or result.get("quality", {}).get("octave_jumps"):
        raise HTTPException(422, "需要可用参照且无倍频跳变的分析结果。")
    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            upstream = await client.post(
                settings.speaking_service_url.rstrip("/") + "/resynthesize",
                data={"result_json": json.dumps(result, ensure_ascii=False)},
                files={
                    "file": (
                        "recording.audio",
                        (root() / f"{practice_id}.audio").read_bytes(),
                        "application/octet-stream",
                    )
                },
            )
            upstream.raise_for_status()
        return AudioResponse(
            upstream.content, media_type="audio/wav", headers={"Cache-Control": "no-store"}
        )
    except httpx.HTTPError as exc:
        raise HTTPException(503, "语调调整试听生成失败，请稍后再试。") from exc
