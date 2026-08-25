"""The binding stage, and the question `COVERAGE_FLOOR` does not ask.

`bind.py` is where SS3.2's guarantee is actually made -- "a claim is admissible
only if it can point at the retrieval that produced it" -- and until now the
deterministic pass that makes most of those decisions had no tests of its own.
`name.py`, `assertions.py` and `compose.py` each had a test module; the three
stages that replaced them inherited end-to-end coverage in `test_pipeline.py`
and nothing at the unit where the judgement is made.

That gap is not academic. It is exactly where the defect below lived, on disk,
through a green gate:

    claim:   the hamper is shown as a "Small Wicker Basket" with a capacity
             of "5 / 5"
    literal: Small Wicker Basket

Both grounding validators passed. Both were asked about the literal.

The tests here are named after the guarantee rather than the function, because
the guarantee is what has to survive the next refactor of the scoring.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.evidence.store import EvidenceStore
from server.evidence.tools import ToolRunner
from server.llm import ScriptedModelClient, answer, calls
from server.models import DiffNode, SegmentRole, SnapshotDiff
from server.pipeline.bind import (
    COVERAGE_FLOOR,
    MIN_LITERAL,
    _best_literal,
    _existence_only,
    _unwitnessed,
    bind_claims,
)
from server.pipeline.draft import (
    DraftedExpectation,
    DraftedScenario,
    DraftedStep,
    DraftResult,
)
from server.pipeline.segment import segment_recording
from server.storage.paths import Storage
from tests import factories as f

# --------------------------------------------------------------------------
# what the evidence has to witness
# --------------------------------------------------------------------------


#: Every (claim, literal) pair the pipeline actually bound across the runs in
#: `runs/`, plus the two it should not have. Kept as one table because the
#: value of this check is the RATIO: a rule that rejects the two bad pairs and
#: any of the good ones is not a fix, it is a yield cut wearing a fix's name.
#:
#: The good pairs are verbose on purpose. "the system displays an error message
#: indicating that the order requires approval" shares four content words out of
#: eleven with "Orders over EUR500 require approval", and it is correct: the
#: extra words are framing, and framing asserts nothing. Any rule phrased as a
#: floor on how much of the CLAIM the literal covers rejects it, which is why
#: this is not phrased that way.
WITNESSED = [
    ('the cart badge shows "1 items"', "Cart contains 1 items"),
    ('the export fails with an "Internal server error"', "Internal server error"),
    (
        "the system displays an error message indicating that the order requires approval",
        "Orders over EUR500 require approval",
    ),
    ("the order is rejected with an approval required status", "APPROVAL_REQUIRED"),
    ("the order is confirmed", "Order confirmed"),
    (
        'the message "Validating with the finance system..." is shown',
        "Validating with the finance system...",
    ),
    (
        "an error message indicating that the maximum quantity has been exceeded is displayed",
        "Maximum Quantity allowed is 3",
    ),
    # The case `_Candidate.conclusive` routes to an agent. If it gets there and
    # the agent binds it, the sentence and the evidence do agree.
    ("the basket is full at 5 of 5 items", "5 / 5"),
]

UNWITNESSED = [
    # The defect, exactly as it shipped in runs/rec_MT7MXBS9B2VB/run_001.
    (
        'the hamper is shown as a "Small Wicker Basket" with a capacity of "5 / 5"',
        "Small Wicker Basket",
        "5 / 5",
    ),
    # The same sentence in CLAUDE.md's own worked example, which has the same
    # hole: the number is the part a broken counter would break.
    (
        "the hamper becomes a Large Wicker Basket holding 18 items",
        "Large Wicker Basket",
        "18",
    ),
]


@pytest.mark.parametrize(("claim", "literal"), WITNESSED)
def test_a_literal_that_covers_what_the_claim_checks_still_binds(claim: str, literal: str):
    # The denominator of the fix. Prose framing around the evidence is not an
    # unproved assertion, and a rule that treats it as one costs Yield on every
    # honest claim in the corpus to catch two dishonest ones.
    assert _unwitnessed(claim, literal) is None


@pytest.mark.parametrize(("claim", "literal", "missing"), UNWITNESSED)
def test_a_claim_may_not_rest_on_evidence_for_only_half_of_it(
    claim: str, literal: str, missing: str
):
    # SS3.2 says a claim is admissible only if it can point at the retrieval
    # that produced it. A sentence checking two things and citing evidence for
    # one is half inadmissible, and nothing in the gate was looking at the
    # other half: `evidence_retrieved` and `assertion_grounding` both ask about
    # the literal, and the literal was true.
    gap = _unwitnessed(claim, literal)
    assert gap is not None
    assert missing in gap


def test_the_missing_half_is_named_in_the_reason():
    # A reviewer asking "why is there no expected result here" gets an answer,
    # the same way a suppressed noise literal does. "Could not bind" is not one.
    gap = _unwitnessed('the total is "615" including "12" of delivery', "Total 615")
    assert gap is not None
    assert '"12"' in gap


def test_a_number_is_witnessed_by_a_number_and_not_by_a_substring():
    # "1" is in "18". Checking digits as substrings would let a claim about one
    # item bind to evidence about eighteen, which is the failure mode this rule
    # exists to prevent, arriving through the rule itself.
    assert _unwitnessed("the cart holds 1 item", "Cart contains 18 items") is not None
    assert _unwitnessed("the cart holds 18 items", "Cart contains 18 items") is None


def test_a_quoted_value_is_matched_on_normalised_whitespace():
    # The claim quotes what the drafter read in the index; the literal is what
    # the snapshot stored. A line break between them is not a disagreement.
    assert _unwitnessed('the capacity is "5 / 5"', "Small Wicker Basket   5 /\n5") is None


# --------------------------------------------------------------------------
# what is not worth checking at all
# --------------------------------------------------------------------------


APPEARANCE = [
    # Bound in runs/rec_MT7VTN7ZRJPO/run_001 to the literal "Shopping Bag" --
    # the panel's own heading -- and shipped as the scenario's closing verdict.
    "the shopping bag panel opens, displaying the item(s) previously added to the cart",
    "the hampers category page is loaded",
    "the form is displayed",
    "the page opens",
    "the checkout view is rendered",
]

#: Claims about what the APPLICATION said. Every one of these mentions
#: something being shown, and every one is worth checking, which is why the
#: rule is about container nouns reaching a visibility verb rather than about
#: the verb alone.
SUBSTANTIVE = [
    'the message "Validating with the finance system..." is shown',
    "the system displays an error message indicating that the order requires approval",
    'the payment panel shows a total of "615"',
    "the order is confirmed",
]


@pytest.mark.parametrize("claim", APPEARANCE)
def test_a_claim_that_the_interface_appeared_checks_the_browser(claim: str):
    # The drafting prompt forbids these in bold and a real recording shipped
    # one anyway, which is the lesson `NOISE` already taught once: a prompt
    # line is not an enforcement. No literal rescues this claim, so it is
    # refused before a retrieval is spent on it.
    assert _existence_only(claim) is not None


@pytest.mark.parametrize("claim", SUBSTANTIVE)
def test_a_claim_about_what_the_application_said_is_not_refused_as_navigation(claim: str):
    assert _existence_only(claim) is None


def test_a_container_carrying_a_real_value_is_about_the_value():
    # The narrow half of the rule. "the payment panel shows a total of "615""
    # names a panel and a visibility verb and is still a claim about 615, which
    # `_unwitnessed` then checks like any other.
    assert _existence_only('the results panel displays "3 matches"') is None


# --------------------------------------------------------------------------
# the same rules, through the stage
# --------------------------------------------------------------------------


def _store_and_runner(tmp_path: Path, role: str, name: str):
    """A recording whose second event ADDS a node with the given text.

    Added rather than merely present: `_candidates` offers only what the event
    changed, so evidence that was on the page beforehand is not a candidate at
    all -- the rule that stopped "a file containing the order details is
    downloaded" binding to the button the tester had just pressed.
    """
    appeared = f.node("0.4", role, name)
    rec = f.recording(
        events=[
            f.event("evt_001", 0, at=0.0, tgt=f.target("button", "Sign in")),
            f.event(
                "evt_002",
                1,
                at=1000.0,
                tgt=f.target("button", "Add"),
                after=f.snapshot(at=1100.0, root=f.node("0", "main", "Basket"), live=[appeared]),
                diff=SnapshotDiff(
                    added=[DiffNode(ref="0.4", role=role, name=name)], removed=[], changed=[]
                ),
            ),
        ]
    )
    store = EvidenceStore(recording=rec, segments=segment_recording(rec, run_id="run_001"))
    storage = Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")
    return store, ToolRunner(store=store, storage=storage, run=storage.run(rec.id, "run_001"))


def _drafted(claim: str, event_id: str = "evt_002") -> DraftResult:
    return DraftResult(
        title="t",
        description="",
        tags=[],
        scenarios=[
            DraftedScenario(
                name="s",
                steps=[
                    DraftedStep(
                        "step_001",
                        "When",
                        SegmentRole.test_step,
                        "the tester adds an item",
                        ["evt_001", "evt_002"],
                        expects=[DraftedExpectation(text=claim, event_id=event_id)],
                    )
                ],
            )
        ],
    )


def test_the_cheap_pass_declines_a_half_proved_claim_rather_than_binding_it(tmp_path: Path):
    # The whole defect, end to end. "Small Wicker Basket" is a conclusive
    # literal -- three content tokens, coverage 1.0 -- so the deterministic
    # pass would settle this without a model call and the gate would agree.
    #
    # It must reach the agent instead, which can look at what the number was
    # counting and either find a literal covering the sentence or revise the
    # sentence down to what it can prove. That is retrieval effort landing on a
    # hard claim, which is SS3.3's whole argument.
    store, runner = _store_and_runner(tmp_path, "heading", "Small Wicker Basket")

    # The retrieval is scripted too, because a literal the agent did not
    # actually receive is unsupported however true it is -- `_resolve_call` is
    # the point at which fabrication stops being possible, and a test that
    # skipped the call would be testing a path no real run takes.
    model = ScriptedModelClient(
        [
            calls(("get_snapshot", {"eventId": "evt_002", "when": "after"})),
            answer(
                json.dumps(
                    {
                        "verdict": "revise",
                        "text": 'the hamper is shown as a "Small Wicker Basket"',
                        "literal": "Small Wicker Basket",
                        "eventId": "evt_002",
                        "kind": "semantic_node",
                        "reason": "the capacity was not on the page at this event",
                    }
                )
            ),
        ]
    )

    claim = 'the hamper is shown as a "Small Wicker Basket" with a capacity of "5 / 5"'
    result = bind_claims(store, runner, model, _drafted(claim), model_name="test")

    # It went to the agent rather than being settled cheaply...
    assert result.claims[0].investigation is not None
    # ...and what survives says only what the recording showed.
    assert result.bound == 1
    assert "5 / 5" not in result.claims[0].text


def test_an_agent_may_not_bind_a_half_proved_claim_either(tmp_path: Path):
    # Enforced twice, for the reason `critic._collect` and `repair.targets`
    # both enforce the protected-step rule: the bind prompt now states this,
    # and a prompt that asks is not a guarantee. An agent handed a two-part
    # claim will quote the part it found and call the verdict `bind`.
    store, runner = _store_and_runner(tmp_path, "heading", "Small Wicker Basket")

    model = ScriptedModelClient(
        [
            calls(("get_snapshot", {"eventId": "evt_002", "when": "after"})),
            answer(
                json.dumps(
                    {
                        "verdict": "bind",
                        "literal": "Small Wicker Basket",
                        "eventId": "evt_002",
                        "kind": "semantic_node",
                        "reason": "the basket is named on the page",
                    }
                )
            ),
        ]
    )

    claim = 'the hamper is shown as a "Small Wicker Basket" with a capacity of "5 / 5"'
    result = bind_claims(store, runner, model, _drafted(claim), model_name="test")

    assert result.bound == 0
    assert "5 / 5" in result.claims[0].reason


def test_a_navigation_claim_is_refused_before_a_retrieval_is_spent(tmp_path: Path):
    # `runs/rec_MT7VTN7ZRJPO/run_001` closed its scenario on this, bound to the
    # panel's own heading. No model call is made: there is no answer an agent
    # could give that would make the claim worth having, so spending a call
    # would be spending it to arrive here anyway.
    store, runner = _store_and_runner(tmp_path, "heading", "Shopping Bag")
    model = ScriptedModelClient([])

    claim = "the shopping bag panel opens, displaying the item(s) previously added to the cart"
    result = bind_claims(store, runner, model, _drafted(claim), model_name="test")

    assert result.bound == 0
    assert not runner.calls
    assert "browser" in result.claims[0].reason


def test_a_fully_witnessed_claim_still_costs_no_model_call(tmp_path: Path):
    # The other side of the trade, and the reason the rule is about quoted
    # values and numbers rather than about coverage. Most claims are honest and
    # must stay cheap: a fix that pushed every claim to the agent would raise
    # calls/step by fiat and flatten SS3.3's Spread, which is the failure
    # mandatory search-before-invent already demonstrated once.
    store, runner = _store_and_runner(tmp_path, "alert", "Order confirmed")
    model = ScriptedModelClient([])

    result = bind_claims(
        store, runner, model, _drafted("the order is confirmed"), model_name="test"
    )

    assert result.bound == 1
    assert result.claims[0].assertion.evidence.literal == "Order confirmed"
    # The cheap pass still retrieves and hashes -- that is what makes the claim
    # admissible -- but it asks nobody. `ScriptedModelClient` would raise if it
    # had been called at all, so this states the invariant the name promises.
    assert not model.requests
    assert not result.model_calls


# --------------------------------------------------------------------------
# the pass that was already there
# --------------------------------------------------------------------------


def test_the_deterministic_pass_reads_only_what_the_event_changed(tmp_path: Path):
    # SS9.5, and the reason `_candidates` is built from the diff: without it
    # the cheap pass binds a claim to any string on the page sharing enough
    # words with it, and the page is full of them. It bound "a file containing
    # the order details is downloaded" to `Export the order` -- the label on
    # the button the tester had just pressed, unchanged by the click, and the
    # export had returned a 500.
    store, _ = _store_and_runner(tmp_path, "alert", "Order confirmed")

    # Present at the event and changed by it.
    assert _best_literal(store, "evt_002", "the order is confirmed") is not None
    # Present in the recording, but nothing about this event changed it.
    assert _best_literal(store, "evt_002", "the tester signs in") is None


def test_a_literal_too_short_to_mean_anything_is_not_evidence():
    # "5" appears on every page that has ever had a number on it. MIN_LITERAL
    # is the floor under that, and it is stated here so a later change to the
    # constant has to be a deliberate one.
    assert MIN_LITERAL >= 3
    assert 0.0 < COVERAGE_FLOOR <= 1.0
