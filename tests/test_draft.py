"""The one author (SS9.3).

`draft.py` is the whole of the model's contribution to a run -- the feature
name, the scenario names, where one step ends and the next begins, the keyword,
the role, and the sentence of every expected result. It replaced three stages
that never saw each other's work, and until now it had no test of its own:
`draft_document` is not named in any other module, and everything here was
covered only end to end through `test_pipeline.py`, where a cassette decides
what the model says and a parsing bug reads as a bad answer.

What is worth pinning is not "does the model write well". It is the defence
around the model: a drafting stage that raises takes the whole run with it and
there is no second author to fall back to, so every field is defended and the
degraded path is a real output rather than an exception.
"""

from __future__ import annotations

import json

from server.config import ProjectConfig
from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm import ScriptedModelClient, answer
from server.models import Confidence, OmissionReason, PipelineStage, SegmentRole
from server.pipeline.draft import (
    _clean,
    _fallback,
    _parse,
    _reconcile,
    _scenarios,
    draft_document,
    rewrite_steps,
    with_subject,
)
from server.storage.paths import Storage
from tests import factories as f


def store_of(count: int = 4) -> EvidenceStore:
    events = [f.event(f"evt_{i:03d}", seq=i - 1, at=float(i * 1000)) for i in range(1, count + 1)]
    return EvidenceStore(recording=f.recording(events=events, objective="Place an order"))


def runner_for(store: EvidenceStore, tmp_path) -> ToolRunner:
    storage = Storage(recordings_dir=tmp_path / "rec", runs_dir=tmp_path / "runs")
    return ToolRunner(store=store, storage=storage, run=storage.run(store.recording.id, "run_001"))


def a_document(**over) -> dict:
    body = {
        "title": "Ordering",
        "description": "",
        "tags": ["checkout"],
        "scenarios": [
            {
                "name": "An order over the limit is held",
                "steps": [
                    {
                        "keyword": "Given",
                        "role": "setup",
                        "text": "signs in",
                        "eventIds": ["evt_001"],
                    },
                    {
                        "keyword": "When",
                        "role": "test_step",
                        "text": "submits the order",
                        "eventIds": ["evt_002"],
                        "expect": [{"text": "the order is held", "eventId": "evt_002"}],
                    },
                ],
            }
        ],
        "omitted": [],
    }
    body.update(over)
    return body


# --------------------------------------------------------------------------
# ids, and the rule that makes the splitter safe
# --------------------------------------------------------------------------


def test_step_ids_are_minted_across_the_whole_document_not_per_scenario():
    # `split.py` repartitions scenarios and keeps `step_id` untouched by
    # construction -- which only holds because the counter is document-global.
    # A per-scenario counter would make two steps called `step_001`, and every
    # review edit searches the IR by id.
    parsed = _scenarios(
        [
            {"name": "a", "steps": [{"text": "one", "eventIds": ["evt_001"]}]},
            {
                "name": "b",
                "steps": [
                    {"text": "two", "eventIds": ["evt_002"]},
                    {"text": "three", "eventIds": ["evt_003"]},
                ],
            },
        ],
        known={"evt_001", "evt_002", "evt_003"},
        config=ProjectConfig(),
    )

    ids = [step.step_id for scenario in parsed for step in scenario.steps]
    assert ids == ["step_001", "step_002", "step_003"]


def test_an_event_claimed_twice_goes_to_the_first_step_that_claimed_it():
    # `event_coverage` counts rather than unions now, so a duplicate is a
    # rejection. First-claim-wins is deterministic; last-claim-wins would let
    # the later step silently overwrite the earlier one's evidence.
    parsed = _scenarios(
        [
            {
                "name": "a",
                "steps": [
                    {"text": "one", "eventIds": ["evt_001", "evt_002"]},
                    {"text": "two", "eventIds": ["evt_002", "evt_003"]},
                ],
            }
        ],
        known={"evt_001", "evt_002", "evt_003"},
        config=ProjectConfig(),
    )

    assert [s.event_ids for s in parsed[0].steps] == [["evt_001", "evt_002"], ["evt_003"]]


def test_a_step_left_with_no_events_is_dropped_rather_than_rendered_empty():
    # Every event of this step was already claimed. A step with no events
    # cannot be replayed, cannot be bound, and has nothing to show a reviewer.
    parsed = _scenarios(
        [
            {
                "name": "a",
                "steps": [
                    {"text": "one", "eventIds": ["evt_001"]},
                    {"text": "again", "eventIds": ["evt_001"]},
                ],
            }
        ],
        known={"evt_001"},
        config=ProjectConfig(),
    )
    assert [s.text for s in parsed[0].steps] == ["the tester one"]


def test_an_event_the_recording_does_not_contain_is_not_admitted():
    parsed = _scenarios(
        [{"name": "a", "steps": [{"text": "one", "eventIds": ["evt_001", "evt_404"]}]}],
        known={"evt_001"},
        config=ProjectConfig(),
    )
    assert parsed[0].steps[0].event_ids == ["evt_001"]


