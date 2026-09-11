"""Chat endpoint: streams LLM responses via Server-Sent Events.

Phase 1 is stateless — conversation history lives entirely in the request body.
Phase 2 will persist it to SQLite and inject user profile fragments.
"""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agent.llm_client import get_llm_client
from backend.agent.prompts import build_system_prompt
from backend.agent.router import Mode, infer_mode
from backend.db.session import get_session
from backend.vocab.service import DEFAULT_USER_ID, get_user_context

router = APIRouter()


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    messages: list[Message] = Field(..., min_length=1)
    mode: Mode | None = None
    level: Literal["CET-4", "CET-6"] | None = None


def _sse_pack(event: str, data: dict | str) -> str:
    payload = data if isinstance(data, str) else json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


@router.post("/chat")
async def chat(
    req: ChatRequest,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    last_user_msg = next(
        (m.content for m in reversed(req.messages) if m.role == "user"),
        "",
    )
    mode = req.mode or infer_mode(last_user_msg, previous_mode=None)

    system_prompt = build_system_prompt(mode=mode)
    if req.level:
        system_prompt += f"\n\n<!-- runtime hint -->\nUser has selected level: {req.level}.\n"

    # Vocab Mode gets a fresh snapshot of the user's learning data so the
    # LLM answers with real numbers, not fabricated encouragement.
    if mode == "vocab":
        ctx = await get_user_context(
            session, user_id=DEFAULT_USER_ID, level=req.level or "CET-4"
        )
        system_prompt += (
            "\n\n<runtime-context>\n"
            + json.dumps(ctx, ensure_ascii=False, indent=2)
            + "\n</runtime-context>\n"
        )

    llm = get_llm_client()

    async def event_stream():
        yield _sse_pack("meta", {"mode": mode})
        try:
            async for chunk in llm.stream(
                messages=[m.model_dump() for m in req.messages],
                system=system_prompt,
            ):
                yield _sse_pack("delta", {"text": chunk})
        except Exception as e:
            yield _sse_pack("error", {"message": str(e)})
        yield _sse_pack("done", "")

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/mode-probe")
async def mode_probe(text: str) -> dict:
    """Debug endpoint: show which mode the router infers for a given text."""
    return {"mode": infer_mode(text)}
