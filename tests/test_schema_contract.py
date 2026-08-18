"""The Pydantic and JavaScript sides must agree about what a Recording is.

SS15.2 makes the JSON Schema the single source of truth and generates both
sides from it. That guarantees the *shapes* were derived from one file, but not
that the two generators read it the same way -- so this validates a document the
Python side produced using the validator the JavaScript side will run.

This is the test that catches a codegen bug rather than a schema bug, and it has
already earned its place once: datamodel-code-generator emitted a bare
`IframeHop | ShadowHop` for a cross-file oneOf without importing either name.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests import factories as f

ROOT = Path(__file__).resolve().parents[1]
VALIDATORS = ROOT / "extension" / "src" / "schemas" / "validators.js"


def run_js_validator(fn: str, payload: dict) -> tuple[bool, list]:
    """Validate `payload` with a generated Ajv standalone validator."""
    # The document arrives on stdin: a real recording is far past the Windows
    # command-line length limit.
    script = textwrap.dedent(f"""
        import {{ {fn} }} from {json.dumps(VALIDATORS.as_uri())};
        let raw = '';
        process.stdin.setEncoding('utf8');
        process.stdin.on('data', (c) => {{ raw += c; }});
        process.stdin.on('end', () => {{
          const ok = {fn}(JSON.parse(raw));
          process.stdout.write(JSON.stringify({{ ok, errors: {fn}.errors ?? [] }}));
        }});
    """)
    tmp = ROOT / "runs" / "_contract_check.mjs"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(script, encoding="utf-8")
    try:
        out = subprocess.run(
            ["node", str(tmp)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            cwd=ROOT,
            timeout=60,
        )
    finally:
        tmp.unlink(missing_ok=True)
    if out.returncode != 0:
        raise AssertionError(f"node failed: {out.stderr[:2000]}")
    result = json.loads(out.stdout)
    return result["ok"], result["errors"]


def as_json(model) -> dict:
    """Serialize the way the pipeline writes artifacts to disk."""
    return json.loads(model.model_dump_json(exclude_none=True))


@pytest.mark.parametrize(
    ("fn", "build"),
    [
        ("validateRecording", lambda: f.recording()),
        ("validateIRDocument", lambda: f.ir_document()),
    ],
)
def test_python_output_passes_js_validator(fn, build):
    ok, errors = run_js_validator(fn, as_json(build()))
    assert ok, f"{fn} rejected a document Pydantic accepted: {errors}"


def test_recording_with_full_event_shape_passes():
    """Exercise the optional branches the minimal fixture skips."""
    rec = f.recording(
        events=[
            f.event(
                "evt_001",
                0,
                at=0.0,
                diff=f.confirmation_diff(),
                network=[f.network_call()],
                fidelity=["settle_timeout"],
                settle={"reason": "timeout", "waitedMs": 5000.0},
                screenshot="screens/evt_001.png",
                transient=f.snapshot(live=[f.node("0.4", "alert", "Order confirmed")]),
            )
        ],
        objective="verify that orders over EUR500 require approval",
    )
    ok, errors = run_js_validator("validateRecording", as_json(rec))
    assert ok, errors


def test_js_validator_rejects_what_pydantic_would_reject():
    """A shared schema is only useful if both sides reject the same things."""
    bad = as_json(f.recording())
    bad["events"][0]["target"].pop("selectors")
    ok, errors = run_js_validator("validateRecording", bad)
    assert not ok
    assert any(e["keyword"] == "required" for e in errors), errors


def test_unknown_fields_are_rejected_on_both_sides():
    """additionalProperties:false is what makes drift show up as a failure."""
    bad = as_json(f.recording())
    bad["events"][0]["unexpectedField"] = "surprise"
    ok, _ = run_js_validator("validateRecording", bad)
    assert not ok

    from pydantic import ValidationError

    from server.models import Recording

    with pytest.raises(ValidationError):
        Recording.model_validate(bad)


def test_date_time_format_is_enforced():
    """gen-validators.mjs inlines the RFC 3339 regex rather than pulling in
    ajv-formats. If that regex is ever dropped, `createdAt` silently degrades to
    'any string' -- this is the test that notices."""
    bad = as_json(f.recording())
    bad["createdAt"] = "last Tuesday"
    ok, errors = run_js_validator("validateRecording", bad)
    assert not ok
    assert any(e["keyword"] == "format" for e in errors), errors
