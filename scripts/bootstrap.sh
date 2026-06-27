#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

need_command uv
need_command node
need_command npm

echo "==> Installing Python dev environment"
uv sync --extra dev

echo "==> Installing MCP server dependencies"
npm --prefix mcp ci

echo "==> Building MCP server"
npm --prefix mcp run build

echo "==> Installing Skill Atlas web dependencies"
npm --prefix web ci

echo "==> Building Skill Atlas web UI"
npm --prefix web run build

echo "==> Indexing example skills"
uv run skillroute index --root examples/skills

echo "==> Checking local backend"
uv run skillroute backend status --backend local

cat <<'EOF'

SkillRoute is ready.

Try:
  uv run skillroute route "Build an MCP server that exposes routing tools"
  uv run skillroute inspect mcp-server-patterns
  uv run skillroute ui

Generate agent setup:
  uv run skillroute mcp config --client ibm-bob
  uv run skillroute mcp config --client codex
  uv run skillroute mcp config --client claude-code
  uv run skillroute mcp config --client claude-desktop
  uv run skillroute mcp config --client vscode
  uv run skillroute mcp config --client windsurf
  uv run skillroute mcp config --client cursor
EOF
