#!/usr/bin/env bash
#
# SS15.2 -- the JSON Schema files are the single source of truth. Both sides
# generate from them:
#
#   schema/*.schema.json
#     |- datamodel-code-generator  ->  server/models/generated/*.py     (Pydantic)
#     |- json-schema-to-typescript ->  extension/src/types/*.ts         (TS types)
#     '- ajv standalone            ->  extension/src/schemas/*.js       (runtime validation)
#
# SS15.4 names Zod for the client side; see tools/gen-validators.mjs for why
# Ajv standalone replaced it (json-schema-to-zod cannot resolve $ref and
# silently degrades every referenced type to z.any()).
#
# `--check` regenerates into a temp directory and diffs. Non-zero exit on drift.
# The cross-language boundary is a build step, not an ongoing hazard.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA_DIR="$ROOT/schema"

PY_REL="server/models/generated"
TS_REL="extension/src/types"
ZOD_REL="extension/src/schemas"

SCHEMAS=(common recording ir trace segments review)

CHECK=0
if [ "${1:-}" = "--check" ]; then CHECK=1; fi

log() { printf '  %s\n' "$*"; }

# Resolve the Python entrypoint: prefer the project venv, fall back to PATH.
pick_python() {
  if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
    echo "$ROOT/.venv/Scripts/python.exe"
  elif [ -x "$ROOT/.venv/bin/python" ]; then
    echo "$ROOT/.venv/bin/python"
  else
    echo "python"
  fi
}

PYTHON="$(pick_python)"

generate_into() {
  local dest="$1"
  mkdir -p "$dest/$PY_REL" "$dest/$TS_REL" "$dest/$ZOD_REL"

  # --- Pydantic -----------------------------------------------------------
  # A directory input lets datamodel-codegen resolve the cross-file $refs in
  # common.schema.json into real imports. It parses every file it finds, so the
  # schemas are staged alone -- codegen.sh and tools/ would fail it as YAML.
  log "pydantic -> $PY_REL"
  local staged
  staged="$(mktemp -d)"
  for s in "${SCHEMAS[@]}"; do
    cp "$SCHEMA_DIR/$s.schema.json" "$staged/"
  done

  "$PYTHON" -m datamodel_code_generator \
    --input "$staged" \
    --input-file-type jsonschema \
    --output "$dest/$PY_REL" \
    --output-model-type pydantic_v2.BaseModel \
    --target-python-version 3.12 \
    --use-standard-collections \
    --use-union-operator \
    --use-schema-description \
    --use-field-description \
    --disable-timestamp \
    --field-constraints \
    --collapse-root-models \
    --formatters ruff-format \
    --use-title-as-name \
    --base-class server.models.base.StrictModel
  rm -rf "$staged"

  # Field names are left in camelCase on purpose: the models are wire-format
  # DTOs, and matching the JSON exactly removes a whole class of alias bug.
  cat > "$dest/$PY_REL/__init__.py" <<'PYEOF'
"""Generated from schema/*.schema.json by schema/codegen.sh. Do not edit."""
PYEOF

  # --- TypeScript types ---------------------------------------------------
  for s in "${SCHEMAS[@]}"; do
    log "types -> $TS_REL/$s.ts"
    npx --no-install json2ts \
      --input "$SCHEMA_DIR/$s.schema.json" \
      --output "$dest/$TS_REL/$s.ts" \
      --cwd "$SCHEMA_DIR" \
      --additionalProperties false \
      --bannerComment "/* Generated from schema/$s.schema.json. Do not edit. */" \
      --unreachableDefinitions
  done

  # --- Runtime validators -------------------------------------------------
  # The extension validates what it is about to persist; a malformed recording
  # should fail at the recorder, not three stages downstream.
  node "$SCHEMA_DIR/tools/gen-validators.mjs" "$dest/$ZOD_REL"
}

if [ "$CHECK" -eq 1 ]; then
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  echo "Regenerating into a temp tree to check for drift..."
  generate_into "$TMP" > /dev/null

  status=0
  for rel in "$PY_REL" "$TS_REL" "$ZOD_REL"; do
    if ! diff -ru -x "__pycache__" -x ".ruff_cache" "$ROOT/$rel" "$TMP/$rel" > "$TMP/drift.diff" 2>&1; then
      echo ""
      echo "SCHEMA DRIFT in $rel -- generated code does not match schema/:"
      head -60 "$TMP/drift.diff"
      status=1
    fi
  done

  if [ "$status" -ne 0 ]; then
    echo ""
    echo "Run 'pnpm codegen' and commit the result."
    exit 1
  fi
  echo "No drift."
else
  echo "Generating from schema/ ..."
  rm -rf "$ROOT/$PY_REL" "$ROOT/$TS_REL" "$ROOT/$ZOD_REL"
  generate_into "$ROOT"
  echo "Done."
fi
