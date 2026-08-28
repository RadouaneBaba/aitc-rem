"""The replay, end to end, through the real driver and a real browser.

`tests/test_runners.py` covers the deterministic half -- turning a finished test
case into instructions. This is the other half, and until it was written the
other half had **never run**: `scripts/replay.mjs` had zero tests, `_run` never
spawned a subprocess in the suite, and every `executionRate` in the repository
was `0.0` while reading as a measurement rather than as an absence.

What it exercises that nothing else does: `build_job` -> `node replay.mjs` ->
`locate` -> `act` -> `check` -> `parse_result`. In particular the serialised
role selector, which crosses a language boundary --
`getByRole('checkbox', { name: "In stock" })` is written by
`extension/src/content/selectors.ts` and parsed by a regex in the driver, and
nothing else in the suite reads both sides.

Skips when the demo app is not listening or node is absent, the same bargain
`test_fixture_outcomes.py` makes with a stale cassette. Run it with:

    pnpm demo
    .venv/Scripts/python -m pytest tests/test_replay_live.py
"""

from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from server.models import Recording
from server.runners import replay_all
from tests import factories as f

FIXTURES = Path(__file__).parent / "fixtures"
DEMO = "http://localhost:5173"

#: The storefront's results count, which the keyhole fixture exists to make
#: reachable. It sits OUTSIDE the filter widget's landmark, so under the old
#: scoped capture it was never recorded at all -- see `Storefront.tsx`.
NINE_OF_24 = "Showing 9 of 24 products"


def _demo_is_up() -> bool:
    try:
        with urllib.request.urlopen(f"{DEMO}/storefront", timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


needs_demo = pytest.mark.skipif(
    not _demo_is_up() or shutil.which("node") is None,
    reason="needs the demo app on :5173 (`pnpm demo`) and node on PATH",
)


def _keyhole() -> Recording:
    body = json.loads((FIXTURES / "keyhole.recording.json").read_text(encoding="utf-8"))
    return Recording.model_validate(body)


@needs_demo
def test_a_generated_test_case_runs_against_the_live_application(tmp_path: Path):
    """The strongest check in the system, and the only one nobody can argue with.

    Every other column says a claim can point at the retrieval that produced
    it. This one says the test runs, and that the thing it asserts is still
    true of the application.

    The literal is the one the rebuild made reachable. Break the storefront's
    filter and this fails, which is `evals/RUBRIC.md`'s first check applied to
    the runner rather than to the prose.
    """
    recording = _keyhole()
    step = f.step(
        "step_001",
        "the tester filters the product list to in-stock items",
        assertions=[f.assertion(ev=f.evidence(literal=NINE_OF_24, event_id="evt_001"))],
    )
    step.eventIds = ["evt_001"]
    case = f.test_case(steps=[step], recording_id=recording.id)

    results = replay_all(
        f.ir_document(test_cases=[case]),
        recording=recording,
        out_dir=tmp_path,
        base_url=DEMO,
    )

    outcome = results[0]
    assert outcome.blocked is None, outcome.blocked
    assert outcome.ran
    assert outcome.passed
    # Beside the verdict, always. `passed` alone is the vacuous half.
    assert outcome.assertions_checked == 1
    assert outcome.assertions_held == 1
    # 0 means the most stable selector that exists resolved. The demo app has no
    # `data-testid`, so this is the role+name path -- the normal case for an
    # application nobody built for testing.
    assert outcome.mean_selector_rank == 0.0


@needs_demo
def test_a_false_expected_result_fails_rather_than_being_reported_green(tmp_path: Path):
    """The negative case, without which the test above proves nothing.

    A replay that answered `pass` for everything would satisfy the assertions
    above exactly as well. This is also the shape of the defect the first real
    replay found: an assertion bound to a moment where the literal could not yet
    exist, which every validator passed.
    """
    recording = _keyhole()
    step = f.step(
        "step_001",
        "the tester filters the product list to in-stock items",
        assertions=[
            f.assertion(
                ev=f.evidence(literal="Showing 1 of 24 products", event_id="evt_001")
            )
        ],
    )
    step.eventIds = ["evt_001"]
    case = f.test_case(steps=[step], recording_id=recording.id)

    results = replay_all(
        f.ir_document(test_cases=[case]),
        recording=recording,
        out_dir=tmp_path,
        base_url=DEMO,
    )

    outcome = results[0]
    assert outcome.ran
    assert not outcome.passed
    assert outcome.assertions_checked == 1
    assert outcome.assertions_held == 0


@needs_demo
def test_a_missing_parameter_blocks_the_replay_instead_of_failing_it(tmp_path: Path):
    """"Could not run" is not evidence about the test case.

    A redacted password is a `<<placeholder>>` by design (SS7.2), and a replay
    nobody supplied a value for has learned nothing about whether the test
    works. Scoring it as a failure would make `executionRate` measure the
    harness -- which is the same vacuity trap as scoring it as a pass, in the
    other direction.
    """
    recording = f.recording(
        events=[
            f.event(
                "evt_001",
                0,
                etype="input",
                url=f"{DEMO}/",
                tgt=f.target("textbox", "Password", css="#password"),
            )
        ]
    )
    recording.events[0].target.value = "<<password>>"
    recording.metadata.startUrl = f"{DEMO}/"
    step = f.step("step_001", "the tester enters a password", assertions=[])
    step.eventIds = ["evt_001"]

    results = replay_all(
        f.ir_document(test_cases=[f.test_case(steps=[step], recording_id=recording.id)]),
        recording=recording,
        out_dir=tmp_path,
        base_url=DEMO,
    )

    outcome = results[0]
    assert not outcome.ran
    assert not outcome.passed
    assert outcome.blocked and "password" in outcome.blocked
