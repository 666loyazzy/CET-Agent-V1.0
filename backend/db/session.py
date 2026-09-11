"""Async SQLAlchemy engine + session factory.

The engine's connect hook loads the sqlite-vec extension into every pooled
connection so kNN queries against `vec_embedding_items` work on every session
without per-call setup. Extension loading is per-sqlite3-connection, so this
must fire on every new connection — hence the pool-level event.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

import sqlite_vec
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import settings

log = logging.getLogger("cet-agent.db")

engine = create_async_engine(settings.effective_database_url, echo=False, future=True)


def _unwrap_to_sqlite3(dbapi_conn: object) -> object:
    """Peel SQLAlchemy's async adapter → aiosqlite.Connection → sqlite3.Connection.

    In the aiosqlite dialect the dbapi_conn handed to sync events is the SA
    async adapter (`_connection` → aiosqlite.Connection) which itself wraps
    the raw sqlite3.Connection (`_conn`). Extension loading needs the raw one.
    """
    conn = dbapi_conn
    for attr in ("_connection", "driver_connection", "_conn"):
        inner = getattr(conn, attr, None)
        if inner is not None and inner is not conn:
            conn = inner
    return conn


@event.listens_for(engine.sync_engine, "connect")
def _load_sqlite_vec(dbapi_conn, _record) -> None:
    conn = _unwrap_to_sqlite3(dbapi_conn)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        log.exception("failed to load sqlite-vec extension")
        raise


async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with async_session_factory() as session:
        yield session
