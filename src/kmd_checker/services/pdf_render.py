"""PDF → list[RenderedPage]. PyMuPDF, выполняется в thread."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import fitz  # PyMuPDF


@dataclass(slots=True)
class RenderedPage:
    index: int
    png_bytes: bytes
    text_layer: str
    width: int
    height: int


def _render_sync(pdf_bytes: bytes, dpi: int) -> list[RenderedPage]:
    pages: list[RenderedPage] = []
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        for i, page in enumerate(doc):
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png = pix.tobytes("png")
            text = page.get_text("text")
            pages.append(
                RenderedPage(
                    index=i,
                    png_bytes=png,
                    text_layer=text or "",
                    width=pix.width,
                    height=pix.height,
                )
            )
    return pages


async def render_pdf(pdf_bytes: bytes, dpi: int = 220) -> list[RenderedPage]:
    return await asyncio.to_thread(_render_sync, pdf_bytes, dpi)


def page_count(pdf_bytes: bytes) -> int:
    with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
        return doc.page_count
