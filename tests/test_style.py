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


# --------------------------------------------------------------------------
# the shape of a scenario, not of the file
# --------------------------------------------------------------------------


DANGLING = """\
Feature: Hamper creation

  Scenario: Upgrading hamper size and adjusting item quantities
    When the tester opens the hampers category
    Then the hampers category page is loaded

    When the tester dismisses the hamper capacity warning
"""


def test_a_scenario_that_ends_on_an_action_has_no_verdict():
    # Shipped, on a real recording. The file-level check above passes here --
    # there IS a `Then` in the file -- so a scenario ending on a dangling
    # `When` went out with nothing to pass or fail. Whoever executes it reaches
    # the last line having been told to do something and never told what should
    # have happened.
    assert "ends on an action rather than an expected result" in messages(DANGLING)


def test_a_background_is_not_required_to_end_on_a_then():
    # A Background is shared setup. It never asserts, and requiring a verdict
    # from it would be requiring it to stop being a background.
    feature = """\
Feature: Order approval

  Background:
    Given the tester signs in

  Scenario: An order over EUR500 is held
    When the tester submits an order totalling "615"
    Then the order is held for manager approval
"""
    assert "ends on an action" not in messages(feature)


SIX_BEATS = """\
Feature: Hamper creation

  Scenario: Upgrading hamper size and adjusting item quantities
    When the tester opens the hampers category
    Then the hampers category page is loaded

    When the tester selects "Morocco" as the delivery country
    Then the hamper selection options are displayed

    When the tester selects the "Small Wicker Basket"
    Then the hamper capacity is updated to 5 items

    When the tester increases the quantity of an item
    Then the quantity increases to 18

    When the tester upgrades the hamper
    Then a larger basket is offered
"""


def test_a_scenario_of_unrelated_beats_is_several_test_cases():
    # Navigate, set country, pick basket, change quantity, upgrade -- five
    # actions each with its own unrelated outcome. Every literal in it can be
    # true and the test case is still wrong, because nobody executing it can
    # tell what failed when it fails.
    #
    # This is the finding no deterministic check had an opinion on, and it is
    # the one that decides whether the output reads as a test or a transcript.
    assert "action/outcome blocks" in messages(SIX_BEATS)


def test_a_scenario_with_two_checkpoints_is_not_flagged():
    # The bar is not "one Then per scenario". A test that establishes something
    # and then checks the consequence is normal and good, and flagging it would
    # push the generator toward scenarios that assert once and prove little.
    feature = """\
Feature: Hamper creation

  Scenario: A hamper at capacity cannot be upgraded past the largest size
    Given the tester starts creating a hamper
    When the tester fills the basket to its capacity
    Then the basket is full at 5 of 5 items

    When the tester upgrades to the largest hamper and fills it
    Then no bigger hampers are available
"""
    assert check(feature)[0].status == ValidatorStatus.pass_


def test_an_over_long_scenario_is_rejected_not_merely_noted():
    # CLAUDE.md, STATUS.md and the drafting prompt all said MAX_BEATS rejects at
    # the gate. The code warned, so the model was being told to aim at a gate
    # that could not fail it -- and a real recording shipped three near-duplicate
    # beats under one heading through thirteen green validators.
    #
    # Safe to arm now because `split.py` cuts an over-long scenario before it is
    # ever rendered, and free of blast radius: no feature file this pipeline has
    # ever produced reaches five blocks.
    rejections = [r for r in check(SIX_BEATS) if r.action == ValidatorAction.reject]
    assert rejections, "shape is not phrasing"
    assert all(r.status == ValidatorStatus.fail for r in rejections)
    assert "action/outcome blocks" in rejections[0].message


def test_an_over_long_scenario_has_no_repair_route():
    # Terminal by design. Repairing it means re-drafting, and re-drafting can
    # change the step COUNT -- which SS3.6 promises it does not.
    from server.pipeline.repair import VALIDATOR_REPAIR

    assert ValidatorName.gherkin_style not in VALIDATOR_REPAIR


def test_a_phrasing_finding_still_only_warns():
    # The posture that has not changed, and must not. Refusing to emit a
    # grounded test case because a sentence names a mouse would trade the
    # valuable thing for the cheap one.
    feature = """Feature: Checkout

  Scenario: An order is placed
    When the tester clicks the blue Place order button
    Then the confirmation banner appears
"""
    findings = check(feature)
    assert findings
    for result in findings:
        assert result.action == ValidatorAction.warn
        assert result.status == ValidatorStatus.warn


def test_a_background_that_asserts_is_rejected():
    # `_scenarios` skipped the Background under a docstring claiming it never
    # asserts, which nothing enforced -- and `narrative`'s two cut rules
    # disagreed in exactly the way that puts a When and a Then inside one.
    feature = """Feature: Checkout

  Background:
    Given the tester signs in
    When the tester opens the checkout page
    Then the confirmation banner appears

  Scenario: An order is placed
    When the tester places the order
    Then the order is confirmed
"""
    rejections = [r for r in check(feature) if r.action == ValidatorAction.reject]
    assert rejections
    assert "Background" in rejections[0].message


