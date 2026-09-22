from __future__ import annotations

import asyncio
import math
import re
from typing import NotRequired, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from backend.writing.llm import DeepSeekWritingRunner, WritingRunner
from backend.writing.reliability import assess_reliability
from backend.writing.rubric import CET_HOLISTIC_RUBRIC
from backend.writing.schemas import FinalResult, score_band


class WritingState(TypedDict):
    essay: dict
    precheck: NotRequired[dict]
    calibration: NotRequired[dict]
    strict_results: NotRequired[list[dict]]
    lenient_results: NotRequired[list[dict]]
    reliability: NotRequired[dict]
    language_evidence: NotRequired[dict]
    task_content_evidence: NotRequired[dict]
    coherence_evidence: NotRequired[dict]
    critic: NotRequired[dict]
    final_result: NotRequired[dict]


def _precheck(state: WritingState) -> dict:
    essay = state["essay"]
    word_count = len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", essay["essay"]))
    expected = (120, 180) if essay["level"] == "CET-4" else (150, 220)
    issues: list[str] = []
    if word_count < 20:
        issues.append("Essay is too short for reliable scoring.")
    if word_count > 1000:
        issues.append("Essay exceeds the review service limit.")
    warnings = [] if expected[0] <= word_count <= expected[1] else [
        f"Expected about {expected[0]}-{expected[1]} words for {essay['level']}."
    ]
    return {
        "precheck": {
            "eligible": not issues,
            "word_count": word_count,
            "issues": issues,
            "warnings": warnings,
        }
    }


def _precheck_route(state: WritingState) -> str:
    return "calibrate" if state["precheck"]["eligible"] else "invalid"


def _calibrate(state: WritingState) -> dict:
    return {
        "calibration": {
            "rubric": CET_HOLISTIC_RUBRIC,
            "anchors": [],
            "severity_profile": None,
            "note": "Official band descriptors active; anchors await user-provided gold data.",
        }
    }


def _validate_quotes(result: dict, essay_text: str) -> dict:
    valid = []
    for item in result.get("evidence", []):
        if item.get("quote", "").strip() in essay_text:
            valid.append(item)
    if not valid:
        raise ValueError("Rater returned no evidence quoted from the essay.")
    result["evidence"] = valid
    return result


