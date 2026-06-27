from __future__ import annotations

from pathlib import Path

from skillroute.context import collect_repo_context


def test_collect_repo_context_none_repo() -> None:
    context = collect_repo_context(None)
    assert context == {"repo_path": None, "languages": [], "signals": [], "file_count": 0}


def test_collect_repo_context_missing_repo(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"
    context = collect_repo_context(missing)
    assert context["languages"] == []
    assert "missing" in context["signals"]


def test_collect_repo_context_detects_languages_and_signals(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "app.ts").write_text("export {}", encoding="utf-8")
    context = collect_repo_context(tmp_path)
    assert "python" in context["languages"]
    assert "typescript" in context["languages"]
    assert "pyproject.toml" in context["signals"]
    assert context["file_count"] >= 3


def test_collect_repo_context_truncates_large_scan(tmp_path: Path) -> None:
    for index in range(1100):
        (tmp_path / f"file_{index}.txt").write_text("x", encoding="utf-8")
    context = collect_repo_context(tmp_path)
    assert "truncated_file_scan" in context["signals"]
    assert context["file_count"] == 1000
