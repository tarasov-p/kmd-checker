"""In-memory хранилище сессий с TTL-уборкой."""

from __future__ import annotations

import asyncio
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from kmd_checker import settings
from kmd_checker.entities import SessionState

logger = logging.getLogger(__name__)

_SESSIONS: dict[str, SessionState] = {}
_LOCK = asyncio.Lock()


async def add(session: SessionState) -> None:
    async with _LOCK:
        _SESSIONS[session.session_id] = session


async def get(session_id: str) -> SessionState | None:
    async with _LOCK:
        return _SESSIONS.get(session_id)


async def remove(session_id: str) -> SessionState | None:
    async with _LOCK:
        return _SESSIONS.pop(session_id, None)


async def cleanup_expired() -> int:
    now = datetime.now(UTC)
    removed = 0
    async with _LOCK:
        expired_ids: list[str] = []
        for sid, s in _SESSIONS.items():
            if s.status in ("done", "failed", "cancelled") and s.completed_at:
                if (now - s.completed_at).total_seconds() > settings.SESSION_TTL_DONE_SEC:
                    expired_ids.append(sid)
                    continue
            if (now - s.started_at).total_seconds() > settings.SESSION_TTL_TOTAL_SEC:
                expired_ids.append(sid)
        for sid in expired_ids:
            session = _SESSIONS.pop(sid, None)
            if session is not None:
                shutil.rmtree(session.tmp_dir, ignore_errors=True)
                removed += 1
    if removed:
        logger.info("kmd_checker: cleaned up %d expired sessions", removed)
    return removed


async def cleanup_loop() -> None:
    """Запускается из lifespan; крутит уборку раз в минуту."""
    while True:
        try:
            await asyncio.sleep(60)
            await cleanup_expired()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("kmd_checker: cleanup loop error")


def sweep_orphan_tmp_dirs(root: Path = Path("/tmp")) -> int:
    """При старте удаляем осиротевшие /tmp/kmd_session_*."""
    n = 0
    for d in root.glob("kmd_session_*"):
        shutil.rmtree(d, ignore_errors=True)
        n += 1
    if n:
        logger.info("kmd_checker: swept %d orphan tmp dirs", n)
    return n