def build_writing_graph(runner: WritingRunner | None = None):
    runner = runner or DeepSeekWritingRunner()

    async def strict(state: WritingState) -> dict:
        results = await asyncio.gather(
            *(runner.rate(state["essay"], "strict", index) for index in range(1, 4))
        )
        return {"strict_results": [_validate_quotes(item, state["essay"]["essay"]) for item in results]}

    async def lenient(state: WritingState) -> dict:
        results = await asyncio.gather(
            *(runner.rate(state["essay"], "lenient", index) for index in range(1, 4))
        )
        return {"lenient_results": [_validate_quotes(item, state["essay"]["essay"]) for item in results]}

    def reliability(state: WritingState) -> dict:
        return {
            "reliability": assess_reliability(
                state["strict_results"], state["lenient_results"]
            )
        }

    def reliability_route(state: WritingState) -> str:
        if state["reliability"]["stable"]:
            return "fuse"
        if len(state["strict_results"]) < 5:
            return "additional"
        return "review"

    async def additional(state: WritingState) -> dict:
        strict_extra, lenient_extra = await asyncio.gather(
            asyncio.gather(*(runner.rate(state["essay"], "strict", i) for i in (4, 5))),
            asyncio.gather(*(runner.rate(state["essay"], "lenient", i) for i in (4, 5))),
        )
        text = state["essay"]["essay"]
        return {
            "strict_results": state["strict_results"]
            + [_validate_quotes(item, text) for item in strict_extra],
            "lenient_results": state["lenient_results"]
            + [_validate_quotes(item, text) for item in lenient_extra],
        }

    def fuse(state: WritingState) -> dict:
        report = state["reliability"]
        score = math.floor(
            (report["strict"]["median"] + report["lenient"]["median"]) / 2 + 0.5
        )
        evidence = []
        for result in (state["strict_results"][-1], state["lenient_results"][-1]):
            evidence.extend(result["evidence"][:3])
        final = FinalResult(
            score=score,
            band=score_band(score),
            route="stable_fusion",
            summary="Blind rating paths agreed within the reliability thresholds.",
            strengths=[item["explanation"] for item in evidence if item["polarity"] == "supports"][:3],
            priorities=[item["explanation"] for item in evidence if item["polarity"] == "limits"][:3],
            evidence=evidence,
        )
        return {"final_result": final.model_dump()}

    def invalid(state: WritingState) -> dict:
        final = FinalResult(
            score=1,
            band=2,
            route="invalid",
            summary=" ".join(state["precheck"]["issues"]),
        )
        return {"final_result": final.model_dump()}

    async def evidence_node(state: WritingState, agent: str, key: str) -> dict:
        results = state["strict_results"] + state["lenient_results"]
        report = await runner.evidence(state["essay"], agent, results)
        findings = [
            item for item in report.get("findings", [])
            if item.get("quote", "").strip() in state["essay"]["essay"]
        ]
        report["findings"] = findings
        return {key: report}

    async def language(state: WritingState) -> dict:
        return await evidence_node(state, "language", "language_evidence")

    async def task_content(state: WritingState) -> dict:
        return await evidence_node(state, "task_content", "task_content_evidence")

    async def coherence(state: WritingState) -> dict:
        return await evidence_node(state, "coherence", "coherence_evidence")

    async def critic(state: WritingState) -> dict:
        reports = [
            state["language_evidence"],
            state["task_content_evidence"],
            state["coherence_evidence"],
        ]
        result = await runner.critic(
            state["essay"], state["strict_results"] + state["lenient_results"], reports
        )
        return {"critic": result}

    async def adjudicate(state: WritingState) -> dict:
        reports = [
            state["language_evidence"],
            state["task_content_evidence"],
            state["coherence_evidence"],
        ]
        final = await runner.adjudicate(
            state["essay"],
            state["strict_results"] + state["lenient_results"],
            reports,
            state["critic"],
        )
        return {"final_result": final}

    graph = StateGraph(WritingState)
    graph.add_node("precheck", _precheck)
    graph.add_node("calibrate", _calibrate)
    graph.add_node("strict_rater", strict)
    graph.add_node("lenient_rater", lenient)
    graph.add_node("reliability_gate", reliability)
    graph.add_node("additional_scoring", additional)
    graph.add_node("fuse", fuse)
    graph.add_node("invalid", invalid)
    graph.add_node("dispatch_review", lambda state: {})
    graph.add_node("language_evidence", language)
    graph.add_node("task_content_evidence", task_content)
    graph.add_node("coherence_evidence", coherence)
    graph.add_node("critic", critic)
    graph.add_node("chief_examiner", adjudicate)

    graph.add_edge(START, "precheck")
    graph.add_conditional_edges(
        "precheck", _precheck_route, {"calibrate": "calibrate", "invalid": "invalid"}
    )
    graph.add_edge("invalid", END)
    graph.add_edge("calibrate", "strict_rater")
    graph.add_edge("calibrate", "lenient_rater")
    graph.add_edge(["strict_rater", "lenient_rater"], "reliability_gate")
    graph.add_conditional_edges(
        "reliability_gate",
        reliability_route,
        {"fuse": "fuse", "additional": "additional_scoring", "review": "dispatch_review"},
    )
    graph.add_edge("additional_scoring", "reliability_gate")
    graph.add_edge("fuse", END)

    # Review branches start together; critic waits for all three.
    graph.add_edge("dispatch_review", "language_evidence")
    graph.add_edge("dispatch_review", "task_content_evidence")
    graph.add_edge("dispatch_review", "coherence_evidence")
    graph.add_edge(
        ["language_evidence", "task_content_evidence", "coherence_evidence"], "critic"
    )
    graph.add_edge("critic", "chief_examiner")
    graph.add_edge("chief_examiner", END)
    return graph.compile(checkpointer=InMemorySaver())
