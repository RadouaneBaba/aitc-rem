"""The judge's contract with itself.

`judge._parse` drops any finding whose `check` is not in `CHECKS`, silently and
by design -- a finding pointing at a category that does not exist would reach the
author as an instruction to change nothing. The cost of that design is a trap:
adding a question to the PROMPT without adding it to `CHECKS` ships a change that
looks clean, runs, and does nothing. These tests are the tripwire.
"""

from __future__ import annotations

import json

from server.models import Evidence, NodeRef, Predicate, PredicateForm
from server.pipeline import judge as judge_mod
from server.pipeline.judge import CHECKS, SEVERITIES, SYSTEM_PROMPT, _form, _parse
from tests import factories as f


def test_every_check_the_parser_accepts_is_one_the_prompt_asks_for():
    """Otherwise the judge can never emit it, and the check is decoration."""
    for check in CHECKS:
        assert check in SYSTEM_PROMPT, (
            f"{check!r} is in CHECKS but the prompt never names it, so the model "
            f"has no way to know it exists"
        )


def test_every_check_the_prompt_names_is_one_the_parser_accepts():
    """Otherwise the finding is discarded at parse and the change is a no-op."""
    import re

    # The numbered list in the prompt is the authoritative statement of the
    # questions; anything bolded there is meant to come back as a `check`.
    named = set(re.findall(r"\*\*([a-z_]+)\*\* --", SYSTEM_PROMPT))
    assert named, "the prompt's check list changed shape; this guard needs updating"
    unknown = named - set(CHECKS)
    assert not unknown, (
        f"the prompt asks for {sorted(unknown)} but `_parse` drops them, so those "
        f"findings would vanish between the model and the author"
    )


def test_the_two_new_questions_survive_the_parser():
    """Each closes a hole nothing else in the system looks at.

    `claim_within_evidence` -- the gate proves the literal came back from a
    retrieval and nothing proves the SENTENCE is about the literal, which is how
    "rejected with a 409 Conflict status" shipped over a page alert with no 409
    in it.

    `refusal_is_true` -- every validator passes a refusal, because a refusal
    claims nothing. It is the only output here that is confident and otherwise
    entirely unchecked, and one shipped saying the tester left the recording's
    scope when the recorder had followed the tab and the index said so.
    """
    ir = _ir_with_one_step()
    answer = {
        "findings": [
            {
                "check": "claim_within_evidence",
                "severity": "fail",
                "scenario": "Order approval",
                "step": "step_001",
                "what": "The sentence claims a 409 and the literal is a page alert.",
                "fix": "Call get_network on that event, or claim the alert.",
            },
            {
                "check": "refusal_is_true",
                "severity": "fail",
                "scenario": "Order approval",
                "step": "step_001",
                "what": "The refusal says the tab was out of scope; the recorder followed it.",
                "fix": "Write the verdict the receipt page supports.",
            },
        ]
    }

    result = _parse(answer, ir)

    assert [finding.check for finding in result.findings] == [
        "claim_within_evidence",
        "refusal_is_true",
    ]
    # Both are `fail`, so both spend a revision round. `weak` never travels.
    assert len(result.fails) == 2


def test_a_check_nobody_defined_is_dropped_rather_than_acted_on():
    result = _parse(
        {"findings": [{"check": "vibes_are_off", "severity": "fail", "what": "no"}]},
        _ir_with_one_step(),
    )
    assert result.findings == []


def test_an_unrecognised_severity_is_treated_as_the_weaker_one():
    # Getting this backwards would let a typo trigger an author round, and every
    # rewrite risks `merge_repeats` folding two steps into one.
    result = _parse(
        {
            "findings": [
                {"check": CHECKS[0], "severity": "catastrophic", "what": "something", "step": ""}
            ]
        },
        _ir_with_one_step(),
    )
    assert result.findings[0].severity == "weak"
    assert "weak" in SEVERITIES


# --------------------------------------------------------------------------
# what the judge is shown
# --------------------------------------------------------------------------


def test_the_judge_is_told_how_a_claim_was_checked():
    """A verdict saying FIRST that was verified as merely PRESENT is exactly the
    mismatch `claim_within_evidence` exists to catch, and without this line the
    two are indistinguishable on the page."""
    evidence = Evidence(
        literal="The Autumnal Hamper",
        toolCallId="tc_0001",
        eventId="evt_001",
        kind="semantic_node",
        predicate=Predicate(
            form=PredicateForm.first_of,
            container=NodeRef(role="list", name="Products"),
        ),
    )
    assert _form(evidence) == '  [checked as first_of of the list "Products"]'


def test_plain_containment_adds_no_noise():
    # The default is silent: every assertion written before predicates existed
    # carries none, and annotating them all with "checked as contains" would be
    # a line of nothing on every verdict in the corpus.
    plain = Evidence(
        literal="Order confirmed", toolCallId="tc_0001", eventId="evt_001", kind="semantic_node"
    )
    assert _form(plain) == ""


def test_the_judge_can_look_at_what_the_server_answered():
    """`claim_within_evidence`'s worked case is a status-code claim, and the only
    way to tell an overreaching sentence from a badly cited one is to look."""
    assert "get_network" in judge_mod.JUDGE_TOOLS


def test_a_refusal_is_printed_where_the_judge_will_read_it():
    ir = _ir_with_one_step(why_not="the tester moved to a tab outside this recording")
    printed = judge_mod.describe_claims(ir)
    assert "no verdict, because: the tester moved to a tab outside this recording" in printed


# --------------------------------------------------------------------------


def _ir_with_one_step(*, why_not: str = ""):
    step = f.step(ident="step_001", text="the tester places the order", assertions=[])
    if why_not:
        step.whyNot = why_not
    case = f.test_case(steps=[step], scenarioName="Order approval")
    return f.ir_document(test_cases=[case])


def test_findings_reach_the_author_as_sentences_and_not_as_a_report():
    # `coherence: weak on step_004` is the vocabulary the rebuild deleted -- it
    # names a machine's category rather than the thing that is wrong.
    result = _parse(
        {
            "findings": [
                {
                    "check": "refusal_is_true",
                    "severity": "fail",
                    "scenario": "Order approval",
                    "step": "step_001",
                    "what": "The refusal misreads the recording.",
                    "fix": "The receipt page was captured; assert the total.",
                }
            ]
        },
        _ir_with_one_step(),
    )
    feedback = result.findings[0].as_feedback()

    assert "refusal_is_true" not in feedback
    assert "fail" not in feedback
    assert feedback.startswith('In "Order approval" (step_001): The refusal misreads')


def test_the_artifact_keeps_the_machine_readable_form():
    result = _parse(
        {"findings": [{"check": "claim_within_evidence", "severity": "fail", "what": "x"}]},
        _ir_with_one_step(),
    )
    artifact = json.loads(json.dumps(result.to_artifact()))
    assert artifact["findings"][0]["check"] == "claim_within_evidence"
