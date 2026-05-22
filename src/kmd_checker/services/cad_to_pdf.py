"""DWG/DXF → PDF. Цепочка: dwg2dxf (libredwg) → ezdxf+matplotlib → PDF."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import ezdxf
import matplotlib.pyplot as plt
from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
from matplotlib.backends.backend_pdf import PdfPages

from kmd_checker import settings

logger = logging.getLogger(__name__)


class CadConvertError(RuntimeError):
    pass


async def cad_to_pdf(input_path: Path, out_dir: Path) -> Path:
    """DWG/DXF → PDF в out_dir. Бросает CadConvertError при провале."""
    ext = input_path.suffix.lower()
    if ext == ".dxf":
        dxf_path = input_path
    elif ext == ".dwg":
        dxf_path = await _dwg_to_dxf(input_path, out_dir)
    else:
        raise CadConvertError(f"unsupported extension: {ext}")
    return await asyncio.to_thread(_dxf_to_pdf_sync, dxf_path, out_dir)


async def _dwg_to_dxf(dwg_path: Path, out_dir: Path) -> Path:
    dxf_path = out_dir / (dwg_path.stem + ".dxf")
    proc = await asyncio.create_subprocess_exec(
        "dwg2dxf",
        str(dwg_path),
        "-o",
        str(dxf_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        _, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.CAD_CONVERT_TIMEOUT_SEC
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise CadConvertError("dwg2dxf timeout")
    if proc.returncode != 0 or not dxf_path.exists():
        msg = stderr.decode(errors="replace")[:500] if stderr else "no stderr"
        raise CadConvertError(f"dwg2dxf failed: {msg}")
    return dxf_path


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