def test_an_expectation_pointing_at_no_event_is_dropped_not_fatal():
    # Proportionate failure: `element_exists` would reject the whole draft, and
    # what went wrong is one field of one claim.
    parsed = _scenarios(
        [
            {
                "name": "a",
                "steps": [
                    {
                        "text": "one",
                        "eventIds": ["evt_001"],
                        "expect": [
                            {"text": "kept", "eventId": "evt_001"},
                            {"text": "dropped", "eventId": "evt_404"},
                            {"text": "", "eventId": "evt_001"},
                        ],
                    }
                ],
            }
        ],
        known={"evt_001"},
        config=ProjectConfig(),
    )
    assert [e.text for e in parsed[0].steps[0].expects] == ["kept"]


# --------------------------------------------------------------------------
# keyword and role, which are two spellings of one judgement
# --------------------------------------------------------------------------


def test_a_given_is_taken_as_a_statement_that_the_step_is_setup():
    # `narrative._base_keyword` derives from the ROLE, so a `Given` whose role
    # said `test_step` would be silently dropped -- the drafter asked for a
    # keyword and got the opposite of it.
    assert _reconcile("Given", "test_step") == ("Given", SegmentRole.setup)


def test_the_reverse_is_deliberately_not_applied():
    # A `When` on a step also called setup is resolved by POSITION:
    # `narrative._opening_block` demotes a setup step that appears after the
    # scenario has begun acting, and that rule is about where the step sits --
    # which the drafter cannot see when writing one line of JSON.
    assert _reconcile("When", "setup") == ("When", SegmentRole.setup)


def test_then_is_normalised_away_because_an_outcome_is_not_a_step():
    # A model that writes an expected result as a step is describing an outcome
    # as an action; rendering it verbatim asserts before the scenario acts.
    assert _reconcile("Then", "test_step") == ("When", SegmentRole.test_step)
    assert _reconcile("Then", "setup") == ("Given", SegmentRole.setup)


def test_a_missing_keyword_falls_out_of_the_role():
    assert _reconcile(None, "setup") == ("Given", SegmentRole.setup)
    assert _reconcile("", "teardown") == ("When", SegmentRole.teardown)


# --------------------------------------------------------------------------
# the deterministic nets on the sentence
# --------------------------------------------------------------------------


def test_a_step_with_no_subject_gets_one():
    # The naming prompt said twice to start with the subject and its worked
    # examples were written without one, so the model copied the examples:
    # "submits an order totalling \"615\"", nobody submitting anything.
    config = ProjectConfig()
    assert with_subject("submits the order", config) == "the tester submits the order"


def test_a_sentence_that_already_names_someone_is_left_alone():
    # "the approver releases the order" must not become "the tester the
    # approver releases the order".
    config = ProjectConfig()
    for text in ("the approver releases the order", "an admin approves it", "the tester signs in"):
        assert with_subject(text, config) == text


def test_first_person_projects_keep_their_own_voice():
    assert with_subject("submit the order", ProjectConfig(voice="I")) == "submit the order"


def test_a_trailing_full_stop_is_stripped_because_a_step_is_a_fragment():
    assert _clean("  the tester   signs  in.  ") == "the tester signs in"


def test_an_ellipsis_is_content_and_survives():
    # "Validating with the finance system..." is what the page said, and
    # trimming it breaks the literal a claim is bound to.
    assert (
        _clean("Validating with the finance system...") == "Validating with the finance system..."
    )


# --------------------------------------------------------------------------
# the fallback -- a transcript, deliberately, and never a guess
# --------------------------------------------------------------------------


def test_a_malformed_answer_produces_a_readable_document_rather_than_an_exception():
    # There is no second author. A drafting stage that raises takes the run.
    store = store_of(3)
    result = _parse({"scenarios": "not a list"}, store, ProjectConfig())

    assert result.degraded
    assert len(result.steps) == 3
    assert [s.event_ids for s in result.steps] == [["evt_001"], ["evt_002"], ["evt_003"]]


def test_the_fallback_makes_no_claims_at_all():
    # A fallback that GUESSED at structure would be indistinguishable from a
    # real draft in the output while being worth much less.
    result = _fallback(store_of(3), ProjectConfig(), why="the model failed")

    assert all(step.expects == [] for step in result.steps)
    assert result.confidence == Confidence.low
    assert result.degraded == "the model failed"


def test_the_fallback_still_opens_on_a_given():
    result = _fallback(store_of(3), ProjectConfig(), why="x")
    assert [s.keyword for s in result.steps] == ["Given", "When", "When"]
    assert result.steps[0].role == SegmentRole.setup


def test_a_run_with_no_events_degrades_without_inventing_a_scenario():
    store = EvidenceStore(recording=f.recording(events=[]))
    result = _fallback(store, ProjectConfig(), why="x")
    assert result.scenarios == []


# --------------------------------------------------------------------------
# omissions -- the other half of `event_coverage`
# --------------------------------------------------------------------------


