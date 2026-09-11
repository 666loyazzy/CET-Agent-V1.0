"""Infer which training mode a user message belongs to.

Phase 1 uses a simple regex/keyword heuristic. Later phases can replace this
with an LLM classification call if needed. The heuristic is intentionally
conservative: when unclear it returns 'intro', which triggers SKILL.md's
"First Interaction Rule" (ask level + section).
"""

from __future__ import annotations

import re
from typing import Literal

Mode = Literal["intro", "writing", "translation", "reading", "listening", "study_plan", "vocab"]


_PATTERNS: list[tuple[Mode, re.Pattern[str]]] = [
    # vocab must precede reading — "阅读一下我错的词" would otherwise hit
    # the reading pattern first. The vocab keywords are all vocab-verb + 词
    # combos, so accidental hits from "作文单词" etc. stay unlikely.
    ("vocab", re.compile(
        r"(背单词|生词|词汇|单词|单词书|抽背|记不住|"
        r"错(?:的|过的|了的)?词|"
        r"忘了?(?:的)?.{0,4}?(?:词|单词)|"
        r"讲.{0,3}?(?:词|list\s*\d+)|"
        r"复习.{0,3}?(?:词)|"
        r"该背|list\s*\d+)",
        re.I,
    )),
    ("writing", re.compile(r"(作文|写作|essay|writing|范文|议论文|模板)", re.I)),
    ("translation", re.compile(r"(翻译|译文|translate|translation|中译英|英译中)", re.I)),
    ("reading", re.compile(
        r"(阅读|选词填空|长篇阅读|信息匹配|仔细阅读|banked cloze|paragraph matching|careful reading|15选10|十五选十)",
        re.I,
    )),
    ("listening", re.compile(r"(听力|听.*(?:对话|篇章|讲座|新闻)|listening)", re.I)),
    ("study_plan", re.compile(
        r"(计划|规划|复习计划|备考|还有\s*\d+\s*(?:天|周|个月)|目标分|冲刺|study plan)",
        re.I,
    )),
]

_ANSWER_PATTERN = re.compile(r"\b\d{2}\s*[A-O]\b", re.I)


def infer_mode(text: str, previous_mode: Mode | None = None) -> Mode:
    """Guess the training mode from a single user message.

    Priority order:
    1. If message looks like an answer submission (e.g. "26A 27F ..."),
       stick with the previous mode.
    2. Match against keyword patterns.
    3. Fall back to previous mode, else 'intro'.
    """
    if not text.strip():
        return previous_mode or "intro"

    if _ANSWER_PATTERN.search(text) and previous_mode:
        return previous_mode

    for mode, pattern in _PATTERNS:
        if pattern.search(text):
            return mode

    return previous_mode or "intro"
