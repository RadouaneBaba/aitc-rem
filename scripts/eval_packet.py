#!/usr/bin/env python
"""Assemble the one document "is this test case any good" can be answered from.

    Fourteen validators and an ablation table measure PROVENANCE -- whether a
    claim can point at the retrieval that produced it. None of them measure
    whether the test case is one a QA lead would sign. `rec_MTA7A2XHHH22`
    shipped fourteen validators green, 4 of 4 claims grounded, and three of the
    four proving nothing. The gate was right every time and the artifact was
    poor, so the gate is not the instrument that was missing.

The missing instrument is something with a human's judgement reading the feature
file beside what the tester actually did. This script makes that cheap by
putting the whole question on one page:

    what the tester said they were checking, and what they marked
    every recorded event, grouped under the step that CLAIMS it
    what came out
    what each surviving claim rests on
    what was proposed and REFUSED, with the reason
    what the gate said

Nothing here is a judgement. Judging is `.claude/agents/qa-judge.md` reading
this against `evals/RUBRIC.md`. Keeping the two apart is the point: the packet
is deterministic and diffable, so two verdicts on the same run differ because
the judge changed its mind rather than because it was shown different things.

    python scripts/eval_packet.py                 # every recording, newest run
    python scripts/eval_packet.py --id rec_MTA7A2XHHH22
    python scripts/eval_packet.py --run runs/rec_X/run_002 --stdout

Writes `evals/packets/<recordingId>.md`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

# `latest_runs` already encodes which run of a recording is the one worth
# reading, including why an `abl_*` run is skipped: A0 claims nothing by
# construction, so judging its output would be judging the ablation rather than
# the tool. One implementation, for the same reason `supports_narrated` is one.
from snapshot_features import latest_runs  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS = REPO_ROOT / "runs"
RECORDINGS = REPO_ROOT / "recordings"
FIXTURES = REPO_ROOT / "tests" / "fixtures"
OUT_DIR = REPO_ROOT / "evals" / "packets"

# A held-out recording is one no prompt was ever tuned against. Declared rather
# than inferred: "which of these did I look at while editing the prompt" is a
# fact about the history of the project, and nothing on disk records it.
HELD_OUT = {"rec_MT7MXBS9B2VB", "rec_MT7VTN7ZRJPO", "rec_MTA7A2XHHH22"}


def _load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _recording_path(recording_id: str) -> Path | None:
    """Where this recording lives. A fixture and a captured session differ."""
    direct = RECORDINGS / recording_id / "recording.json"
    if direct.is_file():
        return direct
    for candidate in sorted(FIXTURES.glob("*.recording.json")):
        body = _load(candidate)
        if isinstance(body, dict) and body.get("id") == recording_id:
            return candidate
    return None


def find_recording(recording_id: str) -> dict[str, Any] | None:
    """The recording **as the pipeline saw it**, which is not what is on disk.

    The e2e suite rewrites every fixture with an empty `narration`, and the
    transcript is produced from the committed audio beside it at RUN time by
    `attach_narration` -- the same call the CLI makes, and the same one
    `tests/test_fixture_outcomes.py` makes for the same reason.

    Reading the raw file therefore reports "Narration: none" for a recording the
    tester narrated. That is not a cosmetic difference in a judgement packet: it
    is the packet asserting the tester said nothing when they spoke, and it cost
    a whole judging pass -- a `narrated` assertion was reported as a gate hole,
    and the validator that passed it was right all along.

    Transcription needs `faster-whisper`. Where it is absent the packet says so
    rather than silently showing an absence it cannot distinguish from silence.
    """
    path = _recording_path(recording_id)
    if path is None:
        return None
    body = _load(path)
    if not isinstance(body, dict):
        return None
    if body.get("narration"):
        return body

    try:
        from server.cli import attach_narration
        from server.config import load_project_config
        from server.models import Recording

        recording = Recording.model_validate(body)
        attach_narration(
            recording, path, transcript=None, offset_ms=0.0,
            project=load_project_config(), quiet=True,
        )
        body["narration"] = [
            s.model_dump(mode="json") for s in (recording.narration or [])
        ]
        body["_narrationSource"] = "transcribed from the committed audio at packet time"
    except Exception as exc:  # noqa: BLE001 - the packet must build regardless
        body["_narrationSource"] = f"could not be transcribed here: {type(exc).__name__}"
    return body


def _flat(text: object, limit: int = 240) -> str:
    flattened = " ".join(str(text).split())
    return flattened if len(flattened) <= limit else flattened[: limit - 1] + "…"


def event_line(event: dict[str, Any]) -> str:
    """One event, in the shape a sentence can be checked against.

    Role and accessible name rather than a selector: that is what the step text
    is supposed to be about, and a judge comparing prose to a CSS path is
    comparing the wrong two things.
    """
    target = event.get("target") or {}
    role = target.get("role") or ""
    name = target.get("name") or ""
    what = f'{role} "{name}"'.strip() if (role or name) else "(no named target)"

    bits = [f"`{event.get('id', '?')}`", f"{event.get('type', '?'):<9}", what]

    value = target.get("value")
    if value not in (None, "") and event.get("type") in {"input", "change", "select"}:
        bits.append(f'= "{_flat(value, 60)}"')

    for call in event.get("network") or []:
        status = call.get("status")
        # A 4xx or 5xx is very often what the test is ABOUT, so it is marked
        # rather than left for the judge to spot in a URL.
        marker = "!!" if isinstance(status, int) and status >= 400 else "->"
        bits.append(f"{marker} {status} {call.get('method', '')} {_flat(call.get('url', ''), 70)}")

    for entry in event.get("console") or []:
        if entry.get("level") in {"error", "warning"}:
            bits.append(f"[console {entry.get('level')}] {_flat(entry.get('text', ''), 90)}")

    fidelity = event.get("fidelity") or []
    if fidelity:
        codes = {str(f.get("code") or f) if isinstance(f, dict) else str(f) for f in fidelity}
        bits.append(f"({', '.join(sorted(codes))})")

    return "  ".join(b for b in bits if b)


def tester_voice(recording: dict[str, Any]) -> list[str]:
    """The three ways a tester speaks, all of which outrank the model.

    Objective, annotations and narration are SS6.7's optional inputs. When the
    output is poor and one of these is thin, the fault may be upstream of
    anything in `server/` -- and a judge that cannot see them blames the prompt
    every time.
    """
    out = [f"**Objective:** {recording.get('objective') or '*(none stated)*'}", ""]

    annotations = recording.get("annotations") or []
    if annotations:
        out += ["**What the tester marked:**", ""]
        for a in annotations:
            kind = a.get("kind") or a.get("type") or "?"
            anchor = a.get("eventId") or f"t={a.get('timestamp')}"
            text = _flat(a.get("text") or a.get("note") or "", 160)
            out.append(f"- `{kind}` at `{anchor}`{(' — ' + text) if text else ''}")
        out.append("")
    else:
        out += ["**What the tester marked:** nothing. No intent notes, no marked "
                "elements, no declared breaks.", ""]

    # `narration` is a LIST of segments on the recording, not a wrapper object.
    narration = recording.get("narration")
    segments = narration if isinstance(narration, list) else None
    source = recording.get("_narrationSource")
    if segments:
        if source:
            out += [f"*({source})*", ""]
        out += [f"**Narration:** {len(segments)} segment(s).", ""]
        for seg in segments[:12]:
            confidence = seg.get("confidence")
            note = f" *(confidence {confidence:.2f})*" if isinstance(confidence, float) else ""
            out.append(f"- {_flat(seg.get('text', ''), 160)}{note}")
        out.append("")
    elif source and "could not" in str(source):
        out += [f"**Narration:** unknown — {source}. Do not read this as silence.", ""]
    else:
        out += ["**Narration:** none.", ""]

    return out


def render_case(case: dict[str, Any], events: dict[str, dict[str, Any]]) -> list[str]:
    """A scenario, with each step's events and verdict directly beneath it.

    The layout is the argument. A step's sentence, the events it claims and the
    claim it reached are the three things that have to agree, so they are
    printed together with nothing between them.
    """
    heading = case.get("scenarioName") or case.get("title") or case.get("id")
    kind = case.get("kind") or "test"
    out = [f"### Scenario: {heading}" + (f"  *(kind: {kind})*" if kind != "test" else ""), ""]
    if case.get("tags"):
        out += [f"tags: {' '.join('@' + t for t in case['tags'])}", ""]

    for step in case.get("steps") or []:
        out.append(
            f"**{step.get('keyword', '?')} {step.get('text', '')}**  "
            f"`{step.get('id')}` role={step.get('role')}"
        )
        for event_id in step.get("eventIds") or []:
            event = events.get(event_id)
            line = event_line(event) if event else f"`{event_id}` *(not in recording)*"
            out.append(f"    {line}")
        for assertion in step.get("assertions") or []:
            mark = "Then" if assertion.get("accepted", True) else "REJECTED"
            evidence = assertion.get("evidence") or {}
            out.append(f"    **{mark}** {assertion.get('text', '')}")
            out.append(
                f'        evidence: "{_flat(evidence.get("literal", ""), 120)}"'
                f"  ({evidence.get('kind', '?')} via `{evidence.get('toolCallId', '?')}`"
                f" at `{evidence.get('eventId', '?')}`)"
                f"  provenance={assertion.get('provenance', '?')}"
            )
        out.append("")

    omitted = case.get("omitted") or []
    if omitted:
        out += ["**Omitted from this scenario, on purpose:**", ""]
        for entry in omitted:
            ids = ", ".join(f"`{e}`" for e in entry.get("eventIds") or [])
            out.append(f"- {entry.get('reason', '?')}: {entry.get('summary', '')} {ids}")
        out.append("")

    return out


def render_refused(run: Path) -> list[str]:
    """What the drafter proposed and binding refused.

    The half of the run the feature file cannot show, and usually where the
    diagnosis is: a good sentence refused by a rule is a different defect from
    a bad sentence nobody proposed a replacement for.
    """
    claims = (_load(run / "assertions.json") or {}).get("claims") or []
    refused = [c for c in claims if c.get("verdict") != "bind"]
    if not refused:
        return ["*Nothing was proposed and refused.*", ""]

    out = []
    for claim in refused:
        out.append(
            f"- **{claim.get('verdict')}** on `{claim.get('stepId')}`: {claim.get('text', '')}"
        )
        out.append(f"  - refused because: {_flat(claim.get('reason', ''), 300)}")
    out.append("")
    return out


def render_gate(run: Path) -> list[str]:
    trace = _load(run / "trace.json") or {}
    metrics = trace.get("metrics") or {}

    rejected, warned = [], []
    for entry in trace.get("validatorResults") or []:
        line = f"{entry.get('validator', '?')} — {_flat(entry.get('message', ''), 140)}"
        if entry.get("action") in {"reject", "hard_fail"}:
            rejected.append(f"- **{line}**")
        elif entry.get("action") == "warn":
            warned.append(f"- {line}")

    out = ["**Rejections:** " + ("none" if not rejected else ""), *rejected, ""]
    out += ["**Warnings:** " + ("none" if not warned else ""), *warned, ""]

    critic = _load(run / "critic.json") or {}
    findings = critic.get("findings") or []
    if critic.get("failed"):
        out.append(f"**Critic:** did not run — `{_flat(critic['failed'], 120)}`")
    elif findings:
        out += ["**Critic findings:**", ""]
        for finding in findings:
            out.append(
                f"- `{finding.get('kind', '?')}` on `{finding.get('stepId') or 'scenario'}` — "
                f"{_flat(finding.get('message') or finding.get('text', ''), 220)}"
            )
    else:
        out.append("**Critic:** ran, found nothing.")
    out.append("")

    # Grounding beside yield, always. A rate alone is vacuously 1.0 for a run
    # that claimed nothing, and this project has met that trap in five columns.
    out += ["| metric | value |", "|---|---|"]
    rows = [
        ("assertions accepted", metrics.get("assertionsTotal", "—")),
        ("grounding rate", metrics.get("groundingRate", "—")),
        ("validator pass (first)", metrics.get("validatorFirstPassRate", "—")),
        ("validator pass (final)", metrics.get("validatorFinalPassRate", "—")),
        (
            "critic findings raised / resolved",
            f"{metrics.get('criticFindingsRaised', '—')} / "
            f"{metrics.get('criticFindingsResolved', '—')}",
        ),
        ("repair attempts", metrics.get("repairAttempts", "—")),
        ("tool calls total", metrics.get("toolCallsTotal", "—")),
        ("tool calls per step", metrics.get("toolCallsPerStep") or {}),
    ]
    out += [f"| {label} | `{value}` |" for label, value in rows]
    out.append("")

    split = _load(run / "split.json") or {}
    if split:
        summary = {k: v for k, v in split.items() if k != "groups"}
        out += [f"**Splitter:** `{json.dumps(summary)}`", ""]
    return out


def packet(run: Path) -> str:
    ir = _load(run / "ir.json") or {}
    recording_id = ir.get("recordingId") or run.parent.name
    recording = find_recording(recording_id) or {}
    events = {e["id"]: e for e in recording.get("events") or []}

    cases = ir.get("testCases") or []
    claimed = {e for c in cases for s in c.get("steps") or [] for e in s.get("eventIds") or []}
    omitted = {
        e
        for c in cases
        for entry in c.get("omitted") or []
        for e in entry.get("eventIds") or []
    }
    unaccounted = [e for e in events if e not in claimed and e not in omitted]

    out = [
        f"# `{recording_id}` — judgement packet",
        "",
        f"Run: `{run.relative_to(REPO_ROOT).as_posix()}`  ·  "
        f"set: **{'held-out' if recording_id in HELD_OUT else 'dev'}**  ·  "
        f"{len(events)} recorded events  ·  {len(cases)} test case(s)",
        "",
        "---",
        "",
        "## 1 · What the tester said they were doing",
        "",
    ]
    out += tester_voice(recording)
    out += ["---", "", "## 2 · What came out", "", "```gherkin"]
    features = sorted(run.glob("*.feature"))
    out.append(
        "\n\n".join(f.read_text(encoding="utf-8").strip() for f in features)
        or "(no feature file was written)"
    )
    out += [
        "```",
        "",
        "---",
        "",
        "## 3 · Every step, beside the events it claims and the evidence it reached",
        "",
    ]
    for case in cases:
        out += render_case(case, events)

    if unaccounted:
        out += [
            f"**{len(unaccounted)} event(s) in the recording that no step claims and no "
            "omission names** — `event_coverage` should have caught this:",
            "",
        ]
        out += [f"    {event_line(events[e])}" for e in unaccounted]
        out.append("")

    out += ["---", "", "## 4 · Proposed and refused", ""]
    out += render_refused(run)
    out += ["---", "", "## 5 · What the gate said", ""]
    out += render_gate(run)
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, help="one run directory")
    parser.add_argument("--id", help="one recording id; its newest run is used")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--stdout", action="store_true", help="print instead of writing")
    args = parser.parse_args(argv)

    if args.run:
        runs = [args.run]
    else:
        runs = latest_runs(RUNS)
        if args.id:
            runs = [r for r in runs if r.parent.name == args.id]
    if not runs:
        print("No runs to build a packet from.", file=sys.stderr)
        return 1

    if not args.stdout:
        args.out.mkdir(parents=True, exist_ok=True)
    for run in runs:
        text = packet(run)
        if args.stdout:
            print(text)
            continue
        target = args.out / f"{run.parent.name}.md"
        target.write_text(text, encoding="utf-8")
        print(f"{run.parent.name}  ->  {target.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
