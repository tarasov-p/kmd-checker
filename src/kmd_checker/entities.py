"""Pydantic-сущности — общие для API и пайплайна."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Severity = Literal["high", "medium", "low"]
Source = Literal["rules", "llm", "merged"]
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
    "extracting",
    "rules",
    "judging",
    "done",
    "failed",
    "cancelled",
]
Ext = Literal["pdf", "dxf"]


class Finding(BaseModel):
    class_code: str
    severity: Severity
    source: Source
    confidence: Confidence
    where: str
    what: str
    expected: str | None = None
    actual: str | None = None
    what_to_fix: str | None = None
    page_index: int | None = None


class TitleBlock(BaseModel):
    name: str | None = None
    code: str | None = None
    designation: str | None = None


class SpecRow(BaseModel):
    pos: int | None = None
    name: str | None = None
    code: str | None = None
    qty: int | None = None
    note: str | None = None


class StampOnSheet(BaseModel):
    sheet: int
    designation: str | None = None
    code: str | None = None


class ExtractedFacts(BaseModel):
    filename: str | None = None
    main_title: TitleBlock = TitleBlock()
    secondary_title_blocks: list[TitleBlock] = []
    material: str | None = None
    material_aisi: str | None = None
    scale: str | None = None
    sheet_no: str | None = None
    sheets_total: str | None = None
    left_right: Literal["l", "r"] | None = None
    specification_rows: list[SpecRow] = []
    tt_text: str | None = None
    notes: list[str] = []
    callouts: list[str] = []
    stamps_on_each_sheet: list[StampOnSheet] = []
    manual_marks_detected: bool = False


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
