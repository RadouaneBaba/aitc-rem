"""What each fixture PRODUCED, not what it contains.

Seven fixtures exist, each built because a fixture that does not contain the
thing cannot demonstrate it. That argument has a second half nobody wrote down:
containing the thing is not the same as demonstrating it.

`twoflows` contains a declared scenario break and shipped ONE scenario, and no
test noticed -- every test of that path built an annotation with an `eventId`
the recorder never sets, so the suite was green on an input that cannot occur.
The recording held the feature; the output did not.

So each test here asserts on the run's OUTPUT: two scenarios, a step named from
the tester's note, an assertion ranked `narrated`, a bug report whose `actual`
is bound, an omission the pruning validator actually checked.

These replay from `runs/_cassettes/`, and skip when the tape for a fixture is
absent. A prompt change invalidates its own cassettes by construction -- the key
is the exact request -- so after any prompt edit these skip until the recordings
are run live again. That is honest: the alternative is a scripted model, and a
scripted model cannot tell you what the pipeline produces.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.cli import attach_narration
from server.config import load_project_config
from server.evidence.store import EvidenceStore
from server.llm.cassette import CassetteClient, CassetteMiss
from server.llm.gemini import DEFAULT_MODEL
from server.models import AblationConfig, Provenance, Recording
from server.pipeline.run import PipelineOptions, PipelineResult, run_pipeline
from server.renderers.base import test_cases as cases_of
from server.storage.paths import Storage

FIXTURES = Path(__file__).parent / "fixtures"
CASSETTES = Path(__file__).resolve().parents[1] / "runs" / "_cassettes"


class _Unreachable:
    """A provider that must never be consulted.

    `read_only` is what makes these tests offline, and a client underneath the
    cassette that could actually answer would turn a silent cassette miss into
    a live API call from the test suite.
    """

    name = "unreachable"

    def complete(self, request):  # pragma: no cover - the point is that it does not run
        raise AssertionError("a fixture outcome test reached a real provider")

    def embed(self, texts):  # pragma: no cover
        raise AssertionError("a fixture outcome test reached a real provider")


def run_fixture(name: str, tmp_path: Path) -> PipelineResult:
    """Replay one fixture, or skip if its tape is not on disk."""
    path = FIXTURES / f"{name}.recording.json"
    if not path.is_file():
        pytest.skip(f"{name} has not been recorded")
    if not CASSETTES.is_dir():
        pytest.skip("no cassettes; run the recordings live to record them")

    recording = Recording.model_validate(json.loads(path.read_text(encoding="utf-8")))
    config = load_project_config()

    # The same call the CLI makes, and it has to be the same call: the e2e suite
    # rewrites these fixtures with an empty `narration`, and the transcript
    # comes from the committed audio beside them at run time. A replay that
    # skipped it would build a different digest, miss every cassette, and skip
    # forever -- while looking like a prompt change.
    attach_narration(
        recording, path, transcript=None, offset_ms=0.0, project=config, quiet=True
    )
    storage = Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")
    model = CassetteClient(_Unreachable(), CASSETTES, mode="read_only")

    # A2 with bug mode on, matching what the recordings are run with -- the
    # cassette key is the exact request, so a different configuration is a
    # different tape and every one of these would skip forever.
    options = PipelineOptions.for_config(
        AblationConfig.A2,
        model_name=DEFAULT_MODEL,
        budget=8,
        project=config,
        bug_mode_enabled=True,
    )
    try:
        return run_pipeline(recording, model, storage=storage, run_id="run_001", options=options)
    except CassetteMiss:
        pytest.skip(f"no cassette for {name} at the current prompts; run it live to record one")


def scenario_names(result: PipelineResult) -> list[str]:
    return [case.scenarioName for case in cases_of(result.ir)]


def accepted(result: PipelineResult) -> list:
    return [
        assertion
        for case in cases_of(result.ir)
        for step in case.steps
        for assertion in step.assertions
        if assertion.accepted
    ]


# --------------------------------------------------------------------------


def test_twoflows_produces_two_test_cases(tmp_path):
    # The whole reason this fixture exists, and the thing it had never done.
    # SS6.7 says a declared break OVERRIDES the model, and override means
    # override: `digest.py` tells the drafter where the tester cut, and
    # `run._split_on_declared_breaks` is the net behind it.
    result = run_fixture("twoflows", tmp_path)

    names = scenario_names(result)
    assert len(names) >= 2, f"the declared break produced one scenario: {names}"
    # Two test cases sharing a name is one test case with a copy of itself.
    assert len(set(names)) == len(names), names


def test_annotated_takes_the_step_name_from_the_tester(tmp_path):
    # SS6.7 ranks the tester's own words above anything the pipeline infers,
    # and `critic._collect` and `repair.targets` both refuse to touch a step
    # named this way -- which is only meaningful if one exists.
    result = run_fixture("annotated", tmp_path)

    store = EvidenceStore(recording=result.recording)
    notes = [
        (a.text or "").strip().lower()
        for a in result.recording.annotations
        if a.kind.value == "intent_note" and a.text
    ]
    assert notes, "the annotated fixture carries no intent note any more"
    assert store  # the recording parsed

    texts = [step.text.lower() for case in cases_of(result.ir) for step in case.steps]
    assert any(
        any(word in text for word in note.split() if len(word) > 4)
        for note in notes
        for text in texts
    ), f"no step reflects the tester's note {notes}: {texts}"


def test_narrated_reaches_the_narrated_rank(tmp_path):
    # The clearest result this project has: narration decides WHICH outcome
    # matters and the evidence stays exact, so `Yield` rises without
    # `grounding_rate` moving. A run where nothing reaches `narrated` has not
    # demonstrated that.
    result = run_fixture("narrated", tmp_path)

    claims = accepted(result)
    assert claims, "the narrated fixture produced no accepted expected result"
    assert any(a.provenance == Provenance.narrated for a in claims), [
        a.provenance.value for a in claims
    ]

    # And the evidence is still a snapshot literal, not the transcript.
    for claim in claims:
        if claim.provenance == Provenance.narrated:
            assert claim.evidence and claim.evidence.toolCallId


def test_bugged_writes_a_report_whose_actual_is_bound(tmp_path):
    # SS14.2. The `actual` is the one sentence a developer reads before
    # deciding whether to go and reproduce something, and it is yielded into
    # `_assertions` in `grounding.py` rather than checked by a branch of its
    # own -- a second implementation of evidence binding is a second thing that
    # can be wrong.
    result = run_fixture("bugged", tmp_path)

    reports = [case for case in result.ir.testCases if case.kind == "bug_report"]
    assert reports, "the bugged fixture produced no bug report"

    report = reports[0].bug
    assert report is not None
    assert report.actual, "the report says nothing about what happened"
    assert report.actualEvidence is not None, "the actual is unbound"
    assert report.actualEvidence.toolCallId and report.actualEvidence.literal


def test_wander_omits_the_wrong_turn_and_the_validator_checks_it(tmp_path):
    # `no_pruned_assertion` had never run: it read a `segmentId` that
    # decomposition stopped writing, so it skipped on every recording in the
    # repo. An omission with nothing checking it is a comment.
    result = run_fixture("wander", tmp_path)

    omitted = [o for case in result.ir.testCases for o in case.omitted]
    assert omitted, "nothing was pruned from the wander fixture"
    assert all(o.eventIds for o in omitted), "an omission that names no event"

    rows = [r for r in result.report.results if r.validator.value == "no_pruned_assertion"]
    assert rows, "the validator did not run at all"
    assert rows[-1].status.value != "skipped", rows[-1].message


def test_every_fixture_run_accounts_for_every_event(tmp_path):
    # The net under the drafter's freedom. It reads the IR rather than the
    # rendered file, which is how `lift_background` deleted steps from the
    # feature while this stayed green -- so it is necessary and not sufficient.
    for name in ("checkout", "hardpaths", "twoflows", "wander"):
        result = run_fixture(name, tmp_path / name)
        rows = [r for r in result.report.results if r.validator.value == "event_coverage"]
        assert rows and rows[-1].status.value == "pass", (name, rows[-1].message if rows else "")
