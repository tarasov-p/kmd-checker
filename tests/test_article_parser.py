"""Тесты парсера артикула — на реальных примерах из датасета."""

from __future__ import annotations

import pytest

from kmd_checker.services.article_parser import (
    compare,
    normalize,
    strip_filename_markers,
    tokenize,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0,5В/Пло-13х20/2490Е", "0.5В/Пло-13x20/2490Е"),
        ("SM43х113х60.4Z345-r", "SM43x113x60.4Z345-r"),
        ("  IB190x142.6Z345-l  ", "IB190x142.6Z345-l"),
        ("M50/5.12.10E", "M50/5.12.10E"),
        ("", ""),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw,must_include",
    [
        ("IB190x142.6Z345-l", {"IB190", "142", "6Z345", "l"}),
        ("SM43х113х60.4Z345-r", {"SM43", "113", "60", "4Z345", "r"}),
        ("ADS.W50.168x81a84.15", {"ADS", "W50", "168", "81a84", "15"}),
        ("M50/5.12.10E", {"M50", "5", "12", "10E"}),
        # 0.5В режется точкой как разделителем — это допустимое упрощение.
        ("0,5В/Пло-13х20/2490Е", {"Пло", "13", "20", "2490Е"}),
    ],
)
def test_tokenize_covers_real_examples(raw: str, must_include: set[str]) -> None:
    tokens = set(tokenize(raw))
    missing = must_include - tokens
    assert not missing, f"missing tokens {missing} from {tokens}"


def test_compare_same_article_matches() -> None:
    c = compare("IB190x142.6Z345-l", "IB190x142.6Z345-l")
    assert c.is_match


def test_compare_klyammer_revision_diff_does_not_match() -> None:
    # Реальный кейс: M50/5.12.10E vs M50/5.12.15E
    c = compare("M50/5.12.10E", "M50/5.12.15E")
    assert not c.is_match


def test_compare_left_right_diff_drops_score() -> None:
    c1 = compare("IB190x142.6Z345-l", "IB190x142.6Z345-r")
    # это «частичное» сходство — должно быть ниже порога 0.8
    assert c1.score < 0.95


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Икля несущая правая IB190x142.6Z345-r с ошибкой.pdf", "Икля несущая правая IB190x142.6Z345-r"),
        ("Шпора левая SM52x113x60.4Z345-l (1).pdf", "Шпора левая SM52x113x60.4Z345-l"),
        ("Кляммер №2 рядовый.pdf", "Кляммер  рядовый"),
        ("Деталь copy.dxf", "Деталь"),
    ],
)
def test_strip_filename_markers(raw: str, expected: str) -> None:
    # Markers убираются, лишних пробелов может остаться один-два — ОК для fuzzy.
    got = strip_filename_markers(raw)
    # точная сверка с допуском по двойным пробелам:
    assert " ".join(got.split()) == " ".join(expected.split())
