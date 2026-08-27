#!/usr/bin/env bash
#
# Fresh clone -> runnable tool, in one command.
#
# What this replaces is five commands in a specific order, two of which differ
# by platform, and one of which (`pnpm --filter @aitc-rem/ui build`) is only
# discovered when the review UI answers 503. None of that is interesting, and
# getting it wrong is the first thing that happens to a new person here.
#
# Every step is idempotent: run it again after a pull and it installs what
# changed and skips what did not.
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
# shellcheck source=scripts/_python.sh
source "$ROOT/scripts/_python.sh"

with_models=1
with_transcription=0
quiet=0

usage() {
  cat <<'USAGE'
usage: bash scripts/setup.sh [options]

  --no-models           skip the google-genai extra (no real model calls;
                        everything up to the validation gate still runs)
  --with-transcription  also install faster-whisper for narration audio (large)
  --quiet               only report what changed
  -h, --help            this

Then: pnpm start
USAGE
}

for arg in "$@"; do
  case "$arg" in
    --no-models) with_models=0 ;;
    --with-transcription) with_transcription=1 ;;
    --quiet) quiet=1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "setup: unknown option $arg" >&2; usage >&2; exit 2 ;;
  esac
done

say() { [ "$quiet" -eq 1 ] || echo "$@"; }
die() { echo ""; echo "setup: $*" >&2; exit 1; }

step() {
  say ""
  say "=== $1 ==="
}

# --- node -------------------------------------------------------------------

step "node dependencies"
if ! command -v pnpm >/dev/null 2>&1; then
  die "pnpm is not installed. Get it with:
    corepack enable && corepack prepare pnpm@10.6.1 --activate
  or see https://pnpm.io/installation"
fi
pnpm install || die "pnpm install failed"

# --- python -----------------------------------------------------------------

step "python environment"
if ! PYTHON="$(venv_python)"; then
  HOST="$(host_python)" || die "no Python 3.12+ on PATH. The server needs 3.12 or newer."
  say "creating .venv from $HOST"
  "$HOST" -m venv .venv || die "could not create .venv"
  PYTHON="$(venv_python)" || die ".venv was created but has no interpreter in it"
else
  say "reusing $PYTHON"
fi

extras="dev"
[ "$with_models" -eq 1 ] && extras="$extras,models"
[ "$with_transcription" -eq 1 ] && extras="$extras,transcription"

say "installing .[$extras]"
"$PYTHON" -m pip install --quiet --upgrade pip || die "could not upgrade pip"
"$PYTHON" -m pip install --quiet -e ".[$extras]" || die "pip install of .[$extras] failed"

# --- build ------------------------------------------------------------------

# Both are needed before the tool does anything visible: the review UI is what
# `serve` mounts at /, and the recorder is loaded into Chrome from a built
# directory, not from source.
step "review UI"
pnpm --filter @aitc-rem/ui build || die "the review UI did not build"

step "recorder extension"
pnpm --filter @aitc-rem/extension build || die "the extension did not build"

# --- local config -----------------------------------------------------------

step "local config"
if [ -f .env ]; then
  say ".env exists, leaving it alone"
else
  cp .env.example .env
  say "wrote .env from .env.example (gitignored; add your key to call a real model)"
fi

# --- what now ---------------------------------------------------------------

cat <<BANNER

Setup complete.

  pnpm start            the server and the review UI on http://127.0.0.1:8000
  pnpm start --demo     the same, plus the fixture app on http://localhost:5173

Load the recorder once, in Chrome: chrome://extensions -> Developer mode ->
Load unpacked -> $ROOT/extension/dist
BANNER

if [ "$with_models" -eq 1 ] && ! grep -qE '^GEMINI_API_KEY=.+' .env 2>/dev/null; then
  cat <<'KEY'

No GEMINI_API_KEY in .env yet. Everything up to and including the validation
gate runs without one; the drafting stage needs it. Key: aistudio.google.com/apikey
KEY
fi
