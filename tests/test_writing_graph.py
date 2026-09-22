import pytest
from pydantic import ValidationError

from backend.writing.graph import build_writing_graph
from backend.writing.schemas import EssayInput, score_band


ESSAY = {
    "topic": "Should students use AI to support learning?",
    "essay": (
        "Students can use AI as a learning assistant when they remain responsible for their work. "
        "It can explain difficult ideas and offer practice, but students should verify every answer. "
        "Schools should also teach ethical use so that technology supports rather than replaces thought. "
        "With clear rules, AI can improve access to useful feedback and help students learn independently."
    ),
    "level": "CET-4",
    "model": "deepseek-flash",
}


class FakeRunner:
    def __init__(self, disputed: bool = False):
        self.disputed = disputed

    async def rate(self, essay: dict, role: str, pass_index: int) -> dict:
        score = (7 if role == "strict" else 12) if self.disputed else (10 if role == "strict" else 11)
        return {
            "rater": role,
            "pass_index": pass_index,
            "score": score,
            "band": score_band(score),
            "decision": "Rubric-aligned test decision.",
            "evidence": [{
                "quote": "Students can use AI as a learning assistant",
                "category": "task",
                "polarity": "supports",
                "severity": "minor",
                "explanation": "The essay directly addresses the topic.",
            }],
        }

    async def evidence(self, essay: dict, agent: str, rater_results: list[dict]) -> dict:
        return {
            "agent": agent,
            "findings": [{
                "quote": "students should verify every answer",
                "category": "content",
                "polarity": "supports",
                "severity": "minor",
                "explanation": "A concrete supporting point is present.",
            }],
            "summary": "Evidence checked.",
        }

    async def critic(self, essay: dict, rater_results: list[dict], reports: list[dict]) -> dict:
        return {
            "disagreement_sources": ["Different treatment of language errors."],
            "strict_overreach": [],
            "lenient_overreach": [],
            "missed_evidence": [],
            "recommendation": "Use the holistic anchor band.",
        }

    async def adjudicate(self, essay: dict, rater_results: list[dict], reports: list[dict], critic: dict) -> dict:
        return {
            "score": 10,
            "band": 11,
            "route": "chief_examiner",
            "summary": "Dispute resolved.",
            "strengths": ["Relevant content."],
            "priorities": ["Improve language accuracy."],
            "evidence": [],
        }


@pytest.mark.asyncio
async def test_stable_path_skips_specialists():
    graph = build_writing_graph(FakeRunner())
    result = await graph.ainvoke(
        {"essay": ESSAY}, config={"configurable": {"thread_id": "stable-test"}}
    )
    assert result["final_result"]["route"] == "stable_fusion"
    assert result["final_result"]["model"] == "deepseek-flash"
    assert "critic" not in result


@pytest.mark.asyncio
async def test_disputed_path_adds_passes_and_adjudicates():
    graph = build_writing_graph(FakeRunner(disputed=True))
    result = await graph.ainvoke(
        {"essay": ESSAY}, config={"configurable": {"thread_id": "disputed-test"}}
    )
    assert len(result["strict_results"]) == 5
    assert len(result["lenient_results"]) == 5
    assert result["final_result"]["route"] == "chief_examiner"
    assert result["final_result"]["model"] == "deepseek-flash"


def test_only_supported_writing_models_are_accepted():
    payload = {**ESSAY, "model": "deepseek-v4-pro"}
    assert EssayInput.model_validate(payload).model == "deepseek-v4-pro"
    with pytest.raises(ValidationError):
        EssayInput.model_validate({**payload, "model": "made-up-model"})
