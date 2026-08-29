"""The Gherkin renderer (SS11.1).

The `.feature` file is the artifact a QA lead judges the whole tool by, and for
a while it did not survive that judgment: `Feature:` and `Scenario:` both set to
the objective the tester typed, seven steps of `When`, `!!` glued to sentences a
step definition has to match, and a traceability comment under every line.

So these tests are about what a reader sees, and each one is named after the
property that makes the file worth reading. Parsing is table stakes and is
checked first; everything after it is the difference between valid Gherkin and
a test case.
"""

from __future__ import annotations

import pytest

from server.config import ProjectConfig
from server.renderers.gherkin import render_document, render_test_case
from tests import factories as f


def parse(text: str):
    parser = pytest.importorskip("gherkin.parser")
    return parser.Parser().parse(text)


def build_case(**kwargs):
    """A signed-in tester who adds a widget and submits the order.

    `prefix` renumbers the steps and events. Step ids are document-global in a
    real run (`draft._scenarios` mints them from one counter), so two cases in
    one IR never share one -- and a fixture that lets them is a fixture that can
    build an input the pipeline cannot, which is how a whole test path once ran
    against a field the recorder never writes.
    """
    prefix = kwargs.pop("prefix", "")
    assertion = f.assertion(
        f"asrt_{prefix}001",
        "the confirmation banner appears",
        ev=f.evidence("Order confirmed", "tc_0447", f"evt_{prefix}027", "semantic_node"),
    )
    steps = kwargs.pop(
        "steps",
        [
            f.step(
                f"step_{prefix}001",
                'the tester signs in as "<<user_email_1>>"',
                role="setup",
                event_ids=[f"evt_{prefix}003"],
                assertions=[],
            ),
            f.step(
                f"step_{prefix}002",
                'the tester adds "Blue Widget" to the cart',
                role="test_step",
                event_ids=[f"evt_{prefix}012", f"evt_{prefix}013"],
                assertions=[],
            ),
            f.step(
                f"step_{prefix}003",
                "the tester submits the order form",
                role="test_step",
                event_ids=[f"evt_{prefix}027"],
                assertions=[assertion],
            ),
        ],
    )
    kwargs.setdefault("title", "Order checkout")
    kwargs.setdefault("scenarioName", "Submitting a valid order shows the confirmation")
    return f.test_case(steps=steps, **kwargs)


def steps_of(text: str) -> list[str]:
    """The step lines a reader actually sees, keyword included."""
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().split(" ")[0] in {"Given", "When", "Then", "And", "But"}
    ]


# --------------------------------------------------------------------------
# it parses
# --------------------------------------------------------------------------


def test_the_rendered_feature_parses(capsys):
    text = render_test_case(build_case(), generated_on="2026-08-17")
    parse(text)
    print(text)


def test_a_case_with_everything_still_parses():
    case = build_case(
        tags=["checkout", "@smoke"],
        preconditions=[
            f.precondition("pre_001", 'the tester is signed in as "<<user_email_1>>"', ["evt_003"]),
            f.precondition("pre_002", "the cart is empty", ["evt_004"]),
        ],
        parameters=[f.parameter("user_email_1", "<<user_email_1>>", "email")],
        omitted=[f.omitted_segment("seg_004", "exploratory", 3, "browsed the reports page")],
    )
    case.steps[0].escalation = "I could not tell whether the export finished - did a file download?"
    case.steps[0].confidence = "low"
    case.steps[1].selectorHints = [f.selector_hint("testId", '[data-testid="submit"]', "high")]

    text = render_test_case(case, generated_on="2026-08-17")
    parse(text)


def test_multiline_text_cannot_break_the_file():
    # Gherkin is line-oriented, so a newline inside a step would produce a file
    # that no longer parses.
    case = build_case(
        steps=[f.step("step_001", "the tester does\nsomething\n\nover lines", assertions=[])]
    )
    text = render_test_case(case)
    parse(text)
    assert "the tester does something over lines" in text


# --------------------------------------------------------------------------
# it reads as a test case
# --------------------------------------------------------------------------


