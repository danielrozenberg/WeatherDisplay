#!/usr/bin/env bash
#
# Full local gate: format check, lint, type-check, tests. Run before committing.
#
# It only checks the repo (no writes, no network), so it is safe to add to your
# Claude Code always-allow list as `Bash(./tools/ci.sh)`.
#
# Usage:  ./tools/ci.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Prefer the project virtualenv's tools; fall back to whatever is on PATH.
VENV_BIN="${ROOT}/.venv/bin"
if [[ -x "${VENV_BIN}/ruff" ]]; then
  PATH="${VENV_BIN}:${PATH}"
fi

run() {
  echo ":: $*"
  "$@"
}

run ruff format --check .
run ruff check .
run pyrefly check
run python -m pytest -q

echo "OK: all gate checks passed."
