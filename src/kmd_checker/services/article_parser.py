"""Парсер артикула. 2 этапа: нормализация → токенизация. Jaccard + WRatio."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz


def normalize(s: str) -> str:
    if not s:
        return ""
    out = s.strip()
    out = out.replace("х", "x").replace("Х", "X")  # кириллическая «х» → латинская «x»
    out = re.sub(r"(?<=\d),(?=\d)", ".", out)  # «0,5» → «0.5»
    out = re.sub(r"\s+", "", out)
    return out


_SEP = re.compile(r"[\/\.\-]+")
_HAS_DIMS = re.compile(r"\d[xX]\d")


def tokenize(article: str) -> list[str]:
    s = normalize(article)
    if not s:
        return []
    raw = [t for t in _SEP.split(s) if t]
    expanded: list[str] = []
    for tok in raw:
        if _HAS_DIMS.search(tok):
            # SM43x113x60 → ['SM43','113','60']; 168x81a84 → ['168','81a84']
            for part in re.split(r"[xX]", tok):
                if part:
                    expanded.append(part)
        else:
            expanded.append(tok)
    return [t for t in expanded if t]


def jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa and not sb:
        return 1.0
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


@dataclass(slots=True)
class ArticleCompare:
    a: str
    b: str
    a_tokens: list[str]
    b_tokens: list[str]
    jaccard: float
    wratio: float

    @property
    def score(self) -> float:
        return 0.6 * self.jaccard + 0.4 * (self.wratio / 100.0)

    @property
    def is_match(self) -> bool:
        return self.score >= 0.8


def compare(a: str, b: str) -> ArticleCompare:
    a_tokens = tokenize(a)
    b_tokens = tokenize(b)
    j = jaccard(a_tokens, b_tokens)
    w = fuzz.WRatio(normalize(a), normalize(b))
    return ArticleCompare(a=a, b=b, a_tokens=a_tokens, b_tokens=b_tokens, jaccard=j, wratio=w)


def strip_filename_markers(name: str) -> str:
    """Убрать «с ошибкой», «copy», «№2» и расширение из имени файла."""
    n = re.sub(r"\.(pdf|dwg|dxf)$", "", name, flags=re.IGNORECASE)
    n = re.sub(r"\s*с\s*ошибкой\b", "", n, flags=re.IGNORECASE)
    n = re.sub(r"\b(copy|копия)\b", "", n, flags=re.IGNORECASE)
    n = re.sub(r"№\s*\d+", "", n)
    n = re.sub(r"\(\d+\)", "", n)
    return n.strip()