def test_the_feature_names_a_capability_and_the_scenario_names_the_case():
    # The defect this replaced: both lines set to the objective string, so the
    # file announced itself twice and named nothing.
    text = render_test_case(build_case())

    feature = next(ln for ln in text.splitlines() if ln.startswith("Feature:"))
    scenario = next(ln for ln in text.splitlines() if ln.strip().startswith("Scenario:"))

    assert feature == "Feature: Order checkout"
    assert "Submitting a valid order shows the confirmation" in scenario
    assert feature.split(": ", 1)[1] != scenario.split(": ", 1)[1]


def test_setup_becomes_given_and_the_tested_behaviour_becomes_when():
    # Given/When/Then is a property of the scenario, so it is derived from the
    # step roles rather than chosen one step at a time -- which is what
    # produced seven `When`s in a row.
    lines = steps_of(render_test_case(build_case()))

    assert lines[0].startswith("Given ")
    assert lines[1].startswith("When ")
    assert any(line.startswith("Then ") for line in lines)


def test_a_repeated_keyword_becomes_and():
    lines = steps_of(render_test_case(build_case()))
    assert lines[2].startswith("And "), lines


def test_an_expected_result_follows_the_step_that_produced_it():
    lines = steps_of(render_test_case(build_case()))
    submit = next(i for i, line in enumerate(lines) if "submits the order form" in line)
    assert lines[submit + 1] == "Then the confirmation banner appears"


def test_no_step_carries_traceability_in_its_sentence():
    # Cucumber matches step text against a step-definition regex. An event id
    # or a review marker in the sentence breaks the glue as well as the
    # reading, so all of it lives in the sidecar (SS3.2 is unaffected: the
    # pointer stays in the IR and the trace, where the validator reads it).
    case = build_case()
    case.steps[0].confidence = "low"
    case.steps[0].fidelity = ["canvas_interaction"]
    case.steps[1].selectorHints = [f.selector_hint("css", "button.submit", "low")]

    for line in steps_of(render_test_case(case)):
        assert "!!" not in line
        assert "evt_" not in line
        assert "tc_0447" not in line
        assert "button.submit" not in line
        assert "canvas_interaction" not in line


def test_the_body_holds_nothing_but_gherkin():
    text = render_test_case(build_case())
    body = text.split("Feature:", 1)[1]
    assert "#" not in body, "the feature body must not carry comments"


def test_a_step_needing_review_is_tagged_rather_than_punctuated():
    # A tag is greppable, survives a `--tags` filter in CI, and does not touch
    # the sentence. `!!` did none of those things.
    case = build_case()
    case.steps[1].escalation = "did a file download?"

    text = render_test_case(case)
    parse(text)

    assert "@needs-review" in text
    assert "!!" not in text


def test_a_notice_level_fidelity_flag_does_not_demand_review():
    # SS6.8 splits its flags into warnings and notices. `network_incomplete` on
    # a step whose description is perfectly sound is a notice; marking it for
    # review is why six of seven steps once carried a marker, which teaches the
    # reader to ignore all of them.
    case = build_case()
    for step in case.steps:
        step.fidelity = ["network_incomplete", "rapid_sequence"]

    assert "@needs-review" not in render_test_case(case)

    case.steps[0].fidelity = ["canvas_interaction"]
    assert "@needs-review" in render_test_case(case)


def test_a_closed_shadow_root_somewhere_on_the_page_is_a_notice():
    # It is raised while BUILDING the snapshot, for any closed shadow root
    # anywhere on the page -- not for the thing the tester acted on. The demo
    # app has one `<promo-widget>` on its checkout page, so six of seven
    # fixtures inherited it and six of seven feature files came out tagged
    # `@needs-review`: the same devaluation the test above describes, arriving
    # by a different route.
    #
    # A true statement about the snapshot and a false one about the step. Only
    # the second is what the marker means.
    case = build_case()
    for step in case.steps:
        step.fidelity = ["closed_shadow_root"]
    assert "@needs-review" not in render_test_case(case)


