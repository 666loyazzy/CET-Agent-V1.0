from __future__ import annotations

import json
from typing import Protocol, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel

from backend.config import settings
from backend.writing.rubric import CET_HOLISTIC_RUBRIC
from backend.writing.schemas import CriticResult, EvidenceReport, FinalResult, RaterResult

T = TypeVar("T", bound=BaseModel)


class WritingRunner(Protocol):
    async def rate(self, essay: dict, role: str, pass_index: int) -> dict: ...
    async def evidence(self, essay: dict, agent: str, rater_results: list[dict]) -> dict: ...
    async def critic(self, essay: dict, rater_results: list[dict], reports: list[dict]) -> dict: ...
    async def adjudicate(
        self, essay: dict, rater_results: list[dict], reports: list[dict], critic: dict
    ) -> dict: ...


class DeepSeekWritingRunner:
    def __init__(self) -> None:
        api_key = settings.writing_api_key
        self.api_key = api_key
        self.client = AsyncOpenAI(
            api_key=api_key or "missing",
            base_url=settings.writing_base_url,
        )
        self.model = settings.writing_model

    async def _json(self, system: str, payload: dict, schema: type[T]) -> dict:
        if not self.api_key:
            raise ValueError("WRITING_API_KEY is empty. Set it after receiving the DeepSeek key.")
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": system
                    + "\nReturn one JSON object only. Follow this JSON schema:\n"
                    + json.dumps(schema.model_json_schema(), ensure_ascii=False),
                },
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            max_tokens=4096,
            extra_body={"thinking": {"type": "disabled"}},
        )
        content = response.choices[0].message.content or ""
        return schema.model_validate_json(content).model_dump()

    async def rate(self, essay: dict, role: str, pass_index: int) -> dict:
        attention = (
            "Search negative evidence first. Ask why the essay cannot enter the next band. "
            "Do not mechanically lower the score."
            if role == "strict"
            else "Search positive evidence first. Ask what supports retaining the higher band. "
            "Do not mechanically raise the score."
        )
        return await self._json(
            f"You are the {role} evidence rater. {attention}\n{CET_HOLISTIC_RUBRIC}",
            {**essay, "rater": role, "pass_index": pass_index},
            RaterResult,
        )

    async def evidence(self, essay: dict, agent: str, rater_results: list[dict]) -> dict:
        focus = {
            "language": "grammar, vocabulary, sentence-level expression and whether errors block meaning",
            "task_content": "topic relevance, task completion, clarity and missing content",
            "coherence": "sentence and paragraph flow, logic, transitions and organization",
        }[agent]
        return await self._json(
            "You are an evidence specialist. Inspect "
            + focus
            + ". Quote exact essay spans. Do not assign or suggest a total score.",
            {**essay, "agent": agent, "rater_results": rater_results},
            EvidenceReport,
        )

    async def critic(self, essay: dict, rater_results: list[dict], reports: list[dict]) -> dict:
        return await self._json(
            "Explain why the two blind rating paths disagree. Identify over-penalization, "
            "over-leniency, and missed evidence. Do not assign a score.",
            {**essay, "rater_results": rater_results, "evidence_reports": reports},
            CriticResult,
        )

    async def adjudicate(
        self, essay: dict, rater_results: list[dict], reports: list[dict], critic: dict
    ) -> dict:
        return await self._json(
            "You are the neutral CET Chief Examiner. Resolve a disputed case using the official "
            "holistic bands and supplied evidence. You alone may issue the final score.\n"
            + CET_HOLISTIC_RUBRIC,
            {
                **essay,
                "rater_results": rater_results,
                "evidence_reports": reports,
                "critic": critic,
                "route": "chief_examiner",
            },
            FinalResult,
        )
