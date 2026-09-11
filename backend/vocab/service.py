"""Review submission + stats aggregation.

`history` stays capped at 40 bits (last-40 window), which is plenty for
the agent to eyeball recent trend without unbounded growth. V3 adds
list-level ebbinghaus finalization; word-level `next_due_at` remains
unfilled in V3 (reserved for a future "heavy words" drill loop).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import Book, BookList, Review, Word
from backend.vocab import ebbinghaus

DEFAULT_USER_ID = 1
HISTORY_WINDOW = 40
RECENT_BITS = 2  # match WordReview.recent_list_rate window


async def _find_book_by_code(session: AsyncSession, code: str) -> Book | None:
    return await session.scalar(select(Book).where(Book.code == code))


async def submit_review_by_en(
    session: AsyncSession, user_id: int, book_code: str, en: str, remembered: bool
) -> Review | None:
    """Look up the word by (book_code, en) then delegate to submit_review.
    Returns None if the word isn't in the given book — the caller decides
    how to surface that (dictation likely just ignores and moves on)."""
    book = await _find_book_by_code(session, book_code)
    if book is None:
        return None
    word = await session.scalar(
        select(Word).where(Word.book_id == book.id, Word.en == en)
    )
    if word is None:
        return None
    return await submit_review(session, user_id, word.id, remembered)


async def submit_review(
    session: AsyncSession, user_id: int, word_id: int, remembered: bool
) -> Review:
    review = await session.scalar(
        select(Review).where(Review.user_id == user_id, Review.word_id == word_id)
    )
    if review is None:
        review = Review(user_id=user_id, word_id=word_id)
        session.add(review)
        await session.flush()  # apply column defaults so numeric fields aren't None
    review.total_num += 1
    if not remembered:
        review.forget_num += 1
    bit = "1" if remembered else "0"
    review.history = (review.history + bit)[-HISTORY_WINDOW:]
    review.rate = review.forget_num / review.total_num if review.total_num > 0 else -1.0
    review.last_reviewed_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(review)
    return review


async def list_book_summaries(session: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Book.id, Book.code, Book.name_zh, Book.total_words).order_by(Book.id)
        )
    ).all()
    return [
        {"id": r.id, "code": r.code, "name_zh": r.name_zh, "total_words": r.total_words}
        for r in rows
    ]


async def list_lists_of_book(
    session: AsyncSession, book_code: str, user_id: int
) -> list[dict[str, Any]]:
    """One row per list_no, with lifetime aggregate + `recent_forget_rate`.

    `avg_forget_rate` is lifetime; `recent_forget_rate` counts 0s in the
    last RECENT_BITS chars of each word's history — better signal for
    "does the user still remember it right now".
    """
    book = await _find_book_by_code(session, book_code)
    if book is None:
        return []
    review_sub = (
        select(Review.word_id, Review.rate, Review.total_num)
        .where(Review.user_id == user_id)
        .subquery()
    )
    agg_stmt = (
        select(
            Word.list_no,
            func.count(Word.id).label("size"),
            func.count(review_sub.c.word_id).label("reviewed"),
            func.avg(review_sub.c.rate).label("avg_forget_rate"),
        )
        .select_from(Word)
        .join(review_sub, review_sub.c.word_id == Word.id, isouter=True)
        .where(Word.book_id == book.id)
        .group_by(Word.list_no)
        .order_by(Word.list_no)
    )
    agg_rows = (await session.execute(agg_stmt)).all()

    hist_stmt = (
        select(Word.list_no, Review.history)
        .join(Review, Review.word_id == Word.id)
        .where(Word.book_id == book.id, Review.user_id == user_id)
    )
    recent_by_list: dict[int, tuple[int, int]] = {}
    for list_no, history in (await session.execute(hist_stmt)).all():
        tail = (history or "")[-RECENT_BITS:]
        if not tail:
            continue
        zeros, total = recent_by_list.get(list_no, (0, 0))
        recent_by_list[list_no] = (zeros + tail.count("0"), total + len(tail))

    booklist_stmt = select(BookList).where(
        BookList.book_id == book.id, BookList.user_id == user_id
    )
    booklist_by_no = {
        bl.list_no: bl for bl in (await session.execute(booklist_stmt)).scalars()
    }

    today = ebbinghaus.study_date()
    out: list[dict[str, Any]] = []
    for r in agg_rows:
        zeros, total_bits = recent_by_list.get(r.list_no, (0, 0))
        recent_rate = zeros / total_bits if total_bits else None
        bl = booklist_by_no.get(r.list_no)
        stage = bl.ebbinghaus_stage if bl else 0
        last_review = bl.last_review_date if bl else None
        out.append(
            {
                "list_no": r.list_no,
                "size": r.size,
                "reviewed": r.reviewed,
                "avg_forget_rate": float(r.avg_forget_rate) if r.avg_forget_rate is not None else None,
                "recent_forget_rate": recent_rate,
                "ebbinghaus_stage": stage,
                "last_review_date": last_review.isoformat() if last_review else None,
                "days_until_due": ebbinghaus.days_until_due(stage, last_review, today),
                # "Due" is only true for previously-reviewed lists whose
                # ebbinghaus cooldown has elapsed. Never-touched lists are
                # surfaced through /today's "new" quota — putting a
                # review-due outline on every fresh list is misleading.
                "due": last_review is not None
                and ebbinghaus.stage_is_due(stage, last_review, today),
            }
        )
    return out


async def finalize_list(
    session: AsyncSession, book_code: str, list_no: int, user_id: int
) -> dict[str, Any] | None:
    """Called when the user finishes cycling through a list. Advances the
    BookList row's ebbinghaus stage based on this pass's performance."""
    book = await _find_book_by_code(session, book_code)
    if book is None:
        return None
    hist_stmt = (
        select(Review.history)
        .join(Word, Word.id == Review.word_id)
        .where(
            Word.book_id == book.id,
            Word.list_no == list_no,
            Review.user_id == user_id,
        )
    )
    histories = [h for (h,) in (await session.execute(hist_stmt)).all()]
    remembered, session_rate = ebbinghaus.list_remembered_from_histories(histories)

    bl = await session.scalar(
        select(BookList).where(
            BookList.user_id == user_id,
            BookList.book_id == book.id,
            BookList.list_no == list_no,
        )
    )
    if bl is None:
        bl = BookList(
            user_id=user_id,
            book_id=book.id,
            list_no=list_no,
            ebbinghaus_stage=0,
            list_rate=-1.0,
        )
        session.add(bl)
        await session.flush()

    new_stage = ebbinghaus.next_stage_after(bl.ebbinghaus_stage, remembered)
    today = ebbinghaus.study_date()
    bl.ebbinghaus_stage = new_stage
    bl.last_review_date = today
    bl.list_rate = session_rate
    next_due = today + timedelta(days=ebbinghaus.STAGES[new_stage])
    await session.commit()
    await session.refresh(bl)
    return {
        "book": book.code,
        "list_no": list_no,
        "session_rate": session_rate,
        "remembered": remembered,
        "ebbinghaus_stage": new_stage,
        "last_review_date": bl.last_review_date.isoformat() if bl.last_review_date else None,
        "next_due_date": next_due.isoformat(),
        "days_until_due": ebbinghaus.STAGES[new_stage],
    }


async def today_due_lists(
    session: AsyncSession, book_code: str, user_id: int, new_list_quota: int = 1
) -> dict[str, Any]:
    """Today's review queue.

    Two categories:
    - `hit_reason="review"`: lists with a BookList row whose ebbinghaus
      schedule fires today (today >= last_review + STAGES[stage]).
    - `hit_reason="new"`: up to `new_list_quota` lists the user has never
      touched, in list_no order. Prevents "fresh user opens app and sees
      114 lists demanded" and matches how WordReview's homepage.pug feeds
      new lists in.
    """
    book = await _find_book_by_code(session, book_code)
    today = ebbinghaus.study_date()
    if book is None:
        return {"book": book_code, "date": today.isoformat(), "lists": [], "heavy_words": []}
    booklist_stmt = select(BookList).where(
        BookList.book_id == book.id, BookList.user_id == user_id
    )
    booklist_by_no = {
        bl.list_no: bl for bl in (await session.execute(booklist_stmt)).scalars()
    }
    max_list = await session.scalar(
        select(func.max(Word.list_no)).where(Word.book_id == book.id)
    ) or 0

    due: list[dict[str, Any]] = []
    new_taken = 0
    for list_no in range(1, max_list + 1):
        bl = booklist_by_no.get(list_no)
        if bl is None:
            if new_taken < new_list_quota:
                due.append(
                    {
                        "list_no": list_no,
                        "ebbinghaus_stage": 0,
                        "last_review_date": None,
                        "hit_reason": "new",
                    }
                )
                new_taken += 1
            continue
        if ebbinghaus.stage_is_due(bl.ebbinghaus_stage, bl.last_review_date, today):
            due.append(
                {
                    "list_no": list_no,
                    "ebbinghaus_stage": bl.ebbinghaus_stage,
                    "last_review_date": bl.last_review_date.isoformat()
                    if bl.last_review_date
                    else None,
                    "hit_reason": f"review-stage-{bl.ebbinghaus_stage}",
                }
            )
    return {
        "book": book.code,
        "date": today.isoformat(),
        "lists": due,
        "heavy_words": [],  # V4 will populate from Review.flag == -1 / high forget rate
    }


async def list_words_in_list(
    session: AsyncSession, book_code: str, list_no: int, user_id: int
) -> list[dict[str, Any]]:
    """Excludes words the user manually marked as mastered (flag >= 2).
    Never-reviewed words (no Review row) are always included."""
    book = await _find_book_by_code(session, book_code)
    if book is None:
        return []
    stmt = (
        select(Word, Review)
        .join(
            Review,
            (Review.word_id == Word.id) & (Review.user_id == user_id),
            isouter=True,
        )
        .where(
            Word.book_id == book.id,
            Word.list_no == list_no,
            or_(Review.id.is_(None), Review.flag < 2),
        )
        .order_by(Word.index_in_list)
    )
    out: list[dict[str, Any]] = []
    for word, review in (await session.execute(stmt)).all():
        out.append(
            {
                "id": word.id,
                "en": word.en,
                "zh": word.zh,
                "zh_full": word.zh_full,
                "list_no": word.list_no,
                "index_in_list": word.index_in_list,
                "review": _review_dict(review) if review else None,
            }
        )
    return out


async def find_word(
    session: AsyncSession, book_code: str, word_en: str, user_id: int
) -> dict[str, Any] | None:
    book = await _find_book_by_code(session, book_code)
    if book is None:
        return None
    stmt = (
        select(Word, Review)
        .join(
            Review,
            (Review.word_id == Word.id) & (Review.user_id == user_id),
            isouter=True,
        )
        .where(Word.book_id == book.id, Word.en == word_en)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    word, review = row
    return {
        "id": word.id,
        "en": word.en,
        "zh": word.zh,
        "zh_full": word.zh_full,
        "list_no": word.list_no,
        "index_in_list": word.index_in_list,
        "book_code": book.code,
        "review": _review_dict(review) if review else None,
    }


async def set_review_flag(
    session: AsyncSession,
    user_id: int,
    word_id: int,
    flag: int,
) -> Review | None:
    """Sets Review.flag directly. Creates a Review row if the user hasn't
    reviewed this word yet — so "mark as mastered" works even for a word
    the user recognizes on sight and never bothered to drill."""
    review = await session.scalar(
        select(Review).where(Review.user_id == user_id, Review.word_id == word_id)
    )
    if review is None:
        review = Review(user_id=user_id, word_id=word_id, flag=flag)
        session.add(review)
        await session.flush()
    else:
        review.flag = flag
    await session.commit()
    await session.refresh(review)
    return review


async def set_review_flag_by_en(
    session: AsyncSession,
    user_id: int,
    book_code: str,
    en: str,
    flag: int,
) -> Review | None:
    book = await _find_book_by_code(session, book_code)
    if book is None:
        return None
    word = await session.scalar(
        select(Word).where(Word.book_id == book.id, Word.en == en)
    )
    if word is None:
        return None
    return await set_review_flag(session, user_id, word.id, flag)


async def recent_error_words(
    session: AsyncSession,
    user_id: int,
    book_code: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Words the user has been failing on. Ranked by rate * forget_num so
    both frequent-forgetters and high-rate ones bubble up. `flag == 2`
    (mastered) is excluded so the agent doesn't circle back to a word the
    user declared done."""
    book = await _find_book_by_code(session, book_code)
    if book is None:
        return []
    stmt = (
        select(
            Word.en,
            Word.zh,
            Word.list_no,
            Review.total_num,
            Review.forget_num,
            Review.rate,
            Review.history,
        )
        .join(Review, Review.word_id == Word.id)
        .where(
            Word.book_id == book.id,
            Review.user_id == user_id,
            Review.total_num >= 2,
            Review.rate > 0,
            Review.flag < 2,
        )
        .order_by((Review.rate * Review.forget_num).desc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "en": r.en,
            "zh": r.zh,
            "list_no": r.list_no,
            "total_num": r.total_num,
            "forget_num": r.forget_num,
            "rate": float(r.rate),
            "history": r.history,
        }
        for r in rows
    ]


