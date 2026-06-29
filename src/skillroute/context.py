from __future__ import annotations

from pathlib import Path
from typing import Any


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

