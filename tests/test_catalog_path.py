"""Where the catalog lives.

v0.1 and v0.2 resolved the catalog relative to the working directory, which was
fine when the only way to run SkillRoute was from a git checkout. Since 0.2
publishes to PyPI and npm, a user can `uvx skillroute` with no checkout at all,
and a checkout-relative default points at a directory that does not exist.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from skillroute.catalog import default_catalog_path, user_catalog_path


@pytest.fixture(autouse=True)
def clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SKILLROUTE_CATALOG_PATH", raising=False)


def test_user_catalog_path_is_under_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    assert user_catalog_path() == (tmp_path / ".skillroute" / "catalog.db").resolve()


def test_env_var_still_wins(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "explicit" / "catalog.db"
    monkeypatch.setenv("SKILLROUTE_CATALOG_PATH", str(target))
    assert default_catalog_path() == target.resolve()
    assert default_catalog_path(tmp_path / "elsewhere") == target.resolve()


def test_default_is_the_user_catalog_when_no_project_catalog_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert default_catalog_path(project) == (home / ".skillroute" / "catalog.db").resolve()


def test_an_existing_project_catalog_still_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Anyone who indexed into their checkout keeps using it.

    Silently switching them to an empty catalog under $HOME would look like
    their whole library vanished.
    """
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    (project / ".skillroute").mkdir(parents=True)
    existing = project / ".skillroute" / "catalog.db"
    existing.write_bytes(b"")
    monkeypatch.setenv("HOME", str(home))
    assert default_catalog_path(project) == existing.resolve()


def test_project_fallback_uses_cwd_when_no_base_is_given(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    (project / ".skillroute").mkdir(parents=True)
    (project / ".skillroute" / "catalog.db").write_bytes(b"")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    assert default_catalog_path() == (project / ".skillroute" / "catalog.db").resolve()


def test_a_project_directory_without_a_catalog_does_not_capture_the_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An empty .skillroute/ dir is not a catalog."""
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    (project / ".skillroute").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    assert default_catalog_path(project) == (home / ".skillroute" / "catalog.db").resolve()


# --- generated configs ----------------------------------------------------


def test_published_configs_never_point_at_a_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The bug this change exists to fix.

    An npx-resolved server has no checkout, so its catalog must not be resolved
    against one -- even when the machine generating the config has one.
    """
    from skillroute.harness_render import build_harness_setup

    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "checkout"
    (repo / ".skillroute").mkdir(parents=True)
    (repo / ".skillroute" / "catalog.db").write_bytes(b"")
    monkeypatch.setenv("HOME", str(home))

    payload = build_harness_setup(
        harness="claude-code", mode="mcp", repo_root=repo, server_source="npx"
    )
    catalog = payload["server_config"]["env"]["SKILLROUTE_CATALOG_PATH"]
    assert str(repo) not in catalog
    assert catalog == str((home / ".skillroute" / "catalog.db").resolve())


def test_local_configs_still_use_the_checkout_catalog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from skillroute.harness_render import build_harness_setup

    home = tmp_path / "home"
    home.mkdir()
    repo = tmp_path / "checkout"
    (repo / ".skillroute").mkdir(parents=True)
    (repo / ".skillroute" / "catalog.db").write_bytes(b"")
    monkeypatch.setenv("HOME", str(home))

    payload = build_harness_setup(
        harness="claude-code", mode="mcp", repo_root=repo, server_source="local"
    )
    catalog = payload["server_config"]["env"]["SKILLROUTE_CATALOG_PATH"]
    assert catalog == str((repo / ".skillroute" / "catalog.db").resolve())


def test_an_explicit_catalog_argument_overrides_both(tmp_path: Path) -> None:
    from skillroute.harness_render import build_harness_setup

    explicit = tmp_path / "chosen.db"
    payload = build_harness_setup(
        harness="claude-code",
        mode="mcp",
        repo_root=tmp_path,
        catalog=explicit,
        server_source="npx",
    )
    assert payload["server_config"]["env"]["SKILLROUTE_CATALOG_PATH"] == str(
        explicit.resolve()
    )
