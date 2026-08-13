"""Hatch build hook that ships bundled assets inside distributions.

Two things travel with the package:

* the built web UI -- wheels get it at ``skillroute/_web`` so ``skillroute ui``
  works from a plain ``pip install``; sdists keep it at ``web/dist`` so wheels
  built from an sdist do not need node.
* the harness manifests -- wheels get them at ``skillroute/_harnesses``, which
  is where ``harnesses.default_manifest_root()`` looks first. Without this a
  pip-installed SkillRoute would know about no harnesses at all.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class WebAssetsBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if version == "editable":
            return
        web_dir = Path(self.root) / "web"
        dist = web_dir / "dist"
        if not (dist / "index.html").exists():
            self._build_web_assets(web_dir)
        force_include = build_data.setdefault("force_include", {})
        target = "skillroute/_web" if self.target_name == "wheel" else "web/dist"
        force_include[str(dist)] = target

        harnesses = Path(self.root) / "harnesses"
        if not any(harnesses.glob("*.toml")):
            raise RuntimeError(f"No harness manifests found in {harnesses}")
        force_include[str(harnesses)] = (
            "skillroute/_harnesses" if self.target_name == "wheel" else "harnesses"
        )

    def _build_web_assets(self, web_dir: Path) -> None:
        npm = shutil.which("npm")
        if npm is None:
            raise RuntimeError(
                "web/dist is missing and npm is not available to build it. "
                "Run `npm --prefix web ci && npm --prefix web run build` first."
            )
        subprocess.run([npm, "--prefix", str(web_dir), "ci"], check=True)
        subprocess.run([npm, "--prefix", str(web_dir), "run", "build"], check=True)
