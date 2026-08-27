#!/usr/bin/env bash
#
# Finding the interpreter, in one place.
#
# The venv binary is `.venv/Scripts/python.exe` on Windows and `.venv/bin/python`
# everywhere else, and every script in here needs to resolve it the same way.
# It was copy-pasted into check.sh; a second copy in setup.sh and start.sh is how
# the three of them start disagreeing about which Python ran.
#
# Sourced, not executed. Expects $ROOT to be the repo root.

# Path to the venv interpreter, if the venv exists. Returns 1 if it does not.
venv_python() {
  if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    echo "$ROOT/.venv/Scripts/python.exe"
  elif [ -x "$ROOT/.venv/bin/python" ]; then
    echo "$ROOT/.venv/bin/python"
  else
    return 1
  fi
}

# Path to the venv interpreter, falling back to whatever `python` is on PATH.
# This is check.sh's historical behaviour: a repo without a venv still gets its
# checks run rather than a confusing "not found".
venv_python_or_system() {
  venv_python 2>/dev/null || echo "python"
}

# An interpreter on PATH new enough to build the venv from. pyproject requires
# >=3.12, and a venv built from 3.11 fails later, during an install, with an
# error that does not mention the version.
host_python() {
  local candidate
  for candidate in python3.14 python3.13 python3.12 python3 python; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}
