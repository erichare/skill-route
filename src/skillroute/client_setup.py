"""Deprecated compatibility shim over :mod:`skillroute.harness_setup`.

v0.1 called agent tools "clients"; 0.2 calls them *harnesses* and declares them
in ``harnesses/*.toml``. The names here are kept for one release so existing
callers and scripts keep working, and will be removed in 0.3.
"""

from __future__ import annotations

from skillroute.harness_setup import (
    NO_TTY_SETUP_MESSAGE,
    SetupResult,
    build_parser,
    can_prompt,
    confirm,
    main,
    merge_json_config,
    print_detection_summary,
    run_detect_command,
    run_setup_command,
)
from skillroute.harness_setup import (
    SETUP_CHOICES as CLIENT_SETUP_CHOICES,
)
from skillroute.harness_setup import (
    HarnessDetection as ClientDetection,
)
from skillroute.harness_setup import (
    HarnessEnvironment as ClientEnvironment,
)
from skillroute.harness_setup import (
    apply_harness_setup as apply_client_setup,
)
from skillroute.harness_setup import (
    detect_harnesses as detect_clients,
)
from skillroute.harness_setup import (
    select_harnesses as select_clients,
)
from skillroute.harnesses import harness_ids

__all__ = [
    "CLIENT_ORDER",
    "CLIENT_SETUP_CHOICES",
    "NO_TTY_SETUP_MESSAGE",
    "ClientDetection",
    "ClientEnvironment",
    "SetupResult",
    "apply_client_setup",
    "build_parser",
    "can_prompt",
    "confirm",
    "detect_clients",
    "main",
    "merge_json_config",
    "print_detection_summary",
    "run_detect_command",
    "run_setup_command",
    "select_clients",
]


def _client_order() -> tuple[str, ...]:
    return harness_ids()


CLIENT_ORDER: tuple[str, ...] = _client_order()

if __name__ == "__main__":
    main()
