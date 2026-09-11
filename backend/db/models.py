"""SQLAlchemy models for the vocab persistence layer.

Design decisions (see plan `cet-agent-vocab-integration.md`):
- List-level ebbinghaus scheduling on BookList; word-level next_due_at is a
  fallback for heavy words drilled independently.
- history is a compact bitstring "10110" — cheap to store, easy for the
  agent to eyeball, avoids a separate ReviewEvent table for V2.
- Word.embedding was reserved in V2 but is superseded by EmbeddingItem
  (multi-entity vector store keyed on entity_type/entity_ref). The column
  stays for backward compat but new writes go through EmbeddingItem so
  listening/reading errors can share the same vector space.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), default="default")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    name_zh: Mapped[str] = mapped_column(String(64))
    total_words: Mapped[int] = mapped_column(Integer, default=0)

    words: Mapped[list[Word]] = relationship(back_populates="book", cascade="all, delete-orphan")


class Word(Base):
    __tablename__ = "words"
    __table_args__ = (UniqueConstraint("book_id", "en", name="uq_words_book_en"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    list_no: Mapped[int] = mapped_column(Integer, index=True)
    index_in_list: Mapped[int] = mapped_column(Integer)
    en: Mapped[str] = mapped_column(String(80), index=True)
    zh: Mapped[str] = mapped_column(String(200))
    zh_full: Mapped[str] = mapped_column(String(400))
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary, nullable=True)

    book: Mapped[Book] = relationship(back_populates="words")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("user_id", "word_id", name="uq_reviews_user_word"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    word_id: Mapped[int] = mapped_column(ForeignKey("words.id"), index=True)
    total_num: Mapped[int] = mapped_column(Integer, default=0)
    forget_num: Mapped[int] = mapped_column(Integer, default=0)
    rate: Mapped[float] = mapped_column(Float, default=-1.0)
    history: Mapped[str] = mapped_column(String(64), default="")
    flag: Mapped[int] = mapped_column(Integer, default=0)
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class BookList(Base):
    __tablename__ = "book_lists"
    __table_args__ = (
        UniqueConstraint("user_id", "book_id", "list_no", name="uq_book_lists_ubl"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    list_no: Mapped[int] = mapped_column(Integer)
    ebbinghaus_stage: Mapped[int] = mapped_column(Integer, default=0)
    last_review_date: Mapped[Optional[date]] = mapped_column(nullable=True)
    list_rate: Mapped[float] = mapped_column(Float, default=-1.0)


class EmbeddingItem(Base):
    """One row per vectorized artifact, discriminated by (entity_type, entity_ref).

    Vocab is the first `entity_type` ('word', entity_ref = str(word_id)).
    Listening/reading errors plug in later with their own type strings and
    per-type `meta_json` — the search API filters on entity_type so callers
    only see the slice they care about, but all vectors share one virtual
    table so cross-type retrieval works out of the box.

    Companion virtual table `vec_embedding_items` (sqlite-vec) is created in
    the app lifespan and keyed on this table's `id`. Keep them in sync: any
    insert into embedding_items must also insert the vector under the same id.
    """

    __tablename__ = "embedding_items"
    __table_args__ = (
        UniqueConstraint("entity_type", "entity_ref", name="uq_emb_items_type_ref"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(32), index=True)
    entity_ref: Mapped[str] = mapped_column(String(128), index=True)
    text: Mapped[str] = mapped_column(Text)
    book_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True, index=True)
    meta_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(64))
    dim: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
