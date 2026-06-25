#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${SKILLROUTE_REPO_URL:-https://github.com/erichare/skill-route.git}"
REF="${SKILLROUTE_REF:-main}"
INSTALL_DIR="${SKILLROUTE_INSTALL_DIR:-}"
ASSUME_YES="${SKILLROUTE_ASSUME_YES:-0}"
WRITE_BOB_CONFIG="${SKILLROUTE_WRITE_BOB_CONFIG:-prompt}"
INDEX_LOCAL_SKILLS="${SKILLROUTE_INDEX_LOCAL_SKILLS:-prompt}"
BOB_CONFIG_PATH="${SKILLROUTE_BOB_CONFIG_PATH:-$HOME/.bob/mcp.json}"

if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
  BLUE="$(printf '\033[38;5;27m')"
  CYAN="$(printf '\033[36m')"
  GREEN="$(printf '\033[32m')"
  YELLOW="$(printf '\033[33m')"
  BOLD="$(printf '\033[1m')"
  RESET="$(printf '\033[0m')"
else
  BLUE=""
  CYAN=""
  GREEN=""
  YELLOW=""
  BOLD=""
  RESET=""
fi

usage() {
  cat <<'EOF'
SkillRoute installer

Usage:
  scripts/install.sh [options]
  curl -fsSL https://raw.githubusercontent.com/erichare/skill-route/main/scripts/install.sh | bash

Options:
  --yes                 Accept prompts.
  --install-dir PATH    Install or update SkillRoute at PATH.
  --repo URL            Git repository URL.
  --ref REF             Git branch, tag, or ref. Defaults to main.
  --no-bob-write        Do not write ~/.bob/mcp.json.
  --help                Show this help.

Environment:
  SKILLROUTE_INSTALL_DIR
  SKILLROUTE_REPO_URL
  SKILLROUTE_REF
  SKILLROUTE_ASSUME_YES=1
  SKILLROUTE_WRITE_BOB_CONFIG=0|1|prompt
  SKILLROUTE_INDEX_LOCAL_SKILLS=0|1|prompt
  SKILLROUTE_BOB_CONFIG_PATH
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y)
      ASSUME_YES=1
      shift
      ;;
    --install-dir)
      if [[ $# -lt 2 ]]; then
        echo "--install-dir requires a path" >&2
        exit 1
      fi
      INSTALL_DIR="$2"
      shift 2
      ;;
    --repo)
      if [[ $# -lt 2 ]]; then
        echo "--repo requires a URL" >&2
        exit 1
      fi
      REPO_URL="$2"
      shift 2
      ;;
    --ref)
      if [[ $# -lt 2 ]]; then
        echo "--ref requires a branch, tag, or ref" >&2
        exit 1
      fi
      REF="$2"
      shift 2
      ;;
    --no-bob-write)
      WRITE_BOB_CONFIG=0
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

is_truthy() {
  case "$1" in
    1|true|TRUE|yes|YES|y|Y) return 0 ;;
    *) return 1 ;;
  esac
}

say() {
  printf '%b\n' "$*"
}

banner() {
  say "${BLUE}${BOLD}"
  cat <<'EOF'
IBM Bob + SkillRoute
Local skill routing for agentic development
EOF
  say "${RESET}"
}

step() {
  say ""
  say "${CYAN}${BOLD}==>${RESET} ${BOLD}$1${RESET}"
}

ok() {
  say "${GREEN}[ok]${RESET} $1"
}

warn() {
  say "${YELLOW}[warn]${RESET} $1"
}

die() {
  say "${YELLOW}[error]${RESET} $1" >&2
  exit 1
}

confirm() {
  local prompt="$1"
  local reply
  if is_truthy "$ASSUME_YES"; then
    say "${GREEN}[yes]${RESET} $prompt"
    return 0
  fi
  if [[ ! -r /dev/tty ]]; then
    die "No terminal is available for prompts. Re-run with --yes or SKILLROUTE_ASSUME_YES=1."
  fi
  printf '%b? %s [y/N] %b' "$BOLD" "$prompt" "$RESET" > /dev/tty
  read -r reply < /dev/tty || return 1
  case "$reply" in
    y|Y|yes|YES) return 0 ;;
    *) return 1 ;;
  esac
}

should_do() {
  local setting="$1"
  local prompt="$2"
  case "$setting" in
    1|true|TRUE|yes|YES|y|Y) return 0 ;;
    0|false|FALSE|no|NO|n|N) return 1 ;;
    *) confirm "$prompt" ;;
  esac
}

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Missing required command: $1"
  fi
}

run_confirmed() {
  local label="$1"
  shift
  step "$label"
  if confirm "$label"; then
    "$@"
    ok "$label"
  else
    warn "Skipped: $label"
  fi
}

local_checkout_root() {
  local source_path="${BASH_SOURCE[0]:-}"
  local candidate
  if [[ -n "$source_path" && -f "$source_path" ]]; then
    candidate="$(cd "$(dirname "$source_path")/.." && pwd)"
    if [[ -f "$candidate/pyproject.toml" && -d "$candidate/mcp" ]]; then
      printf '%s\n' "$candidate"
    fi
  fi
}

ensure_clean_checkout() {
  local dir="$1"
  if ! git -C "$dir" diff --quiet || ! git -C "$dir" diff --cached --quiet; then
    die "Existing checkout has local changes: $dir"
  fi
}

