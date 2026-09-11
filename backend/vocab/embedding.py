"""Vector embedding service — provider-agnostic OpenAI-compatible client
plus dual-table upsert (embedding_items metadata + sqlite-vec vector store).

Design:
- One flat table `embedding_items` discriminated on (entity_type, entity_ref).
  Vocab is the first type; listening/reading errors plug in later using their
  own type strings and per-type `meta_json`. All types share one vector space
  so cross-type retrieval (e.g. "listening errors similar to these weak words")
  works without a schema change.
- Vectors are L2-normalized on write so sqlite-vec's default L2 distance is
  equivalent to cosine — no need to call `vec_distance_cosine()` explicitly,
  and normalized vectors compress better in float32.
- Dim mismatch (config change vs. virtual-table baked dim) surfaces on insert
  as an error; we don't auto-drop the vec table to avoid silent data loss.
"""

from __future__ import annotations

import json
import math
import struct
from typing import Any, Sequence

from openai import AsyncOpenAI
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.db.models import EmbeddingItem


def _pack(vec: Sequence[float]) -> bytes:
    """float32 LE — sqlite-vec's on-disk format for FLOAT[N] columns."""
    return struct.pack(f"{len(vec)}f", *vec)


def _unpack(blob: bytes, dim: int) -> list[float]:
    return list(struct.unpack(f"{dim}f", blob))


async def fetch_vector(session: AsyncSession, item_id: int, dim: int) -> list[float] | None:
    """Read a stored vector back out — used to reuse existing embeddings as
    query vectors without a fresh API call."""
    row = (
        await session.execute(
            text("SELECT embedding FROM vec_embedding_items WHERE id = :id"),
            {"id": item_id},
        )
    ).first()
    if row is None:
        return None
    return _unpack(row[0], dim)


def _l2_normalize(vec: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return list(vec)
    return [x / norm for x in vec]


def _client() -> AsyncOpenAI:
    api_key = settings.embedding_api_key or settings.openai_api_key
    return AsyncOpenAI(api_key=api_key, base_url=settings.embedding_base_url)


async def embed_texts(texts: Sequence[str]) -> list[list[float]]:
    """Batch embed → L2-normalized vectors. Empty input returns []."""
    if not texts:
        return []
    client = _client()
    resp = await client.embeddings.create(
        model=settings.embedding_model,
        input=list(texts),
    )
    return [_l2_normalize(d.embedding) for d in resp.data]


async def upsert_embedding(
    session: AsyncSession,
    *,
    entity_type: str,
    entity_ref: str,
    text_content: str,
    book_code: str | None = None,
    meta: dict[str, Any] | None = None,
    embedding: Sequence[float] | None = None,
) -> EmbeddingItem:
    """Idempotent write: create or update the metadata row + vector row
    under one id. Caller controls the transaction (no commit here)."""
    if embedding is None:
        [embedding] = await embed_texts([text_content])
    dim = len(embedding)
    if dim != settings.embedding_dim:
        raise ValueError(
            f"embedding dim {dim} != configured {settings.embedding_dim}; "
            f"either fix EMBEDDING_DIM or drop vec_embedding_items and rebackfill"
        )

    meta_json = json.dumps(meta, ensure_ascii=False) if meta else None

    existing = await session.scalar(
        select(EmbeddingItem).where(
            EmbeddingItem.entity_type == entity_type,
            EmbeddingItem.entity_ref == entity_ref,
        )
    )
    if existing is None:
        item = EmbeddingItem(
            entity_type=entity_type,
            entity_ref=entity_ref,
            text=text_content,
            book_code=book_code,
            meta_json=meta_json,
            model=settings.embedding_model,
            dim=dim,
        )
        session.add(item)
        await session.flush()  # populate item.id
    else:
        existing.text = text_content
        existing.book_code = book_code
        existing.meta_json = meta_json
        existing.model = settings.embedding_model
        existing.dim = dim
        item = existing
        await session.flush()

    packed = _pack(embedding)
    # vec0 doesn't support ON CONFLICT UPDATE; DELETE-then-INSERT keeps the
    # two writes trivially atomic within the caller's transaction.
    await session.execute(
        text("DELETE FROM vec_embedding_items WHERE id = :id"),
        {"id": item.id},
    )
    await session.execute(
        text("INSERT INTO vec_embedding_items(id, embedding) VALUES (:id, :emb)"),
        {"id": item.id, "emb": packed},
    )
    return item


async def search_similar(
    session: AsyncSession,
    *,
    query_text: str | None = None,
    query_vector: Sequence[float] | None = None,
    entity_types: Sequence[str] | None = None,
    book_code: str | None = None,
    limit: int = 10,
    exclude_ref: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """kNN retrieval over the shared vector space, joined back to metadata.

    Filters on entity_type/book_code/exclude_ref happen in Python after
    overfetching from vec0 — sqlite-vec's MATCH doesn't compose well with
    predicate pushdown, and the overfetch factor is small so this is fine
    at the current data scale (<100k items).
    """
    if query_vector is None:
        if not query_text:
            raise ValueError("need query_text or query_vector")
        [query_vector] = await embed_texts([query_text])
    if len(query_vector) != settings.embedding_dim:
        raise ValueError(
            f"query vector dim {len(query_vector)} != configured {settings.embedding_dim}"
        )
    packed = _pack(query_vector)
    overfetch = max(limit * 4, 40)
    # sqlite-vec 0.1.x requires an explicit `k = ?` hidden-column constraint
    # on kNN queries — a bare LIMIT isn't enough. See sqlite-vec docs.
    rows = (
        await session.execute(
            text(
                """
                SELECT v.id, v.distance,
                       e.entity_type, e.entity_ref, e.text,
                       e.book_code, e.meta_json, e.model
                FROM vec_embedding_items v
                JOIN embedding_items e ON e.id = v.id
                WHERE v.embedding MATCH :emb AND k = :k
                ORDER BY v.distance
                """
            ),
            {"emb": packed, "k": overfetch},
        )
    ).mappings().all()

    out: list[dict[str, Any]] = []
    types_set = set(entity_types) if entity_types else None
    for row in rows:
        if types_set and row["entity_type"] not in types_set:
            continue
        if book_code and row["book_code"] != book_code:
            continue
        if exclude_ref and (row["entity_type"], row["entity_ref"]) == exclude_ref:
            continue
        meta_json = row["meta_json"]
        try:
            meta = json.loads(meta_json) if meta_json else None
        except json.JSONDecodeError:
            meta = None
        out.append(
            {
                "id": row["id"],
                "distance": float(row["distance"]),
                "entity_type": row["entity_type"],
                "entity_ref": row["entity_ref"],
                "text": row["text"],
                "book_code": row["book_code"],
                "model": row["model"],
                "meta": meta,
            }
        )
        if len(out) >= limit:
            break
    return out
