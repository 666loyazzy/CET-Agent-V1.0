# SPDX-License-Identifier: GPL-3.0-or-later
import asyncio
import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from starlette.concurrency import run_in_threadpool

from .catalog import BY_ID, VERSION
from .engine import AudioError, analyze

app = FastAPI(title="English Prosody Analysis", docs_url=None, redoc_url=None)


@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION}


@app.post("/analyze")
async def analysis(
    exercise_id: str = Form(...),
    file: UploadFile = File(...),
    start_s: float | None = Form(None),
    end_s: float | None = Form(None),
    pitch_floor: float = Form(60),
    pitch_ceiling: float = Form(600),
):
    if exercise_id not in BY_ID:
        raise HTTPException(404, "练习不存在。")
    data = await file.read(12 * 1024 * 1024 + 1)
    if not data or len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "音频不能为空，且最多 12 MB。")
    try:
        return await run_in_threadpool(
            analyze, data, BY_ID[exercise_id], start_s, end_s, pitch_floor, pitch_ceiling
        )
    except AudioError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, "声学分析或文本对齐失败，请完整跟读后重试。") from exc


@app.post("/analyze-stream")
async def analysis_stream(
    exercise_id: str = Form(...),
    file: UploadFile = File(...),
    start_s: float | None = Form(None),
    end_s: float | None = Form(None),
    pitch_floor: float = Form(60),
    pitch_ceiling: float = Form(600),
):
    if exercise_id not in BY_ID:
        raise HTTPException(404, "练习不存在。")
    data = await file.read(12 * 1024 * 1024 + 1)
    if not data or len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "音频不能为空，且最多 12 MB。")
    queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def emit(event, payload):
        loop.call_soon_threadsafe(queue.put_nowait, (event, payload))

    def calculate():
        try:
            result = analyze(
                data,
                BY_ID[exercise_id],
                start_s,
                end_s,
                pitch_floor,
                pitch_ceiling,
                on_trace=lambda trace: emit("trace", {"trace": trace}),
            )
            emit("result", result)
        except AudioError as exc:
            emit("error", {"message": str(exc)})
        except Exception:
            emit("error", {"message": "声学分析或对齐失败，请完整跟读后重试。"})
        finally:
            emit("done", {})

    async def events():
        task = asyncio.create_task(run_in_threadpool(calculate))
        try:
            while True:
                try:
                    event, payload = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False, allow_nan=False)}\n\n"
                if event == "done":
                    break
        finally:
            await task

    return StreamingResponse(
        events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
    )


@app.post("/resynthesize")
async def pitch_demo(
    file: UploadFile = File(...), result_json: str = Form(..., max_length=2000000)
):
    from .resynthesis import synthesize

    data = await file.read(12 * 1024 * 1024 + 1)
    if not data or len(data) > 12 * 1024 * 1024:
        raise HTTPException(413, "录音不能为空，且最多 12 MB。")
    try:
        result = json.loads(result_json)
        audio = await run_in_threadpool(synthesize, data, result)
        return Response(audio, media_type="audio/wav")
    except (AudioError, KeyError, ValueError, RuntimeError) as exc:
        raise HTTPException(422, "当前录音或参照不适合进行语调调整试听。") from exc
