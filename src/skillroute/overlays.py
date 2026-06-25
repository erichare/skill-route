from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_overlays(root: Path) -> dict[str, dict[str, Any]]:
    overlay_dir = root / ".skillroute" / "overlays"
    if not overlay_dir.exists():
        return {}
    overlays: dict[str, dict[str, Any]] = {}
    for path in sorted(overlay_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for key, value in data.get("skills", {}).items():
            if isinstance(value, dict):
                overlays[key] = value
    return overlays


def overlay_for_skill(
    overlays: dict[str, dict[str, Any]],
    skill_file: Path,
    name: str | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    candidates = [
        str(skill_file.resolve()),
        str(skill_file),
        str(Path(skill_file.parent.name) / skill_file.name),
        str(skill_file.parent.resolve()),
        skill_file.parent.name,
    ]
    if root:
        try:
            candidates.insert(0, str(skill_file.resolve().relative_to(root.resolve())))
        except ValueError:
            pass
    if name:
        candidates.append(name)
    for candidate in candidates:
        if candidate in overlays:
            return overlays[candidate]
    return {}
