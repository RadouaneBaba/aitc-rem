"""Gherkin narrative layout (`server/pipeline/narrative.py`).

Given/When/Then is a property of a scenario, not of a step, and the Phase 1
output proved the point the hard way: the naming stage was asked for a keyword
while looking at one segment, and answered `When` seven times running.

So the model supplies the role and this module supplies the keyword. These
tests are about the second half -- that a correct set of roles always produces
a scenario a human would have written, with no model in the loop.
"""

from __future__ import annotations

from server.models import Confidence
from server.pipeline.narrative import (
    apply_merges,
    build_narrative,
    keyword_for_role,
    merge_repeats,
    sync_keywords,
)
from tests import factories as f


def step(ident: str, text: str, role: str, *, assertions=None, **kw):
    return f.step(ident, text, role=role, assertions=assertions or [], **kw)


def keywords(narrative) -> list[str]:
    return [line.keyword for line in narrative.body]


# --------------------------------------------------------------------------
# keywords follow from roles
# --------------------------------------------------------------------------


def test_setup_is_given_and_the_tested_behaviour_is_when():
    narrative = build_narrative(
        [
            step("s1", "the tester signs in", "setup"),
            step("s2", "the tester adds a widget", "test_step"),
        ]
    )
    assert keywords(narrative) == ["Given", "When"]


def test_a_run_of_one_keyword_collapses_into_and():
    narrative = build_narrative(
        [
            step("s1", "the tester signs in", "setup"),
            step("s2", "the tester selects the EUR region", "setup"),
            step("s3", "the tester adds a widget", "test_step"),
            step("s4", "the tester goes to checkout", "test_step"),
        ]
    )
    assert keywords(narrative) == ["Given", "And", "When", "And"]


def test_and_never_opens_a_scenario():
    # `And` continues a block. Opening with it means continuing nothing, which
    # parses and reads as a fragment.
    narrative = build_narrative([step("s1", "the tester signs in", "setup")])
    assert keywords(narrative)[0] != "And"


def test_an_expected_result_lands_under_the_step_that_produced_it():
    narrative = build_narrative(
        [
            step("s1", "the tester adds a widget", "test_step"),
            step("s2", "the tester places the order", "test_step", assertions=[f.assertion()]),
        ]
    )
    assert keywords(narrative) == ["When", "And", "Then"]
    assert narrative.body[-1].is_assertion


def test_two_expected_results_on_one_step_read_as_then_and():
    narrative = build_narrative(
        [
            step(
                "s1",
                "the tester places the order",
                "test_step",
                assertions=[
                    f.assertion("asrt_001", "the confirmation banner appears"),
                    f.assertion("asrt_002", "the order reference is shown"),
                ],
            )
        ]
    )
    assert keywords(narrative) == ["When", "Then", "And"]


def test_an_action_after_an_expected_result_opens_a_new_beat():
    # Otherwise the second action reads as more of the first block, when what
    # actually happened is "and then the tester did this".
    narrative = build_narrative(
        [
            step("s1", "the tester places the order", "test_step", assertions=[f.assertion()]),
            step("s2", "the tester confirms approval", "test_step"),
            step("s3", "the tester places the order again", "test_step"),
        ]
    )
    assert keywords(narrative) == ["When", "Then", "When", "And"]
    assert narrative.beats == 2


def test_a_rejected_assertion_is_not_laid_out():
    assertion = f.assertion()
    assertion.accepted = False
    narrative = build_narrative(
        [step("s1", "the tester places the order", "test_step", assertions=[assertion])]
    )
    assert keywords(narrative) == ["When"]
    assert not narrative.has_expected_result


def test_a_step_with_no_role_falls_back_to_its_own_keyword():
    # Composition can fail; the run must still produce something readable
    # rather than a scenario of undifferentiated `When`.
    plain = f.step("s1", "the tester signs in", keyword="Given", assertions=[])
    assert keywords(build_narrative([plain])) == ["Given"]


def test_role_to_keyword_is_a_pure_mapping():
    assert keyword_for_role(None) == "When"
    for role in ("test_step", "teardown", "exploratory", "abandoned"):
        assert keyword_for_role(f.step("s", "t", role=role, assertions=[]).role) == "When"


