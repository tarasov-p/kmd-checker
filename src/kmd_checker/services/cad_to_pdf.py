"""DXF → PDF через ezdxf + matplotlib. (DWG не поддерживается в MVP.)"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import ezdxf
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from matplotlib.backends.backend_pdf import PdfPages

logger = logging.getLogger(__name__)


class CadConvertError(RuntimeError):
    pass


async def cad_to_pdf(input_path: Path, out_dir: Path) -> Path:
    """DXF → PDF в out_dir. Бросает CadConvertError при провале."""
    ext = input_path.suffix.lower()
    if ext != ".dxf":
        raise CadConvertError(f"only .dxf is supported, got {ext}")
    return await asyncio.to_thread(_dxf_to_pdf_sync, input_path, out_dir)


def _dxf_to_pdf_sync(dxf_path: Path, out_dir: Path) -> Path:
    try:
        doc = ezdxf.readfile(str(dxf_path))
    except (OSError, ezdxf.DXFError) as e:
        raise CadConvertError(f"ezdxf read failed: {e}") from e

    out_pdf = out_dir / (dxf_path.stem + ".pdf")
    layout_names = doc.layout_names()
    if not layout_names:
        raise CadConvertError("ezdxf: no layouts in DXF")
    with PdfPages(out_pdf) as pdf:
        for layout_name in layout_names:
            try:
                fig, ax = plt.subplots(figsize=(11.69, 8.27))
                ctx = RenderContext(doc)
                backend = MatplotlibBackend(ax)
                frontend = Frontend(ctx, backend)
                frontend.draw_layout(doc.layout(layout_name), finalize=True)
                pdf.savefig(fig)
            finally:
                plt.close("all")
    return out_pdf
