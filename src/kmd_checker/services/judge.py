"""LLM-judge: смотрит PDF целиком и выносит вердикт. Без rules-движка."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from kmd_checker import settings
from kmd_checker.entities import Finding
from kmd_checker.services.llm_client import (
    InvalidJsonError,
    LlmError,
    chat_completion,
    png_to_data_url,
)
from kmd_checker.services.pdf_render import RenderedPage

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
Ты — проверяющий КМД-чертежей (металлоконструкции).
Тебе дают:
  • имя файла (filename);
  • первые страницы чертежа как картинки;
  • при наличии — текстовый слой PDF.

Проверяешь ТОЛЬКО 2 типа ошибок:

1) Путаница в артикулах/обозначениях:
   • filename vs обозначение в основной надписи (штампе);
   • основной штамп vs дублирующие штампы / таблица документации;
   • согласованность кода детали / артикула / ревизии / индекса;
   • материал / исполнение (например AISI 304 vs AISI 430);
   • левое / правое (-l / -r, «левая» / «правая»).

2) Оформление чертежей:
   • заполненность основной надписи (материал, масштаб, общее количество листов);
   • единое обозначение чертежа на всех листах;
   • рукописные правки на чистовике, кляксы, эмодзи в Outlook-стиле;
   • согласованность ТТ с тем, что нарисовано;
   • читаемость, лишние/недостающие линии, скрытые виды;
   • спецификация: класс прочности крепежа при требовании в ТТ.

ЖЁСТКИЕ ПРАВИЛА (не нарушать):
• Прочность, концентраторы напряжений, катет сварного шва «по сути»,
  диапазон радиусов по конструктиву, размеры по расчёту —
  finding с class='manual_review_required', НЕ как error.
• Припис размера сварного шва без упоминания расчёта = оформление
  (class='missing_weld_designation').
• Несоответствие катета и ребра по толщине = manual_review, не error.
• Если PDF не чертёж (письмо, счёт, таблица) —
  verdict='not_a_drawing', findings=[].

Каждый finding должен указывать:
  • class — короткий снейк-кейс код (filename_title_mismatch,
    part_code_mismatch, left_right_mismatch, revision_index_mismatch,
    material_mismatch, missing_title_block_field,
    drawing_designation_mismatch_between_sheets,
    specification_fastener_class_missing, missing_weld_designation,
    manual_review_required, и т.п.);
  • severity — 'high' | 'medium' | 'low';
  • where — где именно (например «основная надпись лист 1»,
    «таблица документации, строка 3», «спецификация поз. 7»);
  • what — что не так;
  • expected — как должно быть (если применимо);
  • actual — как сейчас (если применимо);
  • what_to_fix — короткая подсказка что поправить.

OUTPUT JSON (строго, без комментариев вне JSON):
{
  "verdict": "no_issues" | "errors_found" | "manual_review_required" | "not_a_drawing",
  "findings": [
    {"class": "...", "severity": "high|medium|low",
     "where": "...", "what": "...",
     "expected": "...", "actual": "...", "what_to_fix": "..."}
  ],
  "reasoning": "1-3 предложения"
}
"""


@dataclass(slots=True)
class JudgeResult:
    verdict: str
    findings: list[Finding]
    reasoning: str
    cost_usd: float
    used_fallback: bool


def _build_messages(
    filename: str, pages: list[RenderedPage]
) -> list[dict[str, Any]]:
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Файл: {filename}\n\n"
                f"Текстовый слой PDF (может быть пуст для сканов):\n"
                + "\n---\n".join(p.text_layer or "" for p in pages[:6])
            ),
        }
    ]
    for p in pages[:6]:
        user_content.append(
            {
                "type": "image_url",
                "image_url": {"url": png_to_data_url(p.png_bytes)},
            }
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def _parse_findings(raw: list[dict[str, Any]]) -> list[Finding]:
    out: list[Finding] = []
    for item in raw or []:
        try:
            out.append(
                Finding(
                    class_code=item.get("class") or item.get("class_code") or "unknown",
                    severity=item.get("severity") or "medium",
                    source="llm",
                    confidence="medium",
                    where=item.get("where") or "unknown",
                    what=item.get("what") or "",
                    expected=item.get("expected"),
                    actual=item.get("actual"),
                    what_to_fix=item.get("what_to_fix"),
                    page_index=item.get("page_index"),
                )
            )
        except Exception:
            logger.warning("judge: skipped malformed finding: %r", item)
    return out


async def _call_once(
    model: str,
    messages: list[dict[str, Any]],
    timeout: float,
    reasoning_effort: str | None = None,
) -> JudgeResult:
    resp = await chat_completion(
        model=model,
        messages=messages,
        timeout=timeout,
        response_format_json=True,
        reasoning_effort=reasoning_effort,
    )
    obj = resp.json_obj or {}
    return JudgeResult(
        verdict=obj.get("verdict", "errors_found"),
        findings=_parse_findings(obj.get("findings", [])),
        reasoning=obj.get("reasoning", "") or "",
        cost_usd=resp.cost_usd,
        used_fallback=False,
    )


async def judge_drawing(
    filename: str, pages: list[RenderedPage]
) -> JudgeResult:
    messages = _build_messages(filename, pages)
    try:
        return await _call_once(
            settings.MODEL_JUDGE, messages, settings.TIMEOUT_JUDGE_SEC
        )
    except (InvalidJsonError, LlmError, TimeoutError) as e:
        logger.warning("judge primary failed, fallback: %s", e)
        try:
            r = await _call_once(
                settings.MODEL_JUDGE_FALLBACK,
                messages,
                settings.TIMEOUT_JUDGE_FALLBACK_SEC,
                reasoning_effort=settings.JUDGE_FALLBACK_REASONING,
            )
        except LlmError as e2:
            if "400" in str(e2):
                logger.warning("judge fallback xhigh not accepted, retry with high")
                r = await _call_once(
                    settings.MODEL_JUDGE_FALLBACK,
                    messages,
                    settings.TIMEOUT_JUDGE_FALLBACK_SEC,
                    reasoning_effort="high",
                )
            else:
                raise
        r.used_fallback = True
        return r


async def is_drawing(page: RenderedPage) -> tuple[bool, float]:
    """Пре-чек «это чертёж?» — дёшево, 1 страница, ответ да/нет."""
    messages = [
        {
            "role": "system",
            "content": (
                "Скажи только: похоже на инженерный чертёж (КМД, металлоконструкции, "
                "штамп, размеры, спецификация)? Ответ строгим JSON: "
                '{"is_drawing": true|false, "reason": "<кратко>"}'
            ),
        },
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Это инженерный чертёж?"},
                {
                    "type": "image_url",
                    "image_url": {"url": png_to_data_url(page.png_bytes)},
                },
            ],
        },
    ]
    resp = await chat_completion(
        model=settings.MODEL_CHEAP,
        messages=messages,
        timeout=settings.TIMEOUT_CHEAP_SEC,
        response_format_json=True,
    )
    val = (resp.json_obj or {}).get("is_drawing", True)
    return bool(val), resp.cost_usd
