"""LLM-judge: financial verdict + findings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from kmd_checker import settings
from kmd_checker.entities import ExtractedFacts, Finding
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
Проверяешь ТОЛЬКО 2 типа ошибок:
  1) путаница в артикулах/обозначениях
     (filename, штамп, дублирующие штампы, спецификация, материал/исполнение,
      левое/правое);
  2) оформление чертежей
     (заполнение основной надписи, нумерация листов, единое обозначение на всех листах,
      наличие масштаба/материала, рукописные правки на чистовике, согласованность ТТ).

ЖЁСТКИЕ ПРАВИЛА:
• Любое суждение о прочности, концентраторах напряжений, катете сварного шва
  «по сути», диапазоне радиусов по конструктиву, размерах по расчёту →
  finding class='manual_review_required'.
• Припис размера сварного шва БЕЗ упоминания расчёта = оформление
  (missing_weld_designation).
• Несоответствие катета и ребра по толщине = manual_review, не error.
• Если PDF не чертёж — verdict='not_a_drawing', findings=[].

OUTPUT JSON (строго):
{
  "verdict": "no_issues" | "errors_found" | "manual_review_required" | "not_a_drawing",
  "findings": [
    {"class": "...", "severity": "high|medium|low",
     "where": "...", "what": "...",
     "expected": "...", "actual": "...",
     "what_to_fix": "..."}
  ],
  "reasoning": "<1-3 предложения>"
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
    facts: ExtractedFacts,
    rule_findings: list[Finding],
    pages: list[RenderedPage],
) -> list[dict[str, Any]]:
    facts_json = facts.model_dump_json(indent=2)
    rules_json = "[\n" + ",\n".join(f.model_dump_json() for f in rule_findings) + "\n]"
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                "Извлечённые факты:\n```json\n" + facts_json + "\n```\n\n"
                "Findings от rule-engine:\n```json\n" + rules_json + "\n```\n\n"
                "Дай финальный JSON-вердикт по схеме."
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
    facts: ExtractedFacts,
    rule_findings: list[Finding],
    pages: list[RenderedPage],
) -> JudgeResult:
    messages = _build_messages(facts, rule_findings, pages)
    try:
        return await _call_once(
            settings.MODEL_JUDGE, messages, settings.TIMEOUT_JUDGE_SEC
        )
    except (InvalidJsonError, LlmError, TimeoutError) as e:
        logger.warning("judge primary failed, fallback: %s", e)
        # try with xhigh; graceful degrade на high при HTTP 400
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
