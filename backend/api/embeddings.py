"""Vector search + backfill HTTP endpoints.

Two shapes of search:
- `GET /api/vocab/similar` — vocab-scoped convenience: "words similar to X in
  book Y". Reuses the source word's stored vector when present (skip an
  embedding API call).
- `POST /api/embeddings/search` — generic kNN over the whole embedding space.
  This is the endpoint listening/reading integrations will call later; the
  `entity_types` filter is what keeps them isolated when they want to be.

Backfill endpoint is a thin wrapper around the CLI so browser-side triggers
work during dev. Full-book backfills are still better run via the CLI to
avoid HTTP timeout risk.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Book, EmbeddingItem, Word
from backend.db.session import get_session
from backend.vocab import embedding
from backend.vocab.embedding_backfill import backfill_words

router = APIRouter(tags=["embeddings"])


class SearchRequest(BaseModel):
    query_text: str | None = None
    query_vector: list[float] | None = None
    entity_types: list[str] | None = None
    book_code: str | None = None
    limit: int = Field(10, ge=1, le=50)


class SearchHit(BaseModel):
    id: int
    distance: float
    entity_type: str
    entity_ref: str
    text: str
    book_code: str | None = None
    model: str
    meta: dict[str, Any] | None = None


@router.post("/embeddings/search", response_model=list[SearchHit])
async def search(
    req: SearchRequest,
    session: AsyncSession = Depends(get_session),
) -> list[SearchHit]:
    if not req.query_text and not req.query_vector:
        raise HTTPException(status_code=422, detail="need query_text or query_vector")
    try:
        hits = await embedding.search_similar(
            session,
            query_text=req.query_text,
            query_vector=req.query_vector,
            entity_types=req.entity_types,
            book_code=req.book_code,
            limit=req.limit,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return [SearchHit(**h) for h in hits]


@router.get("/vocab/similar")
async def vocab_similar(
    en: str = Query(..., min_length=1, max_length=80),
    book: str = Query(..., min_length=1),
    limit: int = Query(10, ge=1, le=30),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Return words semantically similar to `en` within `book`.

    Preferred path: read the source word's cached vector from vec_embedding_items
    and reuse it (0 API calls). Fallback: embed `en + zh_full` fresh — happens
    when backfill hasn't reached this word yet.
    """
    book_row = await session.scalar(select(Book).where(Book.code == book))
    if book_row is None:
        raise HTTPException(status_code=404, detail=f"book '{book}' not found")
    word = await session.scalar(
        select(Word).where(Word.book_id == book_row.id, Word.en == en)
    )
    if word is None:
        raise HTTPException(status_code=404, detail=f"word '{en}' not in {book}")

    src_item = await session.scalar(
        select(EmbeddingItem).where(
            EmbeddingItem.entity_type == "word",
            EmbeddingItem.entity_ref == str(word.id),
        )
    )
    if src_item is not None:
        vec = await embedding.fetch_vector(session, src_item.id, src_item.dim)
        if vec is not None:
            hits = await embedding.search_similar(
                session,
                query_vector=vec,
                entity_types=["word"],
                book_code=book,
                limit=limit,
                exclude_ref=("word", str(word.id)),
            )
            return {
                "source": {"en": en, "book": book, "word_id": word.id, "cached": True},
                "hits": hits,
            }
    # No cached vector — embed on the fly. Won't persist here; that's the
    # backfill job's responsibility.
    query_text = f"{en} {word.zh_full}".strip()
    hits = await embedding.search_similar(
        session,
        query_text=query_text,
        entity_types=["word"],
        book_code=book,
        limit=limit,
        exclude_ref=("word", str(word.id)),
    )
    return {
        "source": {"en": en, "book": book, "word_id": word.id, "cached": False},
        "hits": hits,
    }


class BackfillRequest(BaseModel):
    book: str | None = None
    force: bool = False
    limit: int | None = Field(default=None, ge=1, le=10000)


@router.post("/embeddings/backfill/words")
async def backfill_endpoint(req: BackfillRequest) -> dict[str, Any]:
    """Kick off (and wait for) a word-embedding backfill.

    Blocks on the request thread — fine for `limit`-bounded runs or small
    books; for full-book runs prefer the CLI to avoid client timeouts:
        uv run python -m backend.vocab.embedding_backfill --book cet4
    """
    return await backfill_words(book_code=req.book, force=req.force, limit=req.limit)
