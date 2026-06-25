from __future__ import annotations

import subprocess
from pathlib import Path


def test_shell_scripts_have_valid_bash_syntax() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    for script in ("scripts/bootstrap.sh", "scripts/install.sh"):
        subprocess.run(["bash", "-n", str(repo_root / script)], check=True)


def test_install_script_help_is_skillroute_first() -> None:
    repo_root = Path(__file__).resolve().parents[1]

    completed = subprocess.run(
        [str(repo_root / "scripts" / "install.sh"), "--help"],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "SkillRoute installer" in completed.stdout
    assert "--clients SPEC" in completed.stdout
    assert "--no-client-setup" in completed.stdout
    assert "--no-bob-write" not in completed.stdout