async def get_user_context(
    session: AsyncSession, user_id: int, level: str = "CET-4"
) -> dict[str, Any]:
    """Snapshot of the user's vocab state for the agent to consume as
    runtime context. Agent-facing, not user-facing — the keys and types
    here become part of the SKILL.md contract."""
    book_code = "cet6" if level == "CET-6" else "cet4"
    stats = await compute_stats(session, user_id, book_code)
    today = await today_due_lists(session, book_code, user_id, new_list_quota=3)
    lists = await list_lists_of_book(session, book_code, user_id)
    weak = sorted(
        [l for l in lists if l["recent_forget_rate"] is not None and l["reviewed"] > 0],
        key=lambda l: -(l["recent_forget_rate"] or 0),
    )[:5]
    weak = [
        {
            "list_no": l["list_no"],
            "recent_forget_rate": l["recent_forget_rate"],
            "avg_forget_rate": l["avg_forget_rate"],
            "ebbinghaus_stage": l["ebbinghaus_stage"],
            "last_review_date": l["last_review_date"],
        }
        for l in weak
    ]
    errors = await recent_error_words(session, user_id, book_code, limit=20)
    return {
        "level": level,
        "book_code": book_code,
        "date": ebbinghaus.study_date().isoformat(),
        "mastery": {
            k: stats[k] for k in ("total_words", "reviewed", "mastered", "avg_forget_rate")
        },
        "today_due_lists": today["lists"],
        "weak_lists": weak,
        "recent_error_words": errors,
    }


