"""Vision-LLM extractor: PNG-страницы + filename → ExtractedFacts JSON."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from kmd_checker import settings
from kmd_checker.entities import ExtractedFacts
from kmd_checker.services.llm_client import (
    InvalidJsonError,
    chat_completion,
    png_to_data_url,
)
from kmd_checker.services.pdf_render import RenderedPage

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
Ты — извлекатель фактов из чертежа КМД (металлоконструкции).
Прочитай страницы PDF (vision) и текстовый слой (если есть).
Верни СТРОГИЙ JSON по схеме ExtractedFacts:
{
  "filename": "<имя файла, как пришло>",
  "main_title": {"name": "...", "code": "...", "designation": "..."},
  "secondary_title_blocks": [
    {"name": "...", "code": "...", "designation": "..."}
  ],
  "material": "<строка из штампа, либо null>",
  "material_aisi": "<AISI 304/430/... либо null>",
  "scale": "<1:1 / 1:2 / ... либо null>",
  "sheet_no": "<номер листа либо null>",
  "sheets_total": "<всего листов либо null>",
  "left_right": "l" | "r" | null,
  "specification_rows": [
    {"pos": 1, "name": "...", "code": "...", "qty": 1, "note": null}
  ],
  "tt_text": "<технические требования одной строкой либо null>",
  "notes": ["..."],
  "callouts": ["...","..."],
  "stamps_on_each_sheet": [
    {"sheet": 1, "designation": "...", "code": "..."}
  ],
  "manual_marks_detected": false
}

Правила:
• Если поля нет — null или пустой массив.
• `secondary_title_blocks` — дублирующие штампы и таблица документации.
• `stamps_on_each_sheet` — по одной записи на лист.
• `manual_marks_detected: true`, если видишь рукописные пометки, кляксы, эмодзи,
  стрелки от руки на чертеже.
• Никаких комментариев вне JSON.
"""


@dataclass(slots=True)
class ExtractResult:
    facts: ExtractedFacts
    cost_usd: float


def _build_messages(filename: str, pages: list[RenderedPage]) -> list[dict[str, Any]]:
    user_content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Файл: {filename}\n\n"
                f"Текстовый слой (может быть пуст для сканов):\n"
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


async def extract_facts(
    filename: str,
    pages: list[RenderedPage],
) -> ExtractResult:
    messages = _build_messages(filename, pages)
    resp = await chat_completion(
        model=settings.MODEL_EXTRACTOR,
        messages=messages,
        timeout=settings.TIMEOUT_EXTRACT_SEC,
        response_format_json=True,
    )
    if resp.json_obj is None:
        raise InvalidJsonError("extractor returned empty JSON")
    # filename добавим, если модель его не вернула
    if not resp.json_obj.get("filename"):
        resp.json_obj["filename"] = filename
    try:
        facts = ExtractedFacts.model_validate(resp.json_obj)
    except ValidationError as e:
        logger.warning("extractor JSON failed validation: %s", e)
        # Fallback: вернём минимум, чтобы пайплайн не падал.
        facts = ExtractedFacts(filename=filename)
    return ExtractResult(facts=facts, cost_usd=resp.cost_usd)


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