# --------------------------------------------------------------------------
# merging repeats
# --------------------------------------------------------------------------


def test_adjacent_steps_saying_the_same_thing_merge():
    # The segmenter cuts on evidence of a boundary, not on a change of intent,
    # so one intent regularly spans two segments. Named in isolation both come
    # back identical, and the reader watches the tool stutter.
    merged = merge_repeats(
        [
            step("s1", "the tester signs in to the application", "setup", event_ids=["evt_001"]),
            step("s2", "the tester signs in to the application", "setup", event_ids=["evt_002"]),
        ]
    )
    assert len(merged) == 1
    # Nothing is lost: `event_coverage` still has every event to account for.
    assert merged[0].eventIds == ["evt_001", "evt_002"]


def test_merging_keeps_the_least_certain_confidence_and_every_assertion():
    merged = merge_repeats(
        [
            step(
                "s1",
                "the tester places the order",
                "test_step",
                assertions=[f.assertion("asrt_001", "the banner appears")],
                confidence="high",
            ),
            step(
                "s2",
                "the tester places the order.",
                "test_step",
                assertions=[f.assertion("asrt_002", "the reference is shown")],
                confidence="low",
            ),
        ]
    )
    assert len(merged) == 1
    assert merged[0].confidence == Confidence.low
    assert len(merged[0].assertions) == 2


def test_only_an_exact_repeat_merges():
    # Two steps that merely resemble each other are two steps. Merging on
    # similarity would silently delete work the tester actually did.
    merged = merge_repeats(
        [
            step("s1", "the tester places the order", "test_step"),
            step("s2", "the tester places the order again", "test_step"),
        ]
    )
    assert len(merged) == 2


def test_a_repeat_that_is_not_adjacent_is_left_alone():
    merged = merge_repeats(
        [
            step("s1", "the tester places the order", "test_step"),
            step("s2", "the tester confirms approval", "test_step"),
            step("s3", "the tester places the order", "test_step"),
        ]
    )
    assert len(merged) == 3


# --------------------------------------------------------------------------
# background
# --------------------------------------------------------------------------


def test_leading_setup_lifts_into_a_background_when_asked():
    narrative = build_narrative(
        [
            step("s1", "the tester signs in", "setup"),
            step("s2", "the tester adds a widget", "test_step"),
        ],
        lift_background=True,
    )
    assert [line.keyword for line in narrative.background] == ["Given"]
    assert keywords(narrative) == ["When"]


def test_an_all_setup_scenario_keeps_its_steps():
    # Lifting every step would leave an empty Scenario, which parses and says
    # nothing.
    narrative = build_narrative(
        [
            step("s1", "the tester signs in", "setup"),
            step("s2", "the tester opens the settings page", "setup"),
        ],
        lift_background=True,
    )
    assert narrative.background == []
    assert keywords(narrative) == ["Given", "And"]


# --------------------------------------------------------------------------
# merges composition asked for
# --------------------------------------------------------------------------


def test_composition_can_fold_two_segments_into_one_intent():
    # Typing a password and pressing Sign in are two segments and one thing the
    # tester was doing. Named in isolation they come back as two sentences
    # about signing in, and `merge_repeats` cannot help because they are not
    # word-for-word identical.
    merged = apply_merges(
        [
            step("s1", 'the tester signs in as "<<user_email_1>>"', "setup", event_ids=["evt_001"]),
            step("s2", "the tester signs in to the application", "setup", event_ids=["evt_003"]),
            step("s3", "the tester adds a widget", "test_step", event_ids=["evt_004"]),
        ],
        [["s1", "s2"]],
        texts={"s1": 'the tester signs in as "<<user_email_1>>"'},
    )

    assert [s.text for s in merged] == [
        'the tester signs in as "<<user_email_1>>"',
        "the tester adds a widget",
    ]
    assert merged[0].eventIds == ["evt_001", "evt_003"]


def test_a_merge_across_a_gap_is_refused():
    # Merging step 1 with step 3 would silently delete step 2, which is a much
    # worse outcome than a scenario that reads slightly long.
    steps = [
        step("s1", "the tester signs in", "setup"),
        step("s2", "the tester opens the reports page", "test_step"),
        step("s3", "the tester signs in again", "setup"),
    ]
    assert len(apply_merges(steps, [["s1", "s3"]])) == 3


