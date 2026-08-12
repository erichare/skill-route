from __future__ import annotations

from pathlib import Path

import pytest

from skillroute.context import (
    REPO_ROOT_ENV,
    allowed_repo_root,
    collect_repo_context,
    resolve_repo_within,
)


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


def test_allowed_repo_root_unset_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(REPO_ROOT_ENV, raising=False)
    assert allowed_repo_root() is None

    monkeypatch.setenv(REPO_ROOT_ENV, "")
    assert allowed_repo_root() is None


def test_allowed_repo_root_resolves(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(REPO_ROOT_ENV, str(tmp_path))
    assert allowed_repo_root() == tmp_path.resolve()


def test_resolve_repo_within_accepts_contained_paths(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    (root / "project").mkdir()

    assert resolve_repo_within(root / "project", root) == root / "project"
    assert resolve_repo_within("project", root) == root / "project"  # relative to root
    assert resolve_repo_within(root, root) == root  # the root itself


def test_resolve_repo_within_rejects_escapes(tmp_path: Path) -> None:
    root = (tmp_path / "allowed").resolve()
    root.mkdir()
    outside = (tmp_path / "secret").resolve()
    outside.mkdir()

    for escape in [str(outside), "../secret", "project/../../secret", "/etc"]:
        with pytest.raises(ValueError, match="must stay inside"):
            resolve_repo_within(escape, root)


def test_resolve_repo_within_rejects_symlink_escape(tmp_path: Path) -> None:
    """Resolution happens before the check, so a symlink out is still caught."""
    root = (tmp_path / "allowed").resolve()
    root.mkdir()
    outside = (tmp_path / "secret").resolve()
    outside.mkdir()
    (root / "sneaky").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="must stay inside"):
        resolve_repo_within(root / "sneaky", root)
