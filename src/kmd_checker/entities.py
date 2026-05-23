"""Pydantic-сущности — общие для API и пайплайна."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["high", "medium", "low"]
Source = Literal["llm"]
Confidence = Literal["high", "medium", "low"]
Verdict = Literal[
    "no_issues",
    "errors_found",
    "manual_review_required",
    "not_a_drawing",
    "unsupported_format",
]
Status = Literal[
    "queued",
    "converting",
    "rendering",
    "judging",
    "done",
    "failed",
    "cancelled",
]
Ext = Literal["pdf", "dxf"]


class Finding(BaseModel):
    class_code: str
    severity: Severity
    source: Source = "llm"
    confidence: Confidence
    where: str
    what: str
    expected: str | None = None
    actual: str | None = None
    what_to_fix: str | None = None
    page_index: int | None = None


class SessionState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    session_id: str
    ext: Ext
    original_filename: str
    status: Status = "queued"
    verdict: Verdict | None = None
    findings: list[Finding] = []
    reasoning: str | None = None
    total_pages: int | None = None
    cost_usd: float = 0.0
    duration_ms: int | None = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    force: bool = False
    tmp_dir: Path = Field(exclude=True)
