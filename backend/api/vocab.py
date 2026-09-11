"""Vocab module API — Phase V1.5: AI-powered dictation judgment.

For the dictation UI in /vocab/dictation, some questions (semantic ones like
E→C, or C→E where synonyms exist) need semantic equivalence judgment rather
than strict string comparison. This endpoint runs a targeted LLM call and
returns a strict JSON verdict.

Hint-mode (C→E where the prompt reveals the first N letters) is judged on
the client via string comparison — no need to hit the LLM.

Latency budget: judgment is a classification task, so we short-circuit
exact matches and use a small/fast model (gpt-4o-mini / Claude Haiku)
with non-streaming API + response_format=json_object.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from anthropic import AsyncAnthropic
from fastapi import APIRouter, HTTPException
from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from backend.config import settings

router = APIRouter()

def _judge_provider() -> str:
    """Which provider handles judgment (may differ from main chat)."""
    return settings.judge_provider or settings.llm_provider


def _judge_model_id(provider: str) -> str:
    """Pick the model for judgment calls, given the chosen provider.

    Priority:
    1. Explicit JUDGE_MODEL env override — always wins.
    2. Vendor default only when we can be sure of the catalog:
       - anthropic → Claude Haiku 4.5.
       - openai on openai.com → gpt-4o-mini.
    3. Third-party OpenAI-compatible proxies → fall back to OPENAI_MODEL.
    """
    if settings.judge_model:
        return settings.judge_model
    if provider == "anthropic":
        return "claude-haiku-4-5-20251001"
    if provider == "openai" and "openai.com" in settings.openai_base_url:
        return "gpt-4o-mini"
    return settings.openai_model


Direction = Literal["en_to_zh", "zh_to_en"]


class JudgeRequest(BaseModel):
    direction: Direction
    reference_en: str = Field(..., min_length=1, max_length=80)
    reference_zh: str = Field(..., min_length=1, max_length=120)
    reference_zh_full: str | None = Field(default=None, max_length=400)
    answer: str = Field(..., max_length=200)


class JudgeResponse(BaseModel):
    correct: bool
    reason: str
    correct_answer: str


def _build_prompt(req: JudgeRequest) -> tuple[str, str]:
    """Return (system, user) messages for the judgment call."""
    system = (
        "You are a strict but fair CET-4/CET-6 vocabulary grader. "
        "You judge whether a learner's translation captures the meaning of "
        "the reference word. Accept common synonyms and reasonable variants; "
        "reject unrelated or clearly wrong answers. "
        "Always respond in strict JSON with keys 'correct' (boolean) and "
        "'reason' (Chinese, under 30 characters). No prose outside JSON."
    )
    if req.direction == "en_to_zh":
        user = (
            f"English word: {req.reference_en}\n"
            f"Reference Chinese: {req.reference_zh}\n"
            f"User's Chinese answer: {req.answer.strip() or '(empty)'}\n\n"
            'Judge if the user answer is an acceptable Chinese translation. '
            'Return e.g. {"correct": true, "reason": "同义"}'
        )
    else:
        user = (
            f"Chinese hint: {req.reference_zh}\n"
            f"Reference English word: {req.reference_en}\n"
            f"User's English answer: {req.answer.strip() or '(empty)'}\n\n"
            'Judge if the user answer is an acceptable English word for this '
            'meaning (accept close synonyms, common CET vocabulary, minor '
            'spelling variants like BrE/AmE). Return e.g. '
            '{"correct": true, "reason": "拼写正确"}'
        )
    return system, user


async def _complete(system: str, user: str) -> str:
    """One-shot completion tuned for judgment: small model, no streaming,
    tight max_tokens, JSON mode when available."""
    provider = _judge_provider()
    model = _judge_model_id(provider)
    if provider == "anthropic":
        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        msg = await client.messages.create(
            model=model,
            max_tokens=80,
            temperature=0,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text if msg.content else ""
    # openai / deepseek / openai-compatible.
    # Allow overriding key + base_url so judgment can route through a
    # different fast endpoint (e.g. DeepSeek) while chat keeps its own.
    api_key = settings.judge_openai_api_key or settings.openai_api_key
    base_url = settings.judge_openai_base_url or settings.openai_base_url
    client = AsyncOpenAI(api_key=api_key, base_url=base_url)
    kwargs: dict = {
        "model": model,
        "max_tokens": 200,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    # response_format is safest only on openai.com; some proxies reject it.
    if "openai.com" in base_url:
        kwargs["response_format"] = {"type": "json_object"}
    # DeepSeek V4 Flash defaults reasoning_effort to "high", which burns
    # the token budget on CoT before producing content. Ask for minimal
    # reasoning so we get the JSON verdict directly. Sent via extra_body
    # so the OpenAI SDK doesn't reject the field.
    if "deepseek.com" in base_url:
        kwargs["extra_body"] = {"reasoning_effort": "low"}
    resp = await client.chat.completions.create(**kwargs)
    msg = resp.choices[0].message
    content = getattr(msg, "content", None) or ""
    # DeepSeek V4 Flash and OpenAI o-series may put the answer in a
    # separate reasoning slot when thinking mode fires. Fall back to it.
    if not content.strip():
        content = getattr(msg, "reasoning_content", None) or ""
    return content


_JSON_RE = re.compile(r"\{.*?\}", re.DOTALL)


def _parse_verdict(raw: str) -> tuple[bool, str]:
    """Extract {correct, reason} from LLM output; be lenient about wrappers."""
    text = raw.strip()
    # Strip common markdown fences.
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Try full text first (handles multi-line JSON), then fall back to regex.
    obj = None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_RE.search(text)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict):
        return False, "判分失败"
    correct = bool(obj.get("correct", False))
    reason = str(obj.get("reason", ""))[:60]
    return correct, reason or ("正确" if correct else "不正确")


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


_POS_RE = re.compile(r"(?:^|\s)(?:n|v|adj|adv|prep|pron|conj|art)\.\s*", re.IGNORECASE)
_SPLIT_RE = re.compile(r"[\s，,；;、]+")


def _extract_zh_candidates(zh_full: str) -> set[str]:
    """Break a raw multi-POS Chinese definition into individual terms.

    e.g. "v. 获取 n. 接近，入口" -> {"获取", "接近", "入口"}

    Splits on whitespace too, since POS markers leave a space behind that
    also acts as a boundary between the previous group's terms.
    """
    if not zh_full:
        return set()
    stripped = _POS_RE.sub(" ", zh_full)
    parts = _SPLIT_RE.split(stripped)
    return {_norm(p) for p in parts if p and p.strip()}


@router.post("/vocab/judge", response_model=JudgeResponse)
async def judge(req: JudgeRequest) -> JudgeResponse:
    correct_answer = req.reference_zh if req.direction == "en_to_zh" else req.reference_en
    ans = req.answer.strip()
    if not ans:
        return JudgeResponse(correct=False, reason="未作答", correct_answer=correct_answer)
    ans_norm = _norm(ans)
    # Fast path 1: exact match against the primary reference.
    if ans_norm == _norm(correct_answer):
        return JudgeResponse(correct=True, reason="完全匹配", correct_answer=correct_answer)
    # Fast path 2 (E→C only): match against any candidate parsed from the
    # full definition string. Covers "mood" -> "情绪" when zh_full is
    # "n. 心情，情绪".
    if req.direction == "en_to_zh" and req.reference_zh_full:
        candidates = _extract_zh_candidates(req.reference_zh_full)
        if ans_norm in candidates:
            return JudgeResponse(correct=True, reason="匹配词库释义", correct_answer=correct_answer)
    system, user = _build_prompt(req)
    try:
        raw = await _complete(system, user)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM 调用失败: {e}") from e
    correct, reason = _parse_verdict(raw)
    return JudgeResponse(correct=correct, reason=reason, correct_answer=correct_answer)
