"""Seed books + words from frontend/static/words-cet{4,6}.txt.

Idempotent: if a book already has the exact number of rows expected from the
source file, we skip it. Otherwise we wipe the book's words and reload,
which handles both first-run and wordlist-updated cases.

Parser mirrors `vocab-frontend/src/utils/wordlist.ts::parseWordlist` so
short definitions stay in sync between the two code paths. Both fields are kept:
- zh: first-meaning short form (what shows on a card / practice UI)
- zh_full: raw multi-POS string (fed to /judge fast-path 2)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import PROJECT_ROOT
from backend.db.models import Book, User, Word
from backend.db.session import async_session_factory

log = logging.getLogger("cet-agent.seed")

WORDS_PER_LIST = 40

BOOKS: list[tuple[str, str, Path]] = [
    ("cet4", "CET-4 高频词", PROJECT_ROOT / "frontend" / "static" / "words-cet4.txt"),
    ("cet6", "CET-6 高频词", PROJECT_ROOT / "frontend" / "static" / "words-cet6.txt"),
]

_POS_RE = re.compile(r"^(?:n|v|adj|adv|prep|pron|conj|art)\.\s*", re.IGNORECASE)
_CUT_RE = re.compile(
    r"^([^，,；;]+?)(?=\s+(?:n|v|adj|adv|prep|pron|conj|art)\.|[，,；;]|$)",
    re.IGNORECASE,
)


def _first_meaning(raw_zh: str) -> str:
    cleaned = _POS_RE.sub("", raw_zh).strip()
    m = _CUT_RE.match(cleaned)
    return (m.group(1) if m else cleaned).strip()


def parse_wordlist(text: str) -> list[tuple[str, str, str]]:
    """(en, zh_first, zh_full) rows in file order, deduped on `en`.

    The upstream files (KyleBing/english-vocabulary) list the same word
    multiple times across topical groupings — CET-4 has ~3000 such
    duplicates. First occurrence wins so file ordering is preserved for
    the words that remain.
    """
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        if "\t" not in line:
            continue
        en, raw_zh = line.split("\t", 1)
        en = en.strip()
        raw_zh = raw_zh.strip()
        if not en or not raw_zh:
            continue
        key = en.lower()
        if key in seen:
            continue
        seen.add(key)
        zh = _first_meaning(raw_zh)
        if not zh:
            continue
        out.append((en, zh, raw_zh))
    return out


async def _ensure_default_user(session: AsyncSession) -> None:
    existing = await session.scalar(select(User).where(User.id == 1))
    if existing is None:
        session.add(User(id=1, name="default"))
        await session.flush()


async def _seed_book(session: AsyncSession, code: str, name_zh: str, source: Path) -> None:
    if not source.exists():
        log.warning("skip %s: source file missing %s", code, source)
        return
    rows = parse_wordlist(source.read_text(encoding="utf-8"))
    total = len(rows)

    book = await session.scalar(select(Book).where(Book.code == code))
    if book is None:
        book = Book(code=code, name_zh=name_zh, total_words=total)
        session.add(book)
        await session.flush()
    elif book.total_words == total:
        log.info("skip seed %s: %d words already present", code, total)
        return
    else:
        log.info("re-seed %s: db had %d words, source has %d", code, book.total_words, total)
        await session.execute(delete(Word).where(Word.book_id == book.id))
        book.name_zh = name_zh
        book.total_words = total

    payload = [
        {
            "book_id": book.id,
            "list_no": (i // WORDS_PER_LIST) + 1,
            "index_in_list": i % WORDS_PER_LIST,
            "en": en,
            "zh": zh,
            "zh_full": zh_full,
        }
        for i, (en, zh, zh_full) in enumerate(rows)
    ]
    # Bulk insert — 13k rows would be slow via session.add_all().
    for chunk_start in range(0, len(payload), 500):
        await session.execute(insert(Word), payload[chunk_start : chunk_start + 500])
    log.info("seeded %s: %d words -> %d lists", code, total, (total + WORDS_PER_LIST - 1) // WORDS_PER_LIST)


async def seed_if_needed() -> None:
    async with async_session_factory() as session:
        await _ensure_default_user(session)
        for code, name_zh, source in BOOKS:
            await _seed_book(session, code, name_zh, source)
        await session.commit()
