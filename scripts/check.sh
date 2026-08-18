#!/usr/bin/env bash
#
# The single entry point for "is this repo healthy?".
#
# This -- not the GitHub Actions workflow -- is the load-bearing piece. The
# schema is one source of truth generating into two languages (SS15.2), so drift
# means the extension writes a field the server silently drops and nothing
# complains for weeks. .github/workflows/ci.yml is a thin wrapper around this
# script and stays inert until there is a remote to push to.
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PYTHON="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  PYTHON="python"
fi

failures=()

step() {
  local name="$1"; shift
  echo ""
  echo "=== $name ==="
  if "$@"; then
    echo "--- $name: ok"
  else
    echo "--- $name: FAILED"
    failures+=("$name")
  fi
}

step "schema drift"  bash schema/codegen.sh --check
step "ruff"          "$PYTHON" -m ruff check server tests
step "pytest"        "$PYTHON" -m pytest -q

# Workspace packages opt in by declaring a "test" script; -r is a no-op until
# one does.
if [ -d node_modules ]; then
  step "vitest" pnpm -r --if-present test
fi

echo ""
if [ ${#failures[@]} -eq 0 ]; then
  echo "All checks passed."
  exit 0
fi
echo "FAILED: ${failures[*]}"
exit 1
