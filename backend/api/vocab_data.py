"""Data endpoints for the vocab module (V2 persistence layer).

Companion to `vocab.py` (which owns /judge). Split for readability — this
file talks to SQLite, that file talks to the LLM.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.session import get_session
from backend.vocab import service

router = APIRouter(prefix="/vocab", tags=["vocab-data"])

DEFAULT_USER_ID = service.DEFAULT_USER_ID


class ReviewRequest(BaseModel):
    word_id: int
    remembered: bool
    user_id: int = Field(default=DEFAULT_USER_ID)


class ReviewResponse(BaseModel):
    word_id: int
    total_num: int
    forget_num: int
    rate: float
    history: str
    last_reviewed_at: str | None
    next_due_at: str | None


class ListReviewRequest(BaseModel):
    book: str
    list_no: int
    user_id: int = Field(default=DEFAULT_USER_ID)


class ReviewByEnRequest(BaseModel):
    book: str
    en: str
    remembered: bool
    user_id: int = Field(default=DEFAULT_USER_ID)


class FlagRequest(BaseModel):
    # Either provide word_id, or (book + en). Caller picks the shape that
    # matches its source of truth — HomeView has word_id from the local API,
    # DictationView has book+en from the shuffled wordlist.
    word_id: int | None = None
    book: str | None = None
    en: str | None = None
    flag: int = Field(..., ge=-1, le=2)
    user_id: int = Field(default=DEFAULT_USER_ID)


@router.get("/books")
async def get_books(session: AsyncSession = Depends(get_session)) -> list[dict[str, Any]]:
    return await service.list_book_summaries(session)


@router.get("/lists")
async def get_lists(
    book: str,
    user_id: int = DEFAULT_USER_ID,
    session: AsyncSession = Depends(get_session),
) -> list[dict[str, Any]]:
    rows = await service.list_lists_of_book(session, book, user_id)
    if not rows:
        raise HTTPException(status_code=404, detail=f"book '{book}' not found or empty")
    return rows


@router.get("/list/{book}/{list_no}")
async def get_list(
    book: str,
    list_no: int,
    user_id: int = DEFAULT_USER_ID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    words = await service.list_words_in_list(session, book, list_no, user_id)
    if not words:
        raise HTTPException(status_code=404, detail=f"list {book}/{list_no} not found")
    return {"book": book, "list_no": list_no, "words": words}


@router.get("/word/{book}/{word_en}")
async def get_word(
    book: str,
    word_en: str,
    user_id: int = DEFAULT_USER_ID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    word = await service.find_word(session, book, word_en, user_id)
    if word is None:
        raise HTTPException(status_code=404, detail=f"word '{word_en}' not in {book}")
    return word


@router.post("/review", response_model=ReviewResponse)
async def submit_review(
    req: ReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    review = await service.submit_review(session, req.user_id, req.word_id, req.remembered)
    return ReviewResponse(
        word_id=review.word_id,
        total_num=review.total_num,
        forget_num=review.forget_num,
        rate=review.rate,
        history=review.history,
        last_reviewed_at=review.last_reviewed_at.isoformat() if review.last_reviewed_at else None,
        next_due_at=review.next_due_at.isoformat() if review.next_due_at else None,
    )


@router.get("/stats")
async def get_stats(
    book: str | None = None,
    user_id: int = DEFAULT_USER_ID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await service.compute_stats(session, user_id, book_code=book)


@router.get("/today")
async def get_today(
    book: str,
    user_id: int = DEFAULT_USER_ID,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    return await service.today_due_lists(session, book, user_id)


@router.post("/review/list")
async def submit_list_review(
    req: ListReviewRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    result = await service.finalize_list(session, req.book, req.list_no, req.user_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"book '{req.book}' not found")
    return result


@router.post("/review/flag")
async def set_review_flag(
    req: FlagRequest,
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    """Mark a word: -1=重难词, 0=default, 1=太简单, 2=已掌握.
    flag>=2 excludes the word from list_words_in_list and counts it as
    mastered in stats. Set flag=0 to undo."""
    if req.word_id is not None:
        review = await service.set_review_flag(session, req.user_id, req.word_id, req.flag)
    elif req.book and req.en:
        review = await service.set_review_flag_by_en(
            session, req.user_id, req.book, req.en, req.flag
        )
    else:
        raise HTTPException(status_code=422, detail="need word_id or (book+en)")
    if review is None:
        raise HTTPException(status_code=404, detail="word not found")
    return {"word_id": review.word_id, "flag": review.flag}


@router.post("/review/by-en", response_model=ReviewResponse)
async def submit_review_by_en(
    req: ReviewByEnRequest,
    session: AsyncSession = Depends(get_session),
) -> ReviewResponse:
    """Dictation-friendly variant: caller identifies the word by its
    English spelling instead of DB id. Returns 200 with a null-ish body
    when the word isn't found (dictation may test words outside the seeded
    book), so it doesn't have to special-case 404."""
    review = await service.submit_review_by_en(
        session, req.user_id, req.book, req.en, req.remembered
    )
    if review is None:
        return ReviewResponse(
            word_id=0, total_num=0, forget_num=0, rate=-1.0,
            history="", last_reviewed_at=None, next_due_at=None,
        )
    return ReviewResponse(
        word_id=review.word_id,
        total_num=review.total_num,
        forget_num=review.forget_num,
        rate=review.rate,
        history=review.history,
        last_reviewed_at=review.last_reviewed_at.isoformat() if review.last_reviewed_at else None,
        next_due_at=review.next_due_at.isoformat() if review.next_due_at else None,
    )