def test_a_merge_naming_an_unknown_step_changes_nothing():
    steps = [step("s1", "the tester signs in", "setup")]
    assert len(apply_merges(steps, [["s1", "s99"]])) == 1


def test_layout_does_not_merge_on_its_own():
    # `ir.json` and the rendered feature must show the same steps. A renderer
    # that quietly collapsed two of them would make the artifact disagree with
    # the record the validators read.
    steps = [
        step("s1", "the tester signs in", "setup"),
        step("s2", "the tester signs in", "setup"),
    ]
    assert len(build_narrative(steps).body) == 2


def test_a_merged_sentence_may_not_drop_a_test_parameter():
    # SS7.2 -- redaction placeholders carry forward as the test's parameters,
    # and they are the only thing telling whoever runs it what to supply. A
    # tidier summary that loses them is worse than the two steps it replaced,
    # so the more specific original wins.
    merged = apply_merges(
        [
            step("s1", 'the tester signs in as "<<user_email_1>>"', "setup"),
            step("s2", "the tester signs in to the application", "setup"),
        ],
        [["s1", "s2"]],
        texts={"s1": "the tester signs in to the application"},
    )
    assert merged[0].text == 'the tester signs in as "<<user_email_1>>"'


def test_a_merged_sentence_that_keeps_the_parameters_is_used():
    merged = apply_merges(
        [
            step("s1", 'the tester enters "<<user_email_1>>"', "setup"),
            step("s2", 'the tester enters "<<password>>"', "setup"),
        ],
        [["s1", "s2"]],
        texts={"s1": 'the tester signs in as "<<user_email_1>>" with "<<password>>"'},
    )
    assert merged[0].text == 'the tester signs in as "<<user_email_1>>" with "<<password>>"'


def test_given_belongs_to_the_opening_block_and_nowhere_else():
    # Composition can legitimately call a later step `setup` -- going to the
    # checkout page is setup for what follows it -- but Given/When/Then in that
    # order is not how anyone writes Gherkin, and it reads as the scenario
    # restarting halfway down.
    narrative = build_narrative(
        [
            step("s1", "the tester signs in", "setup"),
            step("s2", "the tester adds a widget", "test_step", assertions=[f.assertion()]),
            step("s3", "the tester goes to checkout", "setup"),
            step("s4", "the tester places the order", "test_step"),
        ]
    )
    assert keywords(narrative) == ["Given", "When", "Then", "When", "And"]


def test_an_expected_result_ends_the_preconditions():
    # Once the scenario has checked something, nothing after it is describing
    # the world beforehand -- even if the step that follows really is setup.
    narrative = build_narrative(
        [
            step("s1", "the tester signs in", "setup", assertions=[f.assertion()]),
            step("s2", "the tester opens the settings page", "setup"),
        ]
    )
    assert keywords(narrative) == ["Given", "Then", "When"]


def test_the_ir_keyword_matches_what_the_step_will_render_as():
    # `Step.keyword` is a denormalisation of role plus position. A reviewer who
    # sees `Given` in the UI while the feature file says `And` has been shown
    # two versions of the same step, so both come from `build_narrative`.
    steps = [
        step("s1", "the tester signs in", "setup"),
        step("s2", "the tester selects the EUR region", "setup"),
        step("s3", "the tester adds a widget", "test_step"),
    ]
    sync_keywords(steps)

    assert [s.keyword.value for s in steps] == ["Given", "And", "When"]
    assert [s.keyword.value for s in steps] == [line.keyword for line in build_narrative(steps).body]


def test_removing_a_step_repairs_the_keyword_of_the_one_after_it():
    # Deleting the head of an `And` block promotes the next step, and a stale
    # `And` would open a block that continues nothing.
    steps = [
        step("s1", "the tester signs in", "setup"),
        step("s2", "the tester adds a widget", "test_step"),
        step("s3", "the tester goes to checkout", "test_step"),
    ]
    sync_keywords(steps)
    assert steps[2].keyword.value == "And"

    remaining = [steps[0], steps[2]]
    sync_keywords(remaining)
    assert remaining[1].keyword.value == "When"
