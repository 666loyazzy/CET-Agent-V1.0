"""Load SKILL.md and slice it into mode-specific system prompts.

SKILL.md is the knowledge asset. This module reads it once at import time and
exposes a `build_system_prompt(mode)` that returns a full system prompt built
from a base slice + the mode-specific slice + shared closing rules.

The slicing is heading-based (## and ---). If the SKILL.md structure changes,
only the SLICE_HEADINGS mapping below needs updating.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from backend.config import settings

Mode = Literal["intro", "writing", "translation", "reading", "listening", "study_plan", "vocab"]


# Section headings in SKILL.md that map to each mode.
# Values are the "## Heading" text as it appears in SKILL.md.
SLICE_HEADINGS: dict[str, list[str]] = {
    "always": [
        "Purpose",
        "Non-Negotiable Copyright and Originality Policy",
        "First Interaction Rule",
        "User Profile Collection",
        "Routing Logic",
        "CET-4 vs CET-6 Difficulty Control",
        "Answer Reveal Policy",
        "Quality Checklist Before Responding",
    ],
    "writing": ["Writing Mode"],
    "translation": ["Translation Mode"],
    "reading": ["Reading Mode"],
    "listening": ["Listening Mode"],
    "study_plan": ["Study Plan Mode"],
    "vocab": ["Vocab Mode"],
}


def _read_skill_md() -> str:
    path: Path = settings.skill_md_path
    if not path.exists():
        raise FileNotFoundError(
            f"SKILL.md not found at {path}. Set SKILL_DIR in .env or copy the skill dir."
        )
    return path.read_text(encoding="utf-8")


def _parse_sections(md: str) -> dict[str, str]:
    """Split SKILL.md by top-level `## Heading` sections.

    Returns a dict mapping heading text -> section body (heading included).
    """
    # Strip frontmatter (--- ... ---) at the very top if present.
    fm = re.match(r"^---\n.*?\n---\n", md, re.DOTALL)
    if fm:
        md = md[fm.end():]

    # Split at every top-level "## " that starts a line.
    parts = re.split(r"(?m)^(?=## )", md)
    sections: dict[str, str] = {}
    for part in parts:
        m = re.match(r"## (.+?)\n", part)
        if not m:
            continue
        heading = m.group(1).strip()
        sections[heading] = part.rstrip() + "\n"
    return sections


@lru_cache(maxsize=1)
def _sections() -> dict[str, str]:
    return _parse_sections(_read_skill_md())


def _collect(headings: list[str]) -> str:
    parts: list[str] = []
    sections = _sections()
    for h in headings:
        if h in sections:
            parts.append(sections[h])
        else:
            parts.append(f"<!-- WARNING: heading '{h}' not found in SKILL.md -->\n")
    return "\n".join(parts)


def build_system_prompt(mode: Mode = "intro") -> str:
    """Assemble the system prompt for a given conversation mode.

    'intro' returns just the base slice; use it before a mode is inferred.
    """
    base = _collect(SLICE_HEADINGS["always"])

    if mode == "intro":
        mode_slice = ""
    else:
        mode_slice = _collect(SLICE_HEADINGS[mode])

    header = (
        "# CET-Agent System Prompt\n\n"
        "You are the CET-4/CET-6 preparation assistant defined by the CET Skill "
        "knowledge base below. Follow every rule in it. Respond in Chinese by default.\n\n"
        "---\n"
    )

    return header + base + ("\n" + mode_slice if mode_slice else "")


def list_available_sections() -> list[str]:
    """Debug helper: list every ## heading parsed from SKILL.md."""
    return list(_sections().keys())
