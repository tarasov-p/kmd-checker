"""Оркестратор. Запускается в asyncio.create_task для каждой сессии."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from kmd_checker import settings
from kmd_checker.entities import Finding, SessionState
from kmd_checker.services.cad_to_pdf import CadConvertError, cad_to_pdf
from kmd_checker.services.extractor import extract_facts, is_drawing
from kmd_checker.services.judge import judge_drawing
from kmd_checker.services.pdf_render import page_count, render_pdf
from kmd_checker.services.rules_engine import run_rules

logger = logging.getLogger(__name__)


def _merge(rule_findings: list[Finding], llm_findings: list[Finding]) -> list[Finding]:
    out: list[Finding] = []
    seen: set[tuple[str, str]] = set()
    for f in rule_findings + llm_findings:
        key = (f.class_code, f.where)
        if key in seen:
            # повышаем уверенность того, что в out, до 'high' если оба источника видели
            for existing in out:
                if (existing.class_code, existing.where) == key:
                    existing.source = "merged"
                    existing.confidence = "high"
                    break
            continue
        seen.add(key)
        out.append(f)
    return out


def _compute_verdict(findings: list[Finding]) -> str:
    if not findings:
        return "no_issues"
    if any(f.class_code == "manual_review_required" for f in findings):
        return "manual_review_required"
    if any(f.severity in ("high", "medium") for f in findings):
        return "errors_found"
    return "no_issues"


def _log_metrics(s: SessionState) -> None:
    row = {
        "event": "kmd_check_done",
        "session_id": s.session_id,
        "ext": s.ext,
        "verdict": s.verdict,
        "findings_count": len(s.findings),
        "cost_usd": round(s.cost_usd, 4),
        "duration_ms": s.duration_ms,
        "total_pages": s.total_pages,
        "error": s.error,
        "ts": datetime.now(UTC).isoformat(),
    }
    logger.info("kmd_metrics %s", json.dumps(row, ensure_ascii=False))


async def run_pipeline(session: SessionState, file_bytes: bytes) -> None:
    try:
        input_path = session.tmp_dir / session.original_filename
        await asyncio.to_thread(input_path.write_bytes, file_bytes)

        # 1. DWG/DXF → PDF
        if session.ext in ("dwg", "dxf"):
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

        # Лимит страниц до полного рендера
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

        # 3. Pre-check
        if not session.force:
            is_drw, cost = await is_drawing(rendered[0])
            session.cost_usd += cost
            if not is_drw:
                session.verdict = "not_a_drawing"
                return

        # 4. Extract
        session.status = "extracting"
        extract = await extract_facts(session.original_filename, rendered)
        session.cost_usd += extract.cost_usd

        # 5. Rules
        session.status = "rules"
        rule_findings = run_rules(extract.facts)

        # 6. Judge
        session.status = "judging"
        judge = await judge_drawing(extract.facts, rule_findings, rendered)
        session.cost_usd += judge.cost_usd
        session.reasoning = judge.reasoning

        # 7. Merge + verdict
        session.findings = _merge(rule_findings, judge.findings)
        # Если judge явно сказал «не чертёж» — берём его вердикт.
        if judge.verdict == "not_a_drawing":
            session.verdict = "not_a_drawing"
            session.findings = []
        else:
            session.verdict = _compute_verdict(session.findings)
            if judge.verdict == "manual_review_required":
                session.verdict = "manual_review_required"

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


def make_tmp_dir(session_id: str) -> Path:
    base = Path("/tmp") / f"kmd_session_{session_id}"
    base.mkdir(parents=True, exist_ok=True)
    return base
