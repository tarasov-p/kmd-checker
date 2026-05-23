"""Click CLI: server / check."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
import uvicorn


@click.group()
def cli() -> None:
    """kmd-checker: веб-интерфейс проверки чертежей КМД."""


@cli.command()
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=8080, type=int, show_default=True)
@click.option("--reload", is_flag=True, help="dev: auto-reload")
def server(host: str, port: int, reload: bool) -> None:
    """Поднять FastAPI-сервер (single-process, как и задумано — stateless dict в памяти)."""
    uvicorn.run(
        "kmd_checker.web:app",
        host=host,
        port=port,
        reload=reload,
        workers=1,
        log_level="info",
    )


@cli.command()
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--force", is_flag=True, help="пропустить пре-чек «это чертёж?»")
def check(file_path: Path, force: bool) -> None:
    """Прогнать файл через пайплайн без HTTP-сервера."""
    from datetime import UTC, datetime

    from kmd_checker.entities import SessionState
    from kmd_checker.services.pipeline import make_tmp_dir, run_pipeline
    from kmd_checker.web import _detect_ext

    ext = _detect_ext(file_path.name)
    if ext is None:
        raise click.ClickException("only .pdf and .dxf are supported")

    sid = "cli-" + datetime.now(UTC).strftime("%Y%m%d%H%M%S")
    tmp = make_tmp_dir(sid)
    session = SessionState(
        session_id=sid,
        ext=ext,
        original_filename=file_path.name,
        started_at=datetime.now(UTC),
        tmp_dir=tmp,
        force=force,
    )

    async def _run() -> None:
        data = file_path.read_bytes()
        await run_pipeline(session, data)

    asyncio.run(_run())
    click.echo(session.model_dump_json(indent=2))
    sys.exit(0 if session.status == "done" else 1)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
