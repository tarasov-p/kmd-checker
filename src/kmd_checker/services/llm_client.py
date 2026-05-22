"""Тонкий клиент OpenRouter. Используется extractor/judge/cheap."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from kmd_checker import settings

logger = logging.getLogger(__name__)


class LlmError(RuntimeError):
    pass


class InvalidJsonError(LlmError):
    pass


@dataclass(slots=True)
class LlmResponse:
    text: str
    json_obj: dict[str, Any] | None
    usage: dict[str, int]
    cost_usd: float
    raw: dict[str, Any]


def png_to_data_url(png_bytes: bytes) -> str:
    b64 = base64.b64encode(png_bytes).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _headers() -> dict[str, str]:
    if not settings.OPENROUTER_API_KEY:
        raise LlmError("OPENROUTER_API_KEY is not set")
    return {
        "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
        "HTTP-Referer": settings.OPENROUTER_HTTP_REFERER,
        "X-Title": settings.OPENROUTER_X_TITLE,
        "Content-Type": "application/json",
    }


async def chat_completion(
    *,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float,
    response_format_json: bool = False,
    reasoning_effort: str | None = None,
    extra_body: dict[str, Any] | None = None,
) -> LlmResponse:
    payload: dict[str, Any] = {"model": model, "messages": messages}
    if response_format_json:
        payload["response_format"] = {"type": "json_object"}
    if reasoning_effort:
        payload["reasoning"] = {"effort": reasoning_effort}
    if extra_body:
        payload.update(extra_body)

    url = settings.OPENROUTER_BASE_URL.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=_headers(), json=payload)
    if resp.status_code >= 400:
        raise LlmError(f"OpenRouter HTTP {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    try:
        choice = data["choices"][0]["message"]
        text = choice.get("content") or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LlmError(f"unexpected OpenRouter response shape: {e}") from e

    json_obj: dict[str, Any] | None = None
    if response_format_json:
        try:
            json_obj = json.loads(text) if isinstance(text, str) else text
        except json.JSONDecodeError as e:
            raise InvalidJsonError(f"invalid JSON from model: {e}") from e

    usage = data.get("usage") or {}
    cost = float(data.get("usage", {}).get("cost") or 0.0)
    return LlmResponse(text=text, json_obj=json_obj, usage=usage, cost_usd=cost, raw=data)
