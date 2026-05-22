"""Rules engine: 7 синхронных правил + 1 experimental."""

from __future__ import annotations

import re

from kmd_checker.entities import ExtractedFacts, Finding
from kmd_checker.services.article_parser import compare, strip_filename_markers


def _f(class_code: str, severity: str, where: str, what: str, **kw) -> Finding:
    return Finding(
        class_code=class_code,
        severity=severity,  # type: ignore[arg-type]
        source="rules",
        confidence="high",
        where=where,
        what=what,
        **kw,
    )


def filename_title_mismatch(facts: ExtractedFacts) -> list[Finding]:
    fname = strip_filename_markers(facts.filename or "")
    code = facts.main_title.code or ""
    if not fname or not code:
        return []
    cmp = compare(fname, code)
    if cmp.is_match:
        return []
    return [
        _f(
            "filename_title_mismatch",
            "high",
            "имя файла vs основная надпись",
            "Имя файла не совпадает с обозначением в штампе.",
            expected=f"{code} (по штампу)",
            actual=facts.filename or "",
        )
    ]


def part_code_mismatch(facts: ExtractedFacts) -> list[Finding]:
    title_code = facts.main_title.code
    if not title_code:
        return []
    findings: list[Finding] = []
    for i, blk in enumerate(facts.secondary_title_blocks):
        if not blk.code:
            continue
        cmp = compare(title_code, blk.code)
        if not cmp.is_match:
            findings.append(
                _f(
                    "part_code_mismatch",
                    "high",
                    f"дублирующий штамп #{i + 1}",
                    "Код в дублирующем штампе не совпадает с кодом в основной надписи.",
                    expected=title_code,
                    actual=blk.code,
                )
            )
    return findings


_SUFFIX_RE = re.compile(r"-([lr])\b", re.IGNORECASE)
_LEFT_RU = re.compile(r"\bлев", re.IGNORECASE)
_RIGHT_RU = re.compile(r"\bправ", re.IGNORECASE)


def _detect_side(text: str) -> str | None:
    if not text:
        return None
    m = _SUFFIX_RE.search(text)
    if m:
        return m.group(1).lower()
    if _LEFT_RU.search(text):
        return "l"
    if _RIGHT_RU.search(text):
        return "r"
    return None


def left_right_mismatch(facts: ExtractedFacts) -> list[Finding]:
    sources: list[tuple[str, str | None]] = [
        ("имя файла", facts.filename),
        ("основная надпись (название)", facts.main_title.name),
        ("основная надпись (код)", facts.main_title.code),
    ]
    for i, blk in enumerate(facts.secondary_title_blocks):
        sources.append((f"дублирующий штамп #{i + 1}", blk.name or blk.code))
    sides = {}
    for label, text in sources:
        side = _detect_side(text or "")
        if side:
            sides[label] = side
    if len(set(sides.values())) > 1:
        return [
            _f(
                "left_right_mismatch",
                "high",
                "сторонность (-l/-r) расходится",
                "Левая/правая сторонность не согласована между местами в чертеже.",
                expected="одинаковая сторонность во всех штампах и имени файла",
                actual="; ".join(f"{k}={v}" for k, v in sides.items()),
            )
        ]
    return []


def revision_index_mismatch(facts: ExtractedFacts) -> list[Finding]:
    """Сравниваем «хвост» после последнего разделителя в коде main vs filename."""
    code = facts.main_title.code or ""
    fname = strip_filename_markers(facts.filename or "")
    if not code or not fname:
        return []
    code_tail = re.split(r"[\/\.\-]+", code)[-1]
    fname_tail = re.split(r"[\/\.\-]+", fname)[-1]
    if code_tail and fname_tail and code_tail.lower() != fname_tail.lower():
        return [
            _f(
                "revision_index_mismatch",
                "high",
                "хвост артикула (ревизия/индекс)",
                "Хвост артикула в штампе не совпадает с хвостом в имени файла.",
                expected=code_tail,
                actual=fname_tail,
            )
        ]
    return []


_AISI = re.compile(r"AISI\s*\d+", re.IGNORECASE)


def material_mismatch(facts: ExtractedFacts) -> list[Finding]:
    """Если в filename упомянут AISI XXX, а в штампе другой — finding."""
    fname = facts.filename or ""
    title_material = (facts.material or "") + " " + (facts.material_aisi or "")
    m_fname = _AISI.search(fname)
    m_title = _AISI.search(title_material)
    if m_fname and m_title and m_fname.group(0).upper().replace(" ", "") != m_title.group(
        0
    ).upper().replace(" ", ""):
        return [
            _f(
                "material_mismatch",
                "medium",
                "материал в штампе",
                "Материал в штампе не совпадает с указанным в имени файла.",
                expected=m_fname.group(0).upper(),
                actual=m_title.group(0).upper(),
            )
        ]
    return []


def missing_title_block_field(facts: ExtractedFacts) -> list[Finding]:
    out: list[Finding] = []
    if not facts.material and not facts.material_aisi:
        out.append(
            _f(
                "missing_title_block_field",
                "medium",
                "основная надпись",
                "В штампе не указан материал.",
            )
        )
    if not facts.scale:
        out.append(
            _f(
                "missing_title_block_field",
                "medium",
                "основная надпись",
                "В штампе не указан масштаб.",
            )
        )
    if not facts.sheets_total:
        out.append(
            _f(
                "missing_title_block_field",
                "medium",
                "основная надпись",
                "В штампе не указано общее количество листов.",
            )
        )
    return out


def drawing_designation_mismatch_between_sheets(facts: ExtractedFacts) -> list[Finding]:
    designations = {s.designation for s in facts.stamps_on_each_sheet if s.designation}
    if len(designations) > 1:
        return [
            _f(
                "drawing_designation_mismatch_between_sheets",
                "high",
                "штампы листов",
                "Обозначение чертежа не совпадает между листами.",
                expected="одно обозначение на всех листах",
                actual="; ".join(sorted(designations)),
            )
        ]
    return []


_FASTENER = re.compile(r"(болт|гайка|винт|шуруп)", re.IGNORECASE)
_CLASS_PROCH = re.compile(r"A2-\d+|5\.8|8\.8|10\.9|12\.9", re.IGNORECASE)


def specification_fastener_class_missing(facts: ExtractedFacts) -> list[Finding]:
    """Experimental: если в ТТ указан A2-50, а в спецификации крепёж без класса."""
    if not facts.tt_text or not _CLASS_PROCH.search(facts.tt_text):
        return []
    findings: list[Finding] = []
    for row in facts.specification_rows:
        text = " ".join(filter(None, [row.name, row.code, row.note]))
        if _FASTENER.search(text) and not _CLASS_PROCH.search(text):
            findings.append(
                _f(
                    "specification_fastener_class_missing",
                    "medium",
                    f"спецификация, поз. {row.pos or '?'}",
                    f"Крепёж «{row.name}» без указания класса прочности при наличии "
                    "требования в ТТ.",
                )
            )
    return findings


ALL_RULES = (
    filename_title_mismatch,
    part_code_mismatch,
    left_right_mismatch,
    revision_index_mismatch,
    material_mismatch,
    missing_title_block_field,
    drawing_designation_mismatch_between_sheets,
    specification_fastener_class_missing,
)


def run_rules(facts: ExtractedFacts) -> list[Finding]:
    findings: list[Finding] = []
    for rule in ALL_RULES:
        try:
            findings.extend(rule(facts))
        except Exception:  # noqa: BLE001
            # одно правило не должно ронять пайплайн
            pass
    return findings
