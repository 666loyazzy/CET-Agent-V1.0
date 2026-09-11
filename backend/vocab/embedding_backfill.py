"""Backfill embeddings for the words in the wordlist.

Idempotent: skips words already vectorized under the current embedding model.
Use --force to re-embed after a text-source change (e.g. tweaking `_word_text`).

Batch size is tuned for DashScope text-embedding-v3 (accepts up to 25 inputs
per request). Commits every batch so a mid-run failure doesn't lose all
progress. The CLI form runs the whole book:

    uv run python -m backend.vocab.embedding_backfill --book cet4
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import Book, EmbeddingItem, Word
from backend.db.session import async_session_factory
from backend.vocab.embedding import embed_texts, upsert_embedding

log = logging.getLogger("cet-agent.embed.backfill")

BATCH_SIZE = 10  # DashScope /v1/embeddings caps inputs per call at 10


def _word_text(en: str, zh_full: str) -> str:
    """Source string per word. Mixing en + full Chinese defs lets a
    cross-lingual model retrieve on either side ("abandon" or "放弃")."""
    return f"{en} {zh_full}".strip()


async def _collect_candidates(
    session: AsyncSession, book_code: str | None
) -> list[tuple[int, str, str, str]]:
    q = select(Word.id, Word.en, Word.zh_full, Book.code).join(
        Book, Word.book_id == Book.id
    )
    if book_code:
        q = q.where(Book.code == book_code)
    q = q.order_by(Word.id)
    rows = (await session.execute(q)).all()
    return [(r.id, r.en, r.zh_full, r.code) for r in rows]


async def _existing_refs(session: AsyncSession) -> set[str]:
    """Fetch entity_refs for words already vectorized under the CURRENT model.
    Rows from a different model don't count as done — re-embed under new one."""
    q = select(EmbeddingItem.entity_ref).where(
        EmbeddingItem.entity_type == "word",
        EmbeddingItem.model == settings.embedding_model,
    )
    return set((await session.execute(q)).scalars().all())


async def backfill_words(
    *,
    book_code: str | None = None,
    force: bool = False,
    limit: int | None = None,
) -> dict[str, Any]:
    stats = {
        "total_candidates": 0,
        "skipped": 0,
        "embedded": 0,
        "failed": 0,
        "model": settings.embedding_model,
        "book": book_code or "all",
    }

    async with async_session_factory() as session:
        candidates = await _collect_candidates(session, book_code)
        stats["total_candidates"] = len(candidates)
        existing = set() if force else await _existing_refs(session)

        pending: list[tuple[int, str, str, str]] = []
        for wid, en, zh_full, book in candidates:
            if str(wid) in existing:
                stats["skipped"] += 1
                continue
            pending.append((wid, en, zh_full, book))
            if limit is not None and len(pending) >= limit:
                break

        log.info(
            "backfill %s: %d candidates, %d pending (%d already embedded)",
            book_code or "all",
            stats["total_candidates"],
            len(pending),
            stats["skipped"],
        )

        for i in range(0, len(pending), BATCH_SIZE):
            batch = pending[i : i + BATCH_SIZE]
            texts = [_word_text(en, zh) for _, en, zh, _ in batch]
            try:
                vectors = await embed_texts(texts)
            except Exception:
                log.exception("embedding batch %d failed", i // BATCH_SIZE)
                stats["failed"] += len(batch)
                continue
            for (wid, en, zh_full, book), vec in zip(batch, vectors, strict=True):
                try:
                    await upsert_embedding(
                        session,
                        entity_type="word",
                        entity_ref=str(wid),
                        text_content=_word_text(en, zh_full),
                        book_code=book,
                        meta={"en": en},
                        embedding=vec,
                    )
                    stats["embedded"] += 1
                except Exception:
                    log.exception("upsert word_id=%d failed", wid)
                    stats["failed"] += 1
            await session.commit()
            log.info(
                "progress: embedded=%d skipped=%d failed=%d",
                stats["embedded"],
                stats["skipped"],
                stats["failed"],
            )

    return stats


def _cli() -> None:
    p = argparse.ArgumentParser(description="Backfill word embeddings.")
    p.add_argument("--book", default=None, help="cet4 / cet6 / omit for all")
    p.add_argument("--force", action="store_true", help="re-embed even if already present")
    p.add_argument("--limit", type=int, default=None, help="cap number of embeddings")
    args = p.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    result = asyncio.run(
        backfill_words(book_code=args.book, force=args.force, limit=args.limit)
    )
    print(result)


if __name__ == "__main__":
    _cli()
