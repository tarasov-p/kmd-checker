"""FastAPI app. Stateless, in-memory sessions, SSE-стрим прогресса."""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

from kmd_checker import settings, sessions
from kmd_checker.entities import Ext, SessionState
from kmd_checker.services.pipeline import make_tmp_dir, run_pipeline

logger = logging.getLogger(__name__)

_UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
_BG_TASKS: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sessions.sweep_orphan_tmp_dirs()
    cleanup_task = asyncio.create_task(sessions.cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass


limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="kmd-checker", lifespan=lifespan)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429, content={"detail": "rate limit exceeded", "retry_after": str(exc)}
    )


if settings.STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=settings.STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    html_path = settings.STATIC_DIR / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>kmd-checker</h1><p>static/index.html missing</p>")
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


@app.get("/ping")
async def ping() -> dict[str, str]:
    return {"status": "ok"}


def _detect_ext(filename: str) -> Ext | None:
    name = filename.lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".dxf"):
        return "dxf"
    # .dwg временно не поддерживается — нужен libredwg (отсутствует в slim-репозиториях)
    return None


def _disk_guard() -> None:
    usage = shutil.disk_usage("/tmp")
    if usage.free < settings.TMP_FREE_BYTES_MIN:
        raise HTTPException(
            status_code=503,
            detail=f"low disk space on /tmp: {usage.free} bytes free",
        )


@app.post("/api/v1/kmd/check")
@limiter.limit(settings.RATE_LIMIT_POST)
async def kmd_check(request: Request, file: UploadFile, force: int = 0) -> dict:
    _disk_guard()
    if not file.filename:
        raise HTTPException(400, "filename required")
    ext = _detect_ext(file.filename)
    if ext is None:
        raise HTTPException(415, "only .pdf and .dxf are supported (DWG не поддерживается)")

    data = await file.read()
    if len(data) == 0:
        raise HTTPException(400, "empty file")
    if len(data) > settings.MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"file too large (limit {settings.MAX_UPLOAD_MB} MB)")

    sid = str(uuid.uuid4())
    tmp = make_tmp_dir(sid)
    session = SessionState(
        session_id=sid,
        ext=ext,
        original_filename=file.filename,
        status="queued",
        started_at=datetime.now(UTC),
        tmp_dir=tmp,
        force=bool(force),
    )
    await sessions.add(session)
    task = asyncio.create_task(run_pipeline(session, data))
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return {"session_id": sid, "ext": ext, "status": session.status}


@app.get("/api/v1/kmd/check/{session_id}")
async def kmd_check_status(session_id: str) -> dict:
    if not _UUID_RE.match(session_id):
        raise HTTPException(400, "invalid session_id")
    session = await sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    return session.model_dump(mode="json")


@app.get("/api/v1/kmd/check/{session_id}/stream")
async def kmd_check_stream(session_id: str, request: Request) -> EventSourceResponse:
    if not _UUID_RE.match(session_id):
        raise HTTPException(400, "invalid session_id")

    async def gen():
        last_status: str | None = None
        while True:
            if await request.is_disconnected():
                # cleanup при разрыве
                s = await sessions.get(session_id)
                if s and s.status not in ("done", "failed", "cancelled"):
                    s.status = "cancelled"
                    await sessions.remove(session_id)
                    shutil.rmtree(s.tmp_dir, ignore_errors=True)
                return
            session = await sessions.get(session_id)
            if session is None:
                yield {"event": "error", "data": '{"detail":"session not found"}'}
                return
            if session.status != last_status:
                yield {"event": "status", "data": session.model_dump_json()}
                last_status = session.status
            if session.status in ("done", "failed", "cancelled"):
                yield {"event": "done", "data": session.model_dump_json()}
                return
            await asyncio.sleep(0.5)

    return EventSourceResponse(gen(), ping=15)


@app.get("/api/v1/kmd/check/{session_id}/pages/{i}.png")
async def kmd_check_page(session_id: str, i: int) -> FileResponse:
    if not _UUID_RE.match(session_id):
        raise HTTPException(400, "invalid session_id")
    if i < 0 or i > 999:
        raise HTTPException(400, "invalid page index")
    session = await sessions.get(session_id)
    if session is None:
        raise HTTPException(404, "session not found")
    if session.total_pages is not None and i >= session.total_pages:
        raise HTTPException(404, "page out of range")
    path: Path = session.tmp_dir / "pages" / f"page_{i:04d}.png"
    if not path.exists():
        raise HTTPException(404, "page not rendered yet")
    return FileResponse(path, media_type="image/png")
