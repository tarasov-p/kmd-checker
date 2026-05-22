"""Тесты rules engine на синтетических ExtractedFacts."""

from __future__ import annotations

from kmd_checker.entities import (
    ExtractedFacts,
    SpecRow,
    StampOnSheet,
    TitleBlock,
)
from kmd_checker.services.rules_engine import run_rules


def _facts(**overrides) -> ExtractedFacts:
    base = ExtractedFacts(
        filename="IB190x142.6Z345-l.pdf",
        main_title=TitleBlock(name="Икля несущая левая", code="IB190x142.6Z345-l"),
        material="09Г2С",
        scale="1:1",
        sheets_total="1",
    )
    return base.model_copy(update=overrides)


def test_no_findings_on_consistent_drawing() -> None:
    findings = run_rules(_facts())
    assert findings == []


def test_filename_title_mismatch_triggers() -> None:
    facts = _facts(filename="WRONG_NAME.pdf")
    findings = run_rules(facts)
    assert any(f.class_code == "filename_title_mismatch" for f in findings)


def test_left_right_mismatch_in_secondary_block() -> None:
    facts = _facts(
        secondary_title_blocks=[
            TitleBlock(name="Икля несущая правая", code="IB190x142.6Z345-r"),
        ]
    )
    findings = run_rules(facts)
    assert any(f.class_code == "left_right_mismatch" for f in findings)


def test_revision_index_mismatch_klyammer() -> None:
    # Реальный кейс: filename = ...10E.pdf, штамп = ...15E
    facts = _facts(
        filename="Кляммер M50_5.12.10E с ошибкой.pdf",
        main_title=TitleBlock(name="Кляммер рядовый", code="M50/5.12.15E"),
    )
    findings = run_rules(facts)
    assert any(f.class_code == "revision_index_mismatch" for f in findings)


def test_missing_material_and_scale() -> None:
    facts = _facts(material=None, material_aisi=None, scale=None, sheets_total=None)
    findings = run_rules(facts)
    classes = {f.class_code for f in findings}
    assert "missing_title_block_field" in classes


def test_designation_mismatch_between_sheets() -> None:
    facts = _facts(
        stamps_on_each_sheet=[
            StampOnSheet(sheet=1, designation="ABC-001"),
            StampOnSheet(sheet=2, designation="ABC-002"),
        ]
    )
    findings = run_rules(facts)
    assert any(
        f.class_code == "drawing_designation_mismatch_between_sheets" for f in findings
    )


def test_material_aisi_mismatch() -> None:
    facts = _facts(
        filename="Закладная деталь ADS.W50 AISI 304.pdf",
        material_aisi="AISI 430",
    )
    findings = run_rules(facts)
    assert any(f.class_code == "material_mismatch" for f in findings)


def test_fastener_class_missing_experimental() -> None:
    facts = _facts(
        tt_text="Класс прочности крепежа A2-50.",
        specification_rows=[
            SpecRow(pos=1, name="Болт М12х40", code="М12х40", qty=2, note=None),
        ],
    )
    findings = run_rules(facts)
    classes = {f.class_code for f in findings}
    assert "specification_fastener_class_missing" in classes
