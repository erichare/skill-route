from __future__ import annotations

from pathlib import Path

import pytest

from skillroute.catalog import Catalog


@pytest.fixture
def fixture_skills_root() -> Path:
    return Path(__file__).parent / "fixtures" / "skills"


@pytest.fixture
def indexed_catalog(tmp_path: Path, fixture_skills_root: Path) -> Catalog:
    catalog = Catalog(tmp_path / "catalog.db")
    catalog.index_root(fixture_skills_root)
    return catalog