def test_a_background_of_only_preconditions_is_not_flagged():
    # The negative case. A Background is normal and good; what it must not do is
    # act or assert.
    feature = """Feature: Checkout

  Background:
    Given the tester signs in
    And the tester has an item in the cart

  Scenario: An order is placed
    When the tester places the order
    Then the order is confirmed
"""
    assert check(feature)[0].status == ValidatorStatus.pass_


def test_an_expected_result_that_checks_two_things_is_flagged():
    # A `Then` is the unit that passes or fails, so it has to be one claim.
    # Shipped on a fixture: "the checkout page updates to reflect the selected
    # Express delivery fee and the payment method is accepted" is two
    # assertions on one line, and when it fails nobody can say which half did.
    #
    # `_is_run_on` does not catch it -- that needs three conjunctions or two
    # commas, and this has one "and".
    feature = """\
Feature: Checkout validation

  Scenario: A payment method can be saved
    Given the tester signs in
    When the tester saves the payment method
    Then the checkout page updates to reflect the fee and the payment method is accepted
"""
    assert "checks two things at once" in messages(feature)


def test_one_claim_with_an_and_in_it_is_not_flagged():
    # The bar is two CLAIMS, not two words. "the order is confirmed with a
    # success alert and a reference number" is one thing being described, and
    # flagging it would push the generator toward stilted sentences.
    feature = """\
Feature: Order approval

  Scenario: An order is confirmed
    Given the tester signs in
    When the tester submits the order
    Then the order is confirmed with a success alert and a reference number
"""
    assert "checks two things at once" not in messages(feature)


def test_a_step_ending_in_a_full_stop_is_flagged():
    # A Gherkin step is a sentence FRAGMENT -- the keyword is its subject -- so
    # a full stop is never right on one. The voice rule has said so all along
    # and nothing enforced it; steps shipped with one.
    feature = """\
Feature: Checkout

  Scenario: A payment method can be saved
    Given the tester signs in
    When the tester saves the payment method.
    Then the payment method appears in the list
"""
    assert "ends in a full stop" in messages(feature)


def test_an_ellipsis_is_content_and_is_left_alone():
    # "Validating with the finance system..." is what the page said, and the
    # expected result is bound to that literal. Trimming it would break the
    # binding to make a style point.
    feature = """\
Feature: Checkout

  Scenario: Slow validation is reported
    Given the tester signs in
    When the tester submits the order for validation
    Then the page displays "Validating with the finance system..."
"""
    assert "full stop" not in messages(feature)


def test_an_expected_result_that_restates_the_scenario_name_adds_no_verdict():
    # `twoflows` closed on `Then Order requires approval` under a scenario
    # called "Order requires approval". It bound to a real literal, so every
    # grounding check passed, and the line proves nothing the heading did not
    # already say.
    feature = """Feature: Order approval

  Scenario: Order requires approval
    When the tester places a large order
    Then Order requires approval
"""
    assert "adds no verdict" in messages(feature)


def test_a_scenario_named_from_its_assertion_is_not_a_restatement():
    # The negative case, and the reason the rule needs BOTH directions to
    # match: `_scenario_from` legitimately names a scenario after what it
    # proves, so a `Then` that says more than its heading is correct.
    feature = """Feature: Order approval

  Scenario: Order requires approval
    When the tester places a large order
    Then the order is refused with "Orders over EUR500 require approval"
"""
    assert "adds no verdict" not in messages(feature)


def test_a_verdict_with_two_passing_states_is_flagged():
    # Repair hedged a claim it did not need to hedge. "saved or selected" is
    # satisfied by either, so a run where the save silently failed and the row
    # merely stayed selected passes -- the exact case the step exists to catch.
    feature = """Feature: Checkout

  Scenario: The payment method is stored
    When the tester submits the payment details
    Then the payment method is displayed as saved or selected
"""
    assert "two passing states" in messages(feature)


def test_an_or_inside_a_noun_phrase_is_not_a_hedge():
    # The negative case. The alternatives have to be what the sentence ends on;
    # "the vendor or supplier field" names one thing.
    feature = """Feature: Invoices

  Scenario: The supplier is recorded
    When the tester saves the invoice
    Then the vendor or supplier field shows "Northwind"
"""
    assert "two passing states" not in messages(feature)


def test_neither_new_finding_can_reject_a_grounded_test_case():
    # Both are phrasing, and `gherkin_style` has no row in VALIDATOR_REPAIR --
    # a rejection here is terminal, which is far too strong for a wording
    # problem a reviewer can fix in the UI in five seconds.
    feature = """Feature: Order approval

  Scenario: Order requires approval
    When the tester places a large order
    Then Order requires approval
"""
    for r in check(feature):
        assert r.action == ValidatorAction.warn
        assert r.status != ValidatorStatus.fail
