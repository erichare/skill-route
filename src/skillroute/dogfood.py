from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skillroute.catalog import Catalog
from skillroute.harnesses import skill_discovery_globs
from skillroute.parser import discover_skill_files

# Roots that belong to no single harness. Everything else now comes from the
# manifests, so a harness's skills directory is declared once, in its pack.
EXTRA_SKILL_ROOTS = (".agents/skills",)


def default_skill_roots() -> tuple[str, ...]:
    """Home-relative skill directories worth scanning.

    v0.1 hardcoded three entries here and notably missed ``.claude/skills``.
    Deriving them from the harness manifests means adding a harness with a
    skills directory automatically makes it discoverable.
    """
    roots: list[str] = []
    for candidate in (*skill_discovery_globs(), *EXTRA_SKILL_ROOTS):
        relative = candidate.lstrip("~/")
        if relative and relative not in roots:
            roots.append(relative)
    return tuple(roots)


def __getattr__(name: str) -> object:
    # Deprecated in 0.2: the hardcoded tuple became manifest-derived.
    if name == "DEFAULT_SKILL_ROOTS":
        return default_skill_roots()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
    seen: set[Path] = set()
    for relative_root in default_skill_roots():
        # Manifests may declare globs (Claude Code's plugin skill dirs), so
        # expand rather than treating every entry as a literal path.
        candidates = (
            sorted(home_path.glob(relative_root))
            if any(char in relative_root for char in "*?[")
            else [home_path / relative_root]
        )
        for root in candidates:
            resolved = root.resolve()
            if resolved in seen or not root.is_dir():
                continue
            seen.add(resolved)
            count = len(discover_skill_files(root))
            if count:
                roots.append(DogfoodRoot(path=resolved, skill_count=count))
    return roots


def index_default_skill_roots(catalog: Catalog, home: Path | None = None) -> DogfoodIndexResult:
    roots = discover_default_skill_roots(home)
    indexed_count = 0
    for root in roots:
        indexed_count += len(catalog.index_root(root.path))
    return DogfoodIndexResult(roots=roots, indexed_count=indexed_count)