def test_the_objective_becomes_the_description_block_not_a_comment():
    # Gherkin has a native place for this and Cucumber reports render it. A
    # leading `#` comment is for the machine.
    case = build_case(description="Orders above EUR500 need a manager to approve them.")
    text = render_test_case(case)

    described = text.split("Feature: Order checkout", 1)[1].split("Scenario:", 1)[0]
    assert "Orders above EUR500 need a manager to approve them." in described
    assert "#" not in described


def test_captured_values_and_placeholders_stay_in_the_step_text():
    # SS7.2 -- redaction placeholders carry forward as test parameters, which
    # is what tells the person running the test what to supply.
    text = render_test_case(build_case())
    assert 'the tester signs in as "<<user_email_1>>"' in text
    assert 'adds "Blue Widget" to the cart' in text


def test_one_header_line_says_where_the_evidence_is():
    text = render_test_case(build_case(), generated_on="2026-08-17")
    header = text.splitlines()[0]

    # The product name, and it travels: this line is the top of every feature
    # file the tool produces, so it lands in Jira, in git and in front of
    # whoever reviews the test.
    assert header.startswith("# AITC - rec_test01 - 2026-08-17")
    assert "tc_case_001.trace.md" in header
    # ...and it is the only comment in the file.
    assert len([ln for ln in text.splitlines() if ln.strip().startswith("#")]) == 1


def test_a_project_can_turn_the_header_off_entirely():
    text = render_test_case(build_case(), config=ProjectConfig(header=False))
    assert text.startswith("@") or text.startswith("Feature:")


# --------------------------------------------------------------------------
# what must survive
# --------------------------------------------------------------------------


def test_preconditions_become_a_background_block():
    case = build_case(
        preconditions=[
            f.precondition("pre_001", 'the tester is signed in as "<<user_email_1>>"', ["evt_003"]),
            f.precondition("pre_002", "the cart is empty", ["evt_004"]),
        ]
    )
    text = render_test_case(case)
    parse(text)

    assert "Background:" in text
    assert 'Given the tester is signed in as "<<user_email_1>>"' in text
    assert "And the cart is empty" in text


def test_a_background_renders_inherited_preconditions_and_lifted_steps():
    # `_background` returned after the lifted lines, which DELETED
    # `case.preconditions` -- and `_build_case` fills those for case 2 onwards
    # with the setup steps of earlier cases, precisely so each scenario is
    # runnable standalone. So the second test case out of a recording lost the
    # sign-in the first one performed, whenever its own steps happened to begin
    # with a setup step.
    #
    # `lift_background` turns on only when a document has two scenarios, which
    # is exactly when preconditions exist -- so the two were never both present
    # until now, and nothing caught it.
    second = build_case(
        ident="tc_rec_test01_02",
        prefix="2",
        preconditions=[
            f.precondition("pre_001", 'the tester is signed in as "<<user_email_1>>"', ["evt_1003"])
        ],
    )
    ir = f.ir_document(test_cases=[build_case(ident="tc_rec_test01_01", prefix="1"), second])

    text = render_test_case(second, ir=ir)
    parse(text)

    assert "Background:" in text
    assert 'Given the tester is signed in as "<<user_email_1>>"' in text, (
        "the inherited precondition must survive the lift"
    )
    assert "the tester adds a widget to the cart" not in text.split("Scenario:")[0], (
        "only preconditions and lifted setup belong above the Scenario"
    )


def test_every_step_of_a_multi_scenario_document_reaches_its_feature_file():
    # The property `event_coverage` cannot check, because it reads the IR and
    # not the rendered output -- and a file missing a step still parses. This is
    # the shape of bug that shipped once already.
    first = build_case(ident="tc_rec_test01_01", prefix="1")
    second = build_case(
        ident="tc_rec_test01_02",
        prefix="2",
        preconditions=[f.precondition("pre_001", "the tester is signed in", ["evt_1003"])],
    )
    ir = f.ir_document(test_cases=[first, second])

    for case in (first, second):
        text = render_test_case(case, ir=ir)
        for step in case.steps:
            assert step.text in text, f"{step.id} vanished from {case.id}"