async def compute_stats(
    session: AsyncSession, user_id: int, book_code: str | None = None
) -> dict[str, Any]:
    """When `book_code` is provided, all counts are filtered to that book's
    words (via JOIN through Review.word_id → Word.book_id). Without a book,
    stats aggregate across all books."""
    book_id: int | None = None
    if book_code:
        book = await _find_book_by_code(session, book_code)
        if book is None:
            return {
                "book": book_code,
                "total_words": 0,
                "reviewed": 0,
                "mastered": 0,
                "avg_forget_rate": None,
            }
        book_id = book.id

    total_words_stmt = select(func.count(Word.id))
    if book_id is not None:
        total_words_stmt = total_words_stmt.where(Word.book_id == book_id)
    total_words = await session.scalar(total_words_stmt) or 0

    reviewed_stmt = select(func.count(Review.id)).where(Review.user_id == user_id)
    mastered_stmt = select(func.count(Review.id)).where(
        Review.user_id == user_id,
        or_(
            (Review.total_num >= 2) & (Review.rate.between(0, 0.2)),
            Review.flag >= 2,
        ),
    )
    avg_stmt = select(func.avg(Review.rate)).where(
        Review.user_id == user_id,
        Review.rate >= 0,
    )
    if book_id is not None:
        reviewed_stmt = reviewed_stmt.join(Word, Word.id == Review.word_id).where(
            Word.book_id == book_id
        )
        mastered_stmt = mastered_stmt.join(Word, Word.id == Review.word_id).where(
            Word.book_id == book_id
        )
        avg_stmt = avg_stmt.join(Word, Word.id == Review.word_id).where(
            Word.book_id == book_id
        )

    reviewed_count = await session.scalar(reviewed_stmt) or 0
    mastered_count = await session.scalar(mastered_stmt) or 0
    avg_forget_rate = await session.scalar(avg_stmt)
    return {
        "book": book_code,
        "total_words": total_words,
        "reviewed": reviewed_count,
        "mastered": mastered_count,
        "avg_forget_rate": float(avg_forget_rate) if avg_forget_rate is not None else None,
    }


def _review_dict(review: Review) -> dict[str, Any]:
    return {
        "total_num": review.total_num,
        "forget_num": review.forget_num,
        "rate": review.rate,
        "history": review.history,
        "flag": review.flag,
        "last_reviewed_at": review.last_reviewed_at.isoformat() if review.last_reviewed_at else None,
        "next_due_at": review.next_due_at.isoformat() if review.next_due_at else None,
    }
