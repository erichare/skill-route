from __future__ import annotations

import os
from pathlib import Path
from typing import Any

REPO_ROOT_ENV = "SKILLROUTE_REPO_ROOT"

LANGUAGE_EXTENSIONS = {
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".py": "python",
    ".rs": "rust",
    ".swift": "swift",
    ".ts": "typescript",
    ".tsx": "typescript",
}

SIGNAL_FILES = {
    "Cargo.toml": "rust",
    "go.mod": "go",
    "package.json": "javascript",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "Package.swift": "swift",
}


def allowed_repo_root() -> Path | None:
    """Base directory callers may point ``repo`` at, or None when unset.

    Only consulted on untrusted surfaces. A local CLI user naming their own
    checkout is not a trust boundary; an HTTP caller naming a path is.
    """
    raw = os.environ.get(REPO_ROOT_ENV)
    if not raw:
        return None
    return Path(raw).expanduser().resolve()


def resolve_repo_within(repo: str | Path, root: Path) -> Path:
    """Resolve ``repo`` and confirm it stays inside ``root``.

    Relative paths are taken against ``root``. Resolution happens before the
    containment check, so ``..`` segments and symlinks pointing outside are
    caught rather than smuggled through.

    CodeQL reports ``py/path-injection`` on the ``resolve()`` below and it is a
    false positive: this function is the sanitizer, and the resolved value only
    reaches a caller after ``is_relative_to`` passes. CodeQL does not model
    ``is_relative_to`` as a barrier.

    Do not rewrite this as a ``startswith`` prefix check to appease the scanner.
    That pattern is what CodeQL recognises, and it is strictly weaker here: a
    sibling directory sharing the root's name as a prefix (``/root-evil`` for a
    root of ``/root``) passes a prefix test and is correctly rejected by
    ``is_relative_to``. ``tests/test_context.py`` covers that case.
    """
    candidate = Path(repo).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"repo must stay inside {root}, got {resolved}")
    return resolved


def collect_repo_context(repo: Path | None) -> dict[str, Any]:
    if repo is None:
        return {"repo_path": None, "languages": [], "signals": [], "file_count": 0}
    repo = repo.resolve()
    if not repo.exists() or not repo.is_dir():
        return {"repo_path": str(repo), "languages": [], "signals": ["missing"], "file_count": 0}

    languages: set[str] = set()
    signals: set[str] = set()
    file_count = 0
    for signal_file, language in SIGNAL_FILES.items():
        if (repo / signal_file).exists():
            signals.add(signal_file)
            languages.add(language)

    for path in repo.rglob("*"):
        if ".git" in path.parts or path.is_dir():
            continue
        file_count += 1
        mapped_language = LANGUAGE_EXTENSIONS.get(path.suffix)
        if mapped_language:
            languages.add(mapped_language)
        if file_count >= 1000:
            signals.add("truncated_file_scan")
            break

    return {
        "repo_path": str(repo),
        "languages": sorted(languages),
        "signals": sorted(signals),
        "file_count": file_count,
    }

