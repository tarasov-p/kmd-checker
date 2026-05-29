"""Персистентный архив проверок.

В отличие от in-memory сессий (живут до TTL и чистятся), архив переживает
рестарт контейнера. По каждой завершённой проверке сохраняем:

- входной файл (тот, что загрузил пользователь);
- ``result.json`` — полный ответ (verdict, findings, reasoning, cost, …),
  тот же JSON, что отдаётся клиенту в ``/api/v1/kmd/check/{id}``;
- строку в общий ``metrics.jsonl`` (append) — компактная сводка по всем
  проверкам, удобно грепать.

Раскладка: ``{ARCHIVE_DIR}/{YYYY-MM-DD}/{session_id}/`` + общий
``{ARCHIVE_DIR}/metrics.jsonl``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

from kmd_checker import settings
from kmd_checker.entities import SessionState

logger = logging.getLogger(__name__)

# Сериализация append'а в metrics.jsonl — чтобы конкурентные пайплайны
# не переплели строки.
_METRICS_LOCK = asyncio.Lock()


def metrics_row(session: SessionState) -> dict:
    """Каноническая сводка по проверке — для stdout-лога и metrics.jsonl."""
    return {
        "event": "kmd_check_done",
        "session_id": session.session_id,
        "ext": session.ext,
        "original_filename": session.original_filename,
        "verdict": session.verdict,
        "findings_count": len(session.findings),
        "cost_usd": round(session.cost_usd, 4),
        "duration_ms": session.duration_ms,
        "total_pages": session.total_pages,
        "error": session.error,
        "ts": datetime.now(UTC).isoformat(),
    }


def _session_dir(session: SessionState) -> Path:
    day = session.started_at.astimezone(UTC).strftime("%Y-%m-%d")
    return settings.ARCHIVE_DIR / day / session.session_id


def _write_session_dir(session: SessionState, input_path: Path) -> None:
    out_dir = _session_dir(session)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Входной файл (как загрузил пользователь). Может уже отсутствовать,
    # если tmp подчистили — тогда пропускаем, ответ всё равно сохраняем.
    if input_path.exists():
        shutil.copy2(input_path, out_dir / input_path.name)

    # Полный ответ. mode="json" сериализует datetime; tmp_dir исключён
    # на уровне модели (Field(exclude=True)) — путь не утечёт.
    result = session.model_dump(mode="json")
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _append_metrics(session: SessionState) -> None:
    settings.ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    line = json.dumps(metrics_row(session), ensure_ascii=False)
    with (settings.ARCHIVE_DIR / "metrics.jsonl").open("a", encoding="utf-8") as f:
        f.write(line + "\n")


async def archive_session(session: SessionState, input_path: Path) -> None:
    """Сохранить проверку в архив. Никогда не роняет пайплайн."""
    if not settings.ARCHIVE_ENABLED:
        return
    try:
        await asyncio.to_thread(_write_session_dir, session, input_path)
        async with _METRICS_LOCK:
            await asyncio.to_thread(_append_metrics, session)
    except Exception:  # noqa: BLE001
        logger.exception(
            "kmd_checker: failed to archive session %s", session.session_id
        )
