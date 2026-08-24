"""The `gherkin_style` validator (SS11.1).

`gherkin_parses` proves the output is Gherkin. It said nothing about whether the
output was a test case, and for a long time it did not have to: the Phase 1
files parsed perfectly while reading as a click log with keywords on them.

These findings are warnings, never rejections -- style is not correctness, and
refusing to emit a grounded test case over a verb would trade the valuable
thing for the cheap one. What they buy is that none of it can regress quietly.
"""

from __future__ import annotations

from server.models import ValidatorAction, ValidatorName, ValidatorStatus
from server.pipeline.validators.style import gherkin_style
from tests import factories as f


def check(feature: str):
    ctx = f.validation_context(rendered={"tc_case_001": feature})
    return list(gherkin_style(ctx))


def messages(feature: str) -> str:
    return " | ".join(r.message or "" for r in check(feature))


GOOD = """\
@checkout
Feature: Order approval

  Scenario: An order over EUR500 is held for manager approval
    Given the tester signs in as "<<user_email_1>>"
    When the tester submits the order with manager approval
    Then the order confirmation appears
"""


def test_a_well_written_feature_produces_no_findings():
    results = check(GOOD)
    assert [r.status for r in results] == [ValidatorStatus.pass_]
    assert results[0].validator == ValidatorName.gherkin_style


def test_findings_warn_and_never_reject():
    # A grounded test case must still reach the human even if a sentence is
    # clumsy. The gate is for fabrication, not for prose.
    results = check(GOOD.replace("Then the order confirmation appears\n", ""))
    assert results
    assert all(r.action == ValidatorAction.warn for r in results)
    assert all(r.status == ValidatorStatus.warn for r in results)


def test_a_feature_with_no_then_is_called_a_transcript():
    # The single most important finding here: a test case that never says what
    # should be true afterwards is a recording, not a test.
    assert "transcript" in messages(GOOD.replace("Then the order confirmation appears\n", ""))


def test_a_step_that_repeats_the_one_before_it_is_flagged():
    # The defect `merge_repeats` exists to catch, checked at the other end so a
    # regression in either place is visible.
    feature = GOOD.replace(
        "    When the tester submits the order with manager approval\n",
        "    When the tester submits the order\n    And the tester submits the order\n",
    )
    assert "repeats the step before it" in messages(feature)


def test_mechanics_are_flagged_but_quoted_labels_are_not():
    # "Submits the order" beats "clicks the blue button" -- but an application
    # may genuinely have a control named "Click here", and quoting it is right.
    assert "mechanics" in messages(
        GOOD.replace("submits the order with manager approval", "clicks the blue button")
    )
    assert "mechanics" not in messages(
        GOOD.replace("submits the order with manager approval", 'follows the "Click here" link')
    )


def test_a_step_listing_several_actions_is_flagged():
    # One segment can hold several actions; one step should still name one
    # intent. A step that reads out the segment cannot be executed as a single
    # check, which is what a step is for.
    feature = GOOD.replace(
        "submits the order with manager approval",
        'enters "PO-4471", sets the total to "615", ticks approval, and submits',
    )
    assert "several actions at once" in messages(feature)


def test_two_actions_joined_by_and_are_left_alone():
    feature = GOOD.replace(
        "submits the order with manager approval",
        'adds "Blue Widget" to the cart and goes to checkout',
    )
    assert "several actions" not in messages(feature)


def test_a_long_word_containing_and_is_not_a_conjunction():
    # Without word boundaries "and" matches inside "brand" and "then" inside
    # "strengthen", so an ordinary sentence with one comma becomes a finding.
    # This is here because that bug shipped once, as a literal backspace where
    # the word boundary should have been.
    feature = GOOD.replace(
        "submits the order with manager approval", "filters by brand, sorted by price"
    )
    assert "several actions" not in messages(feature)


def test_traceability_in_a_sentence_is_flagged():
    # Cucumber matches step text against a step-definition regex, so an id or a
    # review marker glued to the sentence breaks the glue.
    for leaked in ("!!", "evt_012", "tc_0447"):
        feature = GOOD.replace(
            "submits the order with manager approval",
            f"submits the order with manager approval {leaked}",
        )
        assert "sidecar" in messages(feature), leaked


def test_a_scenario_opening_with_and_is_flagged():
    feature = GOOD.replace(
        'Given the tester signs in as "<<user_email_1>>"', "And the tester waits"
    )
    assert "continues nothing" in messages(feature)


def test_a_then_before_any_action_is_flagged():
    feature = """\
Feature: Order approval

  Scenario: Nothing established this
    Then the order confirmation appears
    When the tester submits the order
"""
    assert "before any Given or When" in messages(feature)


def test_nothing_rendered_is_a_skip_not_a_pass():
    # "This had no subject" and "this passed" must stay distinguishable, or the
    # gate's coverage is unknowable.
    ctx = f.validation_context(rendered={})
    results = list(gherkin_style(ctx))
    assert [r.status for r in results] == [ValidatorStatus.skip]


def test_a_given_after_an_expected_result_is_flagged():
    # Given/When/Then in that order is not how anyone writes Gherkin; it reads
    # as the scenario restarting halfway down. `narrative.py` prevents it, and
    # this is the other end of that guarantee.
    feature = """\
Feature: Order approval

  Scenario: The scenario restarts halfway down
    Given the tester signs in
    When the tester adds a widget
    Then the cart badge updates
    Given the tester goes to checkout
    When the tester places the order
    Then the order confirmation appears
"""
    assert "preconditions belong at the top" in messages(feature)


def test_an_expected_result_before_any_when_is_flagged():
    # A real run rendered `Given the tester signs in ...` immediately followed
    # by `Then the user is redirected ...`. Both keywords are legal Gherkin and
    # the sequence still reads wrong: the scenario asserts about its own
    # preconditions and never says what it did. `narrative._lay_out` prevents
    # it by promoting an assertion-bearing setup step to `When`; this is the
    # net for when that regresses.
    assert "before any When" in messages(
        "Feature: Sign in\n"
        "\n"
        "  Scenario: Signing in\n"
        '    Given the tester signs in as "someone"\n'
        "    Then the catalog page is shown\n"
    )


def test_and_continues_the_keyword_before_it_when_checking_order():
    # `Given / And / Then` has a Given in front of the Then. Reading `And` as a
    # keyword in its own right would report a Then with nothing before it, which
    # is the kind of false finding that teaches people to ignore the validator.
    assert "before any Given or When" not in messages(
        GOOD.replace(
            "When the tester submits the order with manager approval\n",
            "When the tester submits the order with manager approval\n"
            "    And the tester confirms the total\n",
        )
    )


def test_one_scenario_refers_to_one_person():
    # Steps come from the naming stage and expected results from the assertion
    # stage, so voice drifts between them: a real run said "the tester" in every
    # step and "the user is redirected" in its expected result.
    assert "more than one way" in messages(
        GOOD.replace("Then the order confirmation appears", "Then the user sees the confirmation")
    )


def test_a_consistent_voice_is_not_flagged():
    assert "more than one way" not in messages(GOOD)