def test_omitted_work_is_shown_rather_than_hidden():
    # A verbatim transcript is unusable; silent deletion is untrustworthy. The
    # marker is the third option, and it is about completeness rather than
    # traceability -- which is why it is the one comment that stays (SS9.3).
    case = build_case(
        omitted=[f.omitted_segment("seg_004", "exploratory", 3, "browsed the reports page")]
    )
    text = render_test_case(case)
    parse(text)

    assert "3 exploratory action(s) omitted" in text
    assert "browsed the reports page" in text


def test_rejected_assertions_are_not_rendered():
    # The review UI's accept/reject is the final gate; a rejected candidate is
    # not part of the test case.
    case = build_case()
    case.steps[2].assertions[0].accepted = False
    text = render_test_case(case)

    assert "the confirmation banner appears" not in text
    parse(text)


def test_a_document_renders_every_test_case():
    document = f.ir_document(test_cases=[build_case(), build_case(ident="tc_case_002")])
    rendered = render_document(document)

    assert set(rendered) == {"tc_case_001", "tc_case_002"}
    for text in rendered.values():
        parse(text)


# --------------------------------------------------------------------------
# parameters
# --------------------------------------------------------------------------


def test_outline_mode_lifts_placeholders_into_an_examples_table():
    case = build_case(parameters=[f.parameter("user_email_1", "<<user_email_1>>", "email")])
    text = render_test_case(case, config=ProjectConfig(parameters="outline"))
    parse(text)

    assert "Scenario Outline:" in text
    assert 'the tester signs in as "<user_email_1>"' in text
    assert "Examples:" in text
    assert "| user_email_1 |" in text
    assert "| <<user_email_1>> |" in text


def test_inline_is_the_default_because_a_tester_reads_top_to_bottom():
    # A single-row Examples table makes the person executing the test look in
    # two places for one value.
    case = build_case(parameters=[f.parameter("user_email_1", "<<user_email_1>>", "email")])
    text = render_test_case(case)

    assert "Scenario Outline:" not in text
    assert "Examples:" not in text
    assert 'the tester signs in as "<<user_email_1>>"' in text


def test_a_lifted_feature_file_still_round_trips_through_review():
    # `apply_feature_text` compares the file's step lines against
    # `build_narrative(case.steps).body`, and a Background carrying INHERITED
    # preconditions has lines that exist in no narrative of this case -- so
    # every human edit of a two-scenario feature file was refused with "this
    # does not line up with the test case it came from". Latent until a
    # recording produced two scenarios, which none ever had.
    from server.api.review import apply_feature_text, new_review

    first = build_case(ident="tc_rec_test01_01", prefix="1")
    second = build_case(
        ident="tc_rec_test01_02",
        prefix="2",
        preconditions=[f.precondition("pre_001", "the tester is signed in", ["evt_1003"])],
    )
    ir = f.ir_document(test_cases=[first, second])
    rendered = render_test_case(second, ir=ir)
    review = new_review(ir)

    edited = rendered.replace(
        "the tester submits the order form", "the tester confirms the order", 1
    )
    case = apply_feature_text(
        ir, review, case_id=second.id, text=edited, rendered=rendered
    )

    assert [s.text for s in case.steps][-1] == "the tester confirms the order"
    assert [e.kind for e in review.edits] == ["step_text"]


def test_editing_an_inherited_precondition_is_refused_by_name():
    # Refusing is the honest answer, in the same way this function refuses
    # structure: the sentence belongs to the case that performed it.
    from server.api.review import ReviewError, apply_feature_text, new_review

    first = build_case(ident="tc_rec_test01_01", prefix="1")
    second = build_case(
        ident="tc_rec_test01_02",
        prefix="2",
        preconditions=[f.precondition("pre_001", "the tester is signed in", ["evt_1003"])],
    )
    ir = f.ir_document(test_cases=[first, second])
    rendered = render_test_case(second, ir=ir)
    review = new_review(ir)

    edited = rendered.replace("the tester is signed in", "the tester is logged in", 1)

    with pytest.raises(ReviewError) as excinfo:
        apply_feature_text(ir, review, case_id=second.id, text=edited, rendered=rendered)

    assert "earlier test case" in str(excinfo.value)
