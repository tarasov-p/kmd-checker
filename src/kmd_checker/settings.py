"""Конфиг через env."""

from __future__ import annotations

import os
from pathlib import Path


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# OpenRouter
OPENROUTER_API_KEY: str = _env("OPENROUTER_API_KEY", "")
OPENROUTER_BASE_URL: str = _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_HTTP_REFERER: str = _env("OPENROUTER_HTTP_REFERER", "https://github.com/tarasov-p/kmd-checker")
OPENROUTER_X_TITLE: str = _env("OPENROUTER_X_TITLE", "kmd-checker")

# Модели — зафиксированы в плане
MODEL_EXTRACTOR: str = _env("KMD_MODEL_EXTRACTOR", "google/gemini-3.1-pro-preview")
MODEL_CHEAP: str = _env("KMD_MODEL_CHEAP", "google/gemini-3.1-pro-preview")
MODEL_JUDGE: str = _env("KMD_MODEL_JUDGE", "anthropic/claude-opus-4-7")
MODEL_JUDGE_FALLBACK: str = _env("KMD_MODEL_JUDGE_FALLBACK", "openai/gpt-5.5")
JUDGE_FALLBACK_REASONING: str = _env("KMD_JUDGE_FALLBACK_REASONING", "xhigh")

# Pipeline
RENDER_DPI: int = int(_env("KMD_RENDER_DPI", "220"))
MAX_PAGES: int = int(_env("KMD_MAX_PAGES", "50"))
MAX_UPLOAD_MB: int = int(_env("KMD_MAX_UPLOAD_MB", "100"))
SESSION_TTL_DONE_SEC: int = int(_env("KMD_SESSION_TTL_DONE_SEC", "300"))
SESSION_TTL_TOTAL_SEC: int = int(_env("KMD_SESSION_TTL_TOTAL_SEC", "900"))

# Таймауты LLM
TIMEOUT_CHEAP_SEC: float = float(_env("KMD_TIMEOUT_CHEAP_SEC", "20"))
TIMEOUT_EXTRACT_SEC: float = float(_env("KMD_TIMEOUT_EXTRACT_SEC", "90"))
TIMEOUT_JUDGE_SEC: float = float(_env("KMD_TIMEOUT_JUDGE_SEC", "120"))
TIMEOUT_JUDGE_FALLBACK_SEC: float = float(_env("KMD_TIMEOUT_JUDGE_FALLBACK_SEC", "180"))

# CAD
CAD_CONVERT_TIMEOUT_SEC: float = float(_env("KMD_CAD_CONVERT_TIMEOUT_SEC", "60"))

# Rate limit
RATE_LIMIT_POST: str = _env("KMD_RATE_LIMIT_POST", "10/minute")

# Disk guard
TMP_FREE_BYTES_MIN: int = int(_env("KMD_TMP_FREE_BYTES_MIN", str(1_000_000_000)))  # 1 GB

# Прочее
LOG_LEVEL: str = _env("KMD_LOG_LEVEL", "INFO")

PACKAGE_ROOT = Path(__file__).parent
STATIC_DIR = PACKAGE_ROOT / "static"