def test_an_omission_names_the_events_it_drops_and_defaults_to_exploratory():
    # `event_coverage` accepts an event only in a step or in an explicit
    # omission naming it, which is what makes the drafter's freedom safe.
    result = _parse(
        a_document(
            omitted=[
                {"eventIds": ["evt_003"], "reason": "abandoned", "summary": "a typo, corrected"},
                {"eventIds": ["evt_004"], "summary": "looked at the help page"},
                {"eventIds": ["evt_404"], "summary": "never happened"},
            ]
        ),
        store_of(4),
        ProjectConfig(),
    )

    assert [o.event_ids for o in result.omitted] == [["evt_003"], ["evt_004"]]
    assert [o.reason for o in result.omitted] == [
        OmissionReason.abandoned,
        OmissionReason.exploratory,
    ]


# --------------------------------------------------------------------------
# the stage end to end, with a scripted answer
# --------------------------------------------------------------------------


def test_the_stage_records_its_own_investigation_under_decompose(tmp_path):
    store = store_of(2)
    model = ScriptedModelClient([answer(json.dumps(a_document()))])

    result = draft_document(
        store, runner_for(store, tmp_path), model, model_name="scripted-1", budget=8
    )

    assert result.title == "Ordering"
    assert [s.step_id for s in result.steps] == ["step_001", "step_002"]
    assert result.investigation is not None
    assert result.investigation.stage == PipelineStage.decompose
    assert result.investigation.budgetMax == 8
    # The session index is what the author reads, and its size is the one
    # number that says whether the whole session fits in one call.
    assert result.digest is not None and result.digest.approx_tokens > 0


def test_a0_hands_the_drafter_no_budget_at_all(tmp_path):
    # `tools_enabled` is the A0 switch, pinned elsewhere by
    # `test_a0_makes_no_retrieval_of_any_kind`. A budget of 8 with the tools
    # off would spend turns being refused.
    store = store_of(2)
    model = ScriptedModelClient([answer(json.dumps(a_document()))])

    result = draft_document(
        store,
        runner_for(store, tmp_path),
        model,
        model_name="scripted-1",
        budget=8,
        tools_enabled=False,
    )

    assert result.investigation is not None
    assert result.investigation.budgetUsed == 0


# --------------------------------------------------------------------------
# rewriting, which is the only path that edits a step's text after drafting
# --------------------------------------------------------------------------


def rewrite(tmp_path, texts: list[str], *, target: str, into: str) -> tuple:
    store = store_of(len(texts))
    document = _parse(
        a_document(
            scenarios=[
                {
                    "name": "s",
                    "steps": [
                        {"text": t, "eventIds": [f"evt_{i:03d}"]}
                        for i, t in enumerate(texts, start=1)
                    ],
                }
            ]
        ),
        store,
        ProjectConfig(),
    )
    model = ScriptedModelClient([answer(json.dumps({"text": into}))])
    changed = rewrite_steps(
        store,
        runner_for(store, tmp_path),
        model,
        document,
        findings={target: "this step is too vague"},
        model_name="scripted-1",
        budget=0,
        tools_enabled=False,
        temperature=0.0,
        config=ProjectConfig(),
        attempt=1,
    )
    return document, changed


def test_a_rewrite_changes_the_sentence_and_nothing_else(tmp_path):
    # Never `eventIds`, never `step_id`. That one constraint is what keeps
    # `event_coverage` and the scenario grouping stable across attempts.
    document, changed = rewrite(
        tmp_path,
        ["the tester signs in", "the tester does something"],
        target="step_002",
        into="the tester submits an order over the approval limit",
    )

    assert changed == {"step_002"}
    step = document.steps[1]
    assert step.text == "the tester submits an order over the approval limit"
    assert step.step_id == "step_002" and step.event_ids == ["evt_002"]


def test_a_rewrite_that_would_delete_a_step_is_refused(tmp_path):
    # `merge_repeats` folds adjacent steps whose normalised text matches, so a
    # repair prompted with "too vague" can produce its neighbour's sentence and
    # DELETE a step -- changing the step count mid-run, which SS3.6 promises
    # does not happen, and moving Yield's denominator, which is worse because
    # the metric then improves by losing a step.
    document, changed = rewrite(
        tmp_path,
        ["the tester adds an item", "the tester adds another item"],
        target="step_002",
        into="the tester adds an item",
    )

    assert changed == set()
    assert document.steps[1].text == "the tester adds another item"


def test_a_rewrite_that_drops_a_redaction_placeholder_is_refused(tmp_path):
    # The placeholders are the test's parameters (SS7.2) -- the one thing
    # telling a reader what to supply before running it. This is the only path
    # that rewrites a step's text after they were put in it.
    document, changed = rewrite(
        tmp_path,
        ["the tester signs in as <<user_email_1>>"],
        target="step_001",
        into="the tester signs in",
    )

    assert changed == set()
    assert document.steps[0].text == "the tester signs in as <<user_email_1>>"


def test_a_rewrite_for_a_step_that_no_longer_exists_is_skipped(tmp_path):
    document, changed = rewrite(
        tmp_path, ["the tester signs in"], target="step_099", into="anything"
    )
    assert changed == set()
    assert document.steps[0].text == "the tester signs in"
