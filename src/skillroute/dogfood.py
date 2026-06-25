from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skillroute.catalog import Catalog
from skillroute.parser import discover_skill_files


DEFAULT_SKILL_ROOTS = (
    ".codex/skills",
    ".agents/skills",
    ".codex/plugins/cache",
)


@dataclass(slots=True)
class DogfoodRoot:
    path: Path
    skill_count: int


@dataclass(slots=True)
class DogfoodIndexResult:
    roots: list[DogfoodRoot]
    indexed_count: int


def discover_default_skill_roots(home: Path | None = None) -> list[DogfoodRoot]:
    home_path = (home or Path.home()).expanduser().resolve()
    roots: list[DogfoodRoot] = []
    for relative_root in DEFAULT_SKILL_ROOTS:
        root = home_path / relative_root
        if not root.is_dir():
            continue
        count = len(discover_skill_files(root))
        if count:
            roots.append(DogfoodRoot(path=root.resolve(), skill_count=count))
    return roots


def index_default_skill_roots(catalog: Catalog, home: Path | None = None) -> DogfoodIndexResult:
    roots = discover_default_skill_roots(home)
    indexed_count = 0
    for root in roots:
        indexed_count += len(catalog.index_root(root.path))
    return DogfoodIndexResult(roots=roots, indexed_count=indexed_count)

