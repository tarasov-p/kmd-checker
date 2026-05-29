"""Функциональный тест персистентного архива.

Прогоняем archive_session на реальной файловой системе (tmp_path) и проверяем,
что на диске оказались: входной файл, result.json с полным ответом и строка
в metrics.jsonl. Без моков — настоящие файлы, точные сравнения.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from kmd_checker import settings
from kmd_checker.entities import Finding, SessionState
from kmd_checker.services import archive


def _make_session(tmp_dir: Path) -> SessionState:
    started = datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC)
    return SessionState(
        session_id="11111111-2222-3333-4444-555555555555",
        ext="pdf",
        original_filename="чертёж.pdf",
        status="done",
        verdict="errors_found",
        findings=[
            Finding(
                class_code="article_mismatch",
                severity="high",
                confidence="high",
                where="штамп",
                what="артикул не совпадает с именем файла",
            )
        ],
        reasoning="нашёл расхождение",
        total_pages=1,
        cost_usd=0.0573,
        duration_ms=26553,
        started_at=started,
        completed_at=datetime(2026, 5, 29, 12, 0, 26, tzinfo=UTC),
        tmp_dir=tmp_dir,
    )


def test_archive_writes_file_result_and_metrics(tmp_path: Path) -> None:
    archive_dir = tmp_path / "archive"
    tmp_dir = tmp_path / "kmd_session"
    tmp_dir.mkdir()
    input_path = tmp_dir / "чертёж.pdf"
    input_path.write_bytes(b"%PDF-1.7 fake")

    session = _make_session(tmp_dir)

    original_dir = settings.ARCHIVE_DIR
    original_enabled = settings.ARCHIVE_ENABLED
    settings.ARCHIVE_DIR = archive_dir
    settings.ARCHIVE_ENABLED = True
    try:
        asyncio.run(archive.archive_session(session, input_path))
    finally:
        settings.ARCHIVE_DIR = original_dir
        settings.ARCHIVE_ENABLED = original_enabled

    session_dir = archive_dir / "2026-05-29" / session.session_id

    # 1. Входной файл скопирован байт-в-байт.
    assert (session_dir / "чертёж.pdf").read_bytes() == b"%PDF-1.7 fake"

    # 2. result.json — полный ответ, без утечки tmp_dir.
    result = json.loads((session_dir / "result.json").read_text(encoding="utf-8"))
    assert result["verdict"] == "errors_found"
    assert result["original_filename"] == "чертёж.pdf"
    assert len(result["findings"]) == 1
    assert result["findings"][0]["class_code"] == "article_mismatch"
    assert "tmp_dir" not in result

    # 3. metrics.jsonl — одна строка-сводка.
    lines = (archive_dir / "metrics.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["event"] == "kmd_check_done"
    assert row["session_id"] == session.session_id
    assert row["original_filename"] == "чертёж.pdf"
    assert row["findings_count"] == 1


def test_archive_disabled_writes_nothing(tmp_path: Path) -> None:
    archive_dir = tmp_path / "archive"
    tmp_dir = tmp_path / "kmd_session"
    tmp_dir.mkdir()
    input_path = tmp_dir / "чертёж.pdf"
    input_path.write_bytes(b"%PDF-1.7 fake")

    session = _make_session(tmp_dir)

    original_dir = settings.ARCHIVE_DIR
    original_enabled = settings.ARCHIVE_ENABLED
    settings.ARCHIVE_DIR = archive_dir
    settings.ARCHIVE_ENABLED = False
    try:
        asyncio.run(archive.archive_session(session, input_path))
    finally:
        settings.ARCHIVE_DIR = original_dir
        settings.ARCHIVE_ENABLED = original_enabled

    assert not archive_dir.exists()
