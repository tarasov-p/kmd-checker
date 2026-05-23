"""Smoke: модули импортируются, FastAPI app собирается."""


def test_import_app() -> None:
    from kmd_checker.web import app

    assert app.title == "kmd-checker"


def test_pipeline_imports() -> None:
    from kmd_checker.services import pipeline, judge

    assert hasattr(pipeline, "run_pipeline")
    assert hasattr(judge, "judge_drawing")
    assert hasattr(judge, "is_drawing")
