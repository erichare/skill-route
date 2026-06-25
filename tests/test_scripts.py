from __future__ import annotations

import subprocess
from pathlib import Path


def test_shell_scripts_have_valid_bash_syntax() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for script in ("scripts/bootstrap.sh", "scripts/install.sh"):
        subprocess.run(["bash", "-n", str(repo_root / script)], check=True)
