"""Оркестратор. Pre-check «это чертёж?» + LLM-judge. Без rules-движка."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from kmd_checker import settings
from kmd_checker.entities import SessionState
from kmd_checker.services import archive
from kmd_checker.services.cad_to_pdf import CadConvertError, cad_to_pdf
from kmd_checker.services.judge import is_drawing, judge_drawing
from kmd_checker.services.pdf_render import page_count, render_pdf

logger = logging.getLogger(__name__)


def _log_metrics(s: SessionState) -> None:
    logger.info("kmd_metrics %s", json.dumps(archive.metrics_row(s), ensure_ascii=False))


async def run_pipeline(session: SessionState, file_bytes: bytes) -> None:
    try:
        input_path = session.tmp_dir / session.original_filename
        await asyncio.to_thread(input_path.write_bytes, file_bytes)

        # 1. DXF → PDF
        if session.ext == "dxf":
            session.status = "converting"
            try:
                pdf_path = await cad_to_pdf(input_path, session.tmp_dir)
            except CadConvertError as e:
                session.status = "failed"
                session.error = f"cad: {e}"
                return
        else:
            pdf_path = input_path

        pdf_bytes = await asyncio.to_thread(pdf_path.read_bytes)

        try:
            n_pages = await asyncio.to_thread(page_count, pdf_bytes)
        except Exception as e:  # noqa: BLE001
            session.status = "failed"
            session.error = f"pdf: {e}"
            return
        if n_pages > settings.MAX_PAGES:
            session.verdict = "unsupported_format"
            session.total_pages = n_pages
            return

        # 2. Render
        session.status = "rendering"
        rendered = await render_pdf(pdf_bytes, dpi=settings.RENDER_DPI)
        session.total_pages = len(rendered)
        pages_dir = session.tmp_dir / "pages"
        await asyncio.to_thread(pages_dir.mkdir, exist_ok=True)
        for i, r in enumerate(rendered):
            await asyncio.to_thread(
                (pages_dir / f"page_{i:04d}.png").write_bytes, r.png_bytes
            )

        # 3. Pre-check «это чертёж?»
        if not session.force:
            is_drw, cost = await is_drawing(rendered[0])
            session.cost_usd += cost
            if not is_drw:
                session.verdict = "not_a_drawing"
                return

        # 4. Judge — единственный судья, видит PDF целиком
        session.status = "judging"
        judge = await judge_drawing(session.original_filename, rendered)
        session.cost_usd += judge.cost_usd
        session.reasoning = judge.reasoning
        session.findings = judge.findings
        session.verdict = judge.verdict

    except asyncio.CancelledError:
        session.status = "cancelled"
        raise
    except Exception as e:  # noqa: BLE001
        session.status = "failed"
        session.error = (str(e) or e.__class__.__name__)[:500]
        logger.exception("pipeline failed for session %s", session.session_id)
    finally:
        if session.status != "cancelled":
            session.status = "done" if session.verdict else "failed"
            if session.status == "failed" and not session.error:
                session.error = "unknown error"
        session.completed_at = datetime.now(UTC)
        delta = (session.completed_at - session.started_at).total_seconds() * 1000
        session.duration_ms = int(delta)
        _log_metrics(session)
        # Персистентный архив (входной файл + полный ответ + metrics.jsonl).
        # cancelled пропускаем: проверка не завершена, tmp уже подчищен.
        if session.status != "cancelled":
            await archive.archive_session(
                session, session.tmp_dir / session.original_filename
            )


def make_tmp_dir(session_id: str) -> Path:
    base = Path("/tmp") / f"kmd_session_{session_id}"
    base.mkdir(parents=True, exist_ok=True)
    return base
