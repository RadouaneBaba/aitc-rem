#!/usr/bin/env bash
#
# The one command that launches the tool.
#
# It bootstraps if it has to, so `pnpm start` on a fresh clone is the whole
# first run -- no separate setup step to forget. After that it is just the
# server, starting in about a second.
#
# Anything it does not recognise is forwarded to `server.cli serve`, so
# `pnpm start --offline --port 8100 --bug-mode` works.
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/_python.sh
source "$ROOT/scripts/_python.sh"

demo=0
serve_args=()

for arg in "$@"; do
  case "$arg" in
    --demo) demo=1 ;;
    -h|--help)
      cat <<'USAGE'
usage: pnpm start [--demo] [serve options...]

  --demo   also run the fixture app on http://localhost:5173

Everything else is passed to `server.cli serve` (--port, --offline, --config,
--bug-mode, ...). First run bootstraps the venv, node deps and both builds.
USAGE
      exit 0
      ;;
    *) serve_args+=("$arg") ;;
  esac
done

# The bootstrap trigger is the four things `serve` and the recorder actually
# need on disk. Checking for them beats a marker file, which goes stale the
# first time somebody deletes node_modules to fix something else.
needs_setup=0
[ -d node_modules ] || needs_setup=1
venv_python >/dev/null 2>&1 || needs_setup=1
[ -d ui/dist ] || needs_setup=1
[ -d extension/dist ] || needs_setup=1

if [ "$needs_setup" -eq 1 ]; then
  echo "First run: setting things up. This takes a couple of minutes, once."
  bash "$ROOT/scripts/setup.sh" --quiet || exit 1
fi

PYTHON="$(venv_python)" || { echo "start: no .venv -- run 'bash scripts/setup.sh'" >&2; exit 1; }

demo_pid=""
cleanup() {
  [ -n "$demo_pid" ] && kill "$demo_pid" 2>/dev/null
}
trap cleanup EXIT INT TERM

if [ "$demo" -eq 1 ]; then
  pnpm --filter @aitc-rem/demo-app dev >/dev/null 2>&1 &
  demo_pid=$!
  echo "demo app   http://localhost:5173"
fi

echo "recorder   chrome://extensions -> Load unpacked -> $ROOT/extension/dist"
echo ""

if [ -n "$demo_pid" ]; then
  # Deliberately not `exec`: exec replaces this shell, the EXIT trap goes with
  # it, and the fixture app is left holding :5173 after Ctrl-C -- which the next
  # `pnpm start --demo` reports as a port conflict rather than as this.
  "$PYTHON" -m server.cli serve "${serve_args[@]}"
  exit $?
fi

exec "$PYTHON" -m server.cli serve "${serve_args[@]}"
