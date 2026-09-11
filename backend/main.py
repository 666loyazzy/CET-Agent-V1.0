"""FastAPI entrypoint for cet-agent."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from backend.api.chat import router as chat_router
from backend.api.embeddings import router as embeddings_router
from backend.api.vocab import router as vocab_router
from backend.api.vocab_data import router as vocab_data_router
from backend.config import PROJECT_ROOT, settings
from backend.db import Base, engine
from backend.db.seed import seed_if_needed

log = logging.getLogger("cet-agent.startup")


async def _ensure_vec_virtual_table() -> None:
    """Create the sqlite-vec kNN table keyed on embedding_items.id.

    Dim is baked into the virtual table at creation; if the configured
    embedding_dim later changes, insertion errors will surface — that's a
    signal to drop and re-backfill, which we don't automate to avoid
    silent data loss.
    """
    dim = settings.embedding_dim
    ddl = text(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_embedding_items "
        f"USING vec0(id INTEGER PRIMARY KEY, embedding FLOAT[{dim}])"
    )
    async with engine.begin() as conn:
        await conn.execute(ddl)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_vec_virtual_table()
    await seed_if_needed()
    log.info("db ready at %s (vec dim=%d)", settings.effective_database_url, settings.embedding_dim)
    yield


app = FastAPI(title="CET Agent", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def no_cache_static(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static") or path.startswith("/vocab") or path == "/":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


app.include_router(chat_router, prefix="/api")
app.include_router(vocab_router, prefix="/api")
app.include_router(vocab_data_router, prefix="/api")
app.include_router(embeddings_router, prefix="/api")


FRONTEND_DIR: Path = PROJECT_ROOT / "frontend"


@app.get("/")
async def index() -> RedirectResponse:
    # Chat lives inside the Vue SPA at /vocab/#/. Canonical URLs are all
    # /vocab/#/* so hash-only nav between tabs stays instant.
    return RedirectResponse(url="/vocab/#/", status_code=302)


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/healthz")
async def healthz() -> dict:
    return {
        "status": "ok",
        "llm_provider": settings.llm_provider,
        "skill_md": str(settings.skill_md_path),
        "skill_md_exists": settings.skill_md_path.exists(),
    }


app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")

VOCAB_DIST = FRONTEND_DIR / "vocab"
if VOCAB_DIST.exists():
    app.mount("/vocab", StaticFiles(directory=VOCAB_DIST, html=True), name="vocab")


def run() -> None:
    """Convenience runner: `python -m backend.main` or `uv run python -m backend.main`."""
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        reload_dirs=[
            str(PROJECT_ROOT / "backend"),
            str(PROJECT_ROOT / "frontend" / "static"),
            str(PROJECT_ROOT / "skill"),
        ],
    )


if __name__ == "__main__":
    run()
