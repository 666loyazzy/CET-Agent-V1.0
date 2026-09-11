"""Output-format validators for generated CET-style tasks.

Phase 1 provides skeletons and helpers; only the writing/translation validators
are wired up in the API layer. Reading validators (banked cloze / paragraph
matching / careful reading) are stubbed for Phase 3.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    ok: bool
    issues: list[str] = field(default_factory=list)

    def add(self, msg: str) -> None:
        self.ok = False
        self.issues.append(msg)


def word_count_en(text: str) -> int:
    """Rough English word count (splits on whitespace, strips markdown)."""
    stripped = re.sub(r"[#*`>_\[\]()|-]", " ", text)
    return len([w for w in stripped.split() if w])


def has_practice_label(text: str) -> bool:
    return "原创" in text and "CET-style" in text


def validate_writing_task(text: str, level: str) -> ValidationResult:
    """Check that a writing task response includes label + topic options."""
    result = ValidationResult(ok=True)
    if not has_practice_label(text):
        result.add("缺少原创 CET-style 标注")
    if not re.search(r"(?:^|\n)\s*1[\.、]", text):
        result.add("未列出编号 1. 的选题")
    return result


def validate_translation_task(text: str) -> ValidationResult:
    result = ValidationResult(ok=True)
    if not has_practice_label(text):
        result.add("缺少原创 CET-style 标注")
    if not re.search(r"[一-鿿]", text):
        result.add("翻译任务应包含中文段落")
    return result


# ---- Reading validators (Phase 3 stubs) ------------------------------------


def validate_banked_cloze(text: str, level: str) -> ValidationResult:
    """Verify 26-35 blanks, 15 A-O options, passage length."""
    result = ValidationResult(ok=True)
    blanks = re.findall(r"\b(2[6-9]|3[0-5])\b", text)
    if len(set(blanks)) < 10:
        result.add(f"选词填空应有 26-35 共 10 空，找到 {len(set(blanks))}")
    option_letters = set(re.findall(r"(?:^|\n)\s*([A-O])[\.\)、]\s*[A-Za-z]", text))
    if len(option_letters) < 15:
        result.add(f"选词填空应有 A-O 共 15 个选项，找到 {len(option_letters)}")
    return result


def validate_paragraph_matching(text: str, level: str) -> ValidationResult:
    """Verify [A]-[O] paragraphs, 36-45 statements."""
    result = ValidationResult(ok=True)
    paragraphs = set(re.findall(r"\[([A-O])\]", text))
    if len(paragraphs) < 15:
        result.add(f"长篇阅读需要 [A]-[O] 共 15 段，找到 {len(paragraphs)}")
    statements = re.findall(r"\b(3[6-9]|4[0-5])\b", text)
    if len(set(statements)) < 10:
        result.add(f"长篇阅读应有 36-45 共 10 个 statements，找到 {len(set(statements))}")
    return result


def validate_careful_reading(text: str, level: str) -> ValidationResult:
    """Verify two passages, 46-50 and 51-55 questions, A-D options."""
    result = ValidationResult(ok=True)
    p1 = re.findall(r"\b(4[6-9]|50)\b", text)
    p2 = re.findall(r"\b(5[1-5])\b", text)
    if len(set(p1)) < 5:
        result.add(f"仔细阅读第一篇应有 46-50 共 5 题，找到 {len(set(p1))}")
    if len(set(p2)) < 5:
        result.add(f"仔细阅读第二篇应有 51-55 共 5 题，找到 {len(set(p2))}")
    return result
