from __future__ import annotations

import json
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from backend.writing import build_writing_graph
from backend.writing.schemas import EssayInput

router = APIRouter(prefix="/writing", tags=["writing"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/review-stream")
async def review_stream(request: EssayInput) -> StreamingResponse:
    run_id = str(uuid4())

    async def events():
        yield _sse("run", {"run_id": run_id})
        try:
            graph = build_writing_graph()
            config = {"configurable": {"thread_id": run_id}}
            async for update in graph.astream(
                {"essay": request.model_dump()}, config=config, stream_mode="updates"
            ):
                for node, payload in update.items():
                    yield _sse("node", {"node": node, "data": payload})
            yield _sse("done", {"run_id": run_id})
        except Exception as exc:
            yield _sse("error", {"run_id": run_id, "message": str(exc)})

    return StreamingResponse(events(), media_type="text/event-stream")