prepare_checkout() {
  local detected_root="$1"
  local using_current="$2"

  step "Prepare SkillRoute checkout"
  if [[ "$using_current" == "1" ]]; then
    ok "Using current checkout: $detected_root"
    INSTALL_DIR="$detected_root"
    return
  fi

  if [[ -d "$INSTALL_DIR/.git" ]]; then
    if confirm "Update existing checkout at $INSTALL_DIR from $REF"; then
      ensure_clean_checkout "$INSTALL_DIR"
      git -C "$INSTALL_DIR" fetch origin "$REF"
      git -C "$INSTALL_DIR" checkout "$REF" 2>/dev/null || git -C "$INSTALL_DIR" checkout -t "origin/$REF"
      git -C "$INSTALL_DIR" pull --ff-only origin "$REF"
      ok "Updated checkout: $INSTALL_DIR"
    else
      warn "Using existing checkout without updating: $INSTALL_DIR"
    fi
    return
  fi

  if [[ -e "$INSTALL_DIR" && -n "$(ls -A "$INSTALL_DIR" 2>/dev/null || true)" ]]; then
    die "Install path exists and is not an empty directory: $INSTALL_DIR"
  fi

  if confirm "Clone SkillRoute into $INSTALL_DIR"; then
    mkdir -p "$(dirname "$INSTALL_DIR")"
    git clone --branch "$REF" "$REPO_URL" "$INSTALL_DIR"
    ok "Cloned SkillRoute: $INSTALL_DIR"
  else
    die "Cannot continue without a SkillRoute checkout."
  fi
}

write_bob_config() {
  local payload
  payload="$(uv run skillroute mcp config --client ibm-bob --json)"
  SKILLROUTE_MCP_PAYLOAD="$payload" BOB_CONFIG_PATH="$BOB_CONFIG_PATH" uv run python - <<'PY'
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from pathlib import Path

target = Path(os.environ["BOB_CONFIG_PATH"]).expanduser()
payload = json.loads(os.environ["SKILLROUTE_MCP_PAYLOAD"])
server = payload["config"]["mcpServers"]["skillroute"]

data: dict[str, object] = {}
backup_path: Path | None = None
if target.exists():
    try:
        data = json.loads(target.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Existing Bob MCP config is not valid JSON: {target}: {exc}") from exc
    timestamp = dt.datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = target.with_name(f"{target.name}.bak-{timestamp}")
    shutil.copy2(target, backup_path)

servers = data.setdefault("mcpServers", {})
if not isinstance(servers, dict):
    raise SystemExit(f"Bob MCP config has a non-object mcpServers field: {target}")
servers["skillroute"] = server

target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"Wrote {target}")
if backup_path:
    print(f"Backup {backup_path}")
PY
}

main() {
  local detected_root
  local using_current=0

  banner
  say "This installer sets up SkillRoute locally and prepares IBM Bob MCP config."
  say "Repository: $REPO_URL"
  say "Ref:        $REF"

  detected_root="$(local_checkout_root || true)"
  if [[ -z "$INSTALL_DIR" && -n "$detected_root" ]]; then
    INSTALL_DIR="$detected_root"
    using_current=1
  fi
  if [[ -z "$INSTALL_DIR" ]]; then
    INSTALL_DIR="$HOME/.skillroute/skill-route"
  fi
  say "Install:    $INSTALL_DIR"

  step "Check prerequisites"
  confirm "Check required commands: git, uv, node, npm" || die "Cannot continue without checking prerequisites."
  need_command git
  need_command uv
  need_command node
  need_command npm
  ok "Required commands are available"

  prepare_checkout "$detected_root" "$using_current"
  cd "$INSTALL_DIR"

  run_confirmed "Install Python environment with uv" uv sync --extra dev
  run_confirmed "Install MCP server Node dependencies" npm --prefix mcp install
  run_confirmed "Build MCP server" npm --prefix mcp run build
  run_confirmed "Index example skills" uv run skillroute index --root examples/skills

  step "Index local skill roots"
  if should_do "$INDEX_LOCAL_SKILLS" "Index local Codex and agent skill roots if found"; then
    uv run skillroute dogfood index
    ok "Local skill-root indexing complete"
  else
    warn "Skipped local skill-root indexing"
  fi

  run_confirmed "Check local retrieval backend" uv run skillroute backend status --backend local

  step "IBM Bob MCP setup"
  if should_do "$WRITE_BOB_CONFIG" "Write or update IBM Bob MCP config at $BOB_CONFIG_PATH"; then
    write_bob_config
    ok "IBM Bob MCP config is ready"
  else
    warn "IBM Bob MCP config was not written"
    say "Generate it later with:"
    say "  cd $INSTALL_DIR"
    say "  uv run skillroute mcp config --client ibm-bob"
  fi

  say ""
  say "${BLUE}${BOLD}SkillRoute is ready for IBM Bob.${RESET}"
  say "Try:"
  say "  cd $INSTALL_DIR"
  say "  uv run skillroute route \"Build an MCP server that exposes routing tools\""
  say ""
  say "Other agent setup:"
  say "  uv run skillroute mcp config --client codex"
  say "  uv run skillroute mcp config --client claude-code"
  say "  uv run skillroute mcp config --client claude-desktop"
}

main "$@"
