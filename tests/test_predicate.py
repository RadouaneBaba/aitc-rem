"""What a claim SAYS, checked against what the retrieval shows.

The gate was substring containment and nothing else, so a sentence saying FIRST
was proved by a check saying PRESENT:

    Then the first product is 'The Autumnal Hamper' priced at £120.00

shipped on nothing more than that string being somewhere in the response. Every
test here is a sentence the old gate could not tell apart from a true one.
"""

from __future__ import annotations

import json

import pytest

from server.evidence.predicate import Outcome, evaluate
from server.evidence.tools import MAX_SNAPSHOT_NODES, get_snapshot, snapshot_view
from server.models import NodeRef, Predicate, PredicateForm
from tests import factories as f


def products(*names: str) -> dict:
    """A snapshot response shaped exactly as `get_snapshot` returns one.

    The wrapper `group` nodes are the point: they carry no name, so `_rank`
    sorts them to the BACK, which is what makes evaluating a positional claim
    against a ranked or capped view answer the wrong question.
    """
    return {
        "eventId": "evt_001",
        "when": "after",
        "present": True,
        "url": "https://shop.local/halloween",
        "root": {
            "ref": "0",
            "role": "main",
            "name": "Halloween",
            "children": [
                {
                    "ref": "0.0",
                    "role": "list",
                    "name": "Products",
                    "children": [
                        {
                            "ref": f"0.0.{i}",
                            "role": "listitem",
                            "name": "",
                            "children": [{"ref": f"0.0.{i}.0", "role": "link", "name": name}],
                        }
                        for i, name in enumerate(names)
                    ],
                }
            ],
        },
        "liveRegions": [],
    }


LIST = NodeRef(role="list", name="Products")


@pytest.fixture
def storage(tmp_path):
    from server.storage.paths import Storage

    return Storage(recordings_dir=tmp_path / "recordings", runs_dir=tmp_path / "runs")


@pytest.fixture
def run_paths(storage):
    return storage.run("rec_test01", "run_test")


# --------------------------------------------------------------------------
# first_of -- the form the sorting recording needed and could not express
# --------------------------------------------------------------------------


def test_first_of_is_true_only_when_the_literal_is_actually_first():
    response = products("The Autumnal Hamper", "Lucifer's Marmalade, 200g")
    predicate = Predicate(form=PredicateForm.first_of, container=LIST)

    assert evaluate(response, "The Autumnal Hamper", predicate).outcome is Outcome.true


def test_first_of_is_false_when_the_literal_is_merely_present():
    # The whole reason this module exists. Under plain containment this claim
    # passed, and it would have passed on a build with sorting removed.
    response = products("Lucifer's Marmalade, 200g", "The Autumnal Hamper")
    predicate = Predicate(form=PredicateForm.first_of, container=LIST)

    verdict = evaluate(response, "The Autumnal Hamper", predicate)
    assert verdict.outcome is Outcome.false
    # And it says which one WAS first, so the author can write the true sentence.
    assert "Lucifer's Marmalade" in verdict.why


def test_first_of_reaches_through_a_nameless_wrapper():
    # A list item that is a div around a link is layout, not position. Requiring
    # the literal on the wrapper itself would refuse every real product grid.
    response = products("The Autumnal Hamper")
    assert evaluate(
        response, "The Autumnal Hamper", Predicate(form=PredicateForm.first_of, container=LIST)
    ).holds


def test_first_of_cannot_be_evaluated_when_the_container_was_not_retrieved():
    response = products("The Autumnal Hamper")
    predicate = Predicate(form=PredicateForm.first_of, container=NodeRef(role="table", name="Cart"))

    verdict = evaluate(response, "The Autumnal Hamper", predicate)
    # Neither true nor false. Passing would put a green badge on an unchecked
    # claim; rejecting would kill true claims whenever a shape changed.
    assert verdict.outcome is Outcome.cannot_evaluate
    assert verdict.unresolved and not verdict.holds
    assert "not in this retrieval" in verdict.why


def test_a_positional_claim_against_a_diff_is_unresolved_rather_than_false():
    # A diff is a list of changed nodes with no tree between them, so it cannot
    # answer a question about order. Saying "false" would tell the author its
    # sentence was wrong when the truth is that it cited the wrong retrieval.
    diff = {"eventId": "evt_001", "summary": {"added": 3, "removed": 0, "changed": 0}, "added": []}
    verdict = evaluate(
        diff, "The Autumnal Hamper", Predicate(form=PredicateForm.first_of, container=LIST)
    )
    assert verdict.outcome is Outcome.cannot_evaluate


# --------------------------------------------------------------------------
# the capping trap -- constraint 2, and the reason for the store/view split
# --------------------------------------------------------------------------


def test_first_of_evaluated_against_a_view_would_answer_a_different_question():
    """The trap this design exists to avoid, demonstrated rather than asserted.

    `_rank` puts NAMED nodes first. If a snapshot were capped the way a diff is
    and the predicate then read that capped value, `first_of` would report the
    first *named* node -- and in a product grid the nameless wrappers holding
    each item are exactly what ranks to the back. So the full response is what
    is stored and what every predicate reads; the narrowing is display only.
    """
    from server.evidence.tools import _rank

    response = products("The Autumnal Hamper", "Lucifer's Marmalade, 200g")
    items = response["root"]["children"][0]["children"]

    # Ranked, the unnamed list items are pushed behind anything with a name --
    # so "the first item" under a ranking is not the first item on the page.
    ranked, _hidden = _rank([{"ref": i["ref"], "role": i["role"], "name": i["name"]} for i in items])
    assert all(not r["name"] for r in ranked), "these are the nodes a rank would demote"

    # The stored response is untouched and still answers the real question.
    assert evaluate(
        response, "The Autumnal Hamper", Predicate(form=PredicateForm.first_of, container=LIST)
    ).holds


def test_the_view_narrows_what_the_model_sees_and_never_what_is_stored():
    wide = products(*[f"Product {i}" for i in range(MAX_SNAPSHOT_NODES)])
    view = snapshot_view(wide)

    assert view is not wide
    assert view["nodesTotal"] > MAX_SNAPSHOT_NODES
    assert view["nodesShown"] <= MAX_SNAPSHOT_NODES
    # The count is always the real one. "How big was the page" and "what was on
    # it" are different questions and the first must not depend on a budget.
    assert view["nodesTotal"] == 2 + 2 * MAX_SNAPSHOT_NODES
    # And it is a document-order PREFIX, never a re-sort: the first product is
    # still the first product.
    assert evaluate(
        view, "Product 0", Predicate(form=PredicateForm.first_of, container=LIST)
    ).holds


def test_a_small_page_is_handed_over_untouched():
    small = products("One", "Two")
    assert snapshot_view(small) is small


def test_the_runner_stores_the_whole_response_and_returns_the_view(storage, run_paths):
    """The split, end to end: the hash covers the page, the model gets a prefix."""
    from server.evidence.store import EvidenceStore
    from server.evidence.tools import ToolRunner
    from server.util.canonical import response_hash

    root = f.node(
        "0",
        "main",
        "Wide",
        children=[f.node(f"0.{i}", "listitem", f"Item {i}") for i in range(MAX_SNAPSHOT_NODES + 50)],
    )
    recording = f.recording(events=[f.event("evt_001", 0, after=f.snapshot(root=root))])
    runner = ToolRunner(store=EvidenceStore(recording=recording), storage=storage, run=run_paths)

    call_id, seen = runner.call("get_snapshot", {"eventId": "evt_001"})

    stored = storage.load_tool_response(run_paths, call_id)
    full = get_snapshot(EvidenceStore(recording=recording), "evt_001")

    assert stored == json.loads(json.dumps(full)), "what is persisted is the whole retrieval"
    assert runner.calls[0].responseHash == response_hash(full), "and the hash covers all of it"
    assert seen != stored, "and the model was handed less than that"
    assert seen["nodesShown"] == MAX_SNAPSHOT_NODES


# --------------------------------------------------------------------------
# count and absent
# --------------------------------------------------------------------------


def test_count_checks_the_number_the_feature_computes():
    response = products(*[f"Product {i}" for i in range(9)])
    predicate = Predicate(form=PredicateForm.count, container=LIST, role="listitem", n=9)

    assert evaluate(response, "Showing 9 of 24 products", predicate).holds


def test_count_is_false_at_the_wrong_number_even_though_the_text_is_present():
    # The literal is in the response either way -- it is the page's own summary
    # line. Only the count separates the working filter from the broken one.
    response = products(*[f"Product {i}" for i in range(24)])
    predicate = Predicate(form=PredicateForm.count, container=LIST, role="listitem", n=9)

    verdict = evaluate(response, "Product 0", predicate)
    assert verdict.outcome is Outcome.false
    assert "24" in verdict.why


def test_count_without_a_number_is_unresolved():
    predicate = Predicate(form=PredicateForm.count, container=LIST)
    assert evaluate(products("One"), "One", predicate).outcome is Outcome.cannot_evaluate


def test_absent_is_true_only_against_a_retrieval_of_the_whole_page():
    response = products("Lucifer's Marmalade, 200g")

    assert evaluate(
        response, "Out of stock", Predicate(form=PredicateForm.absent)
    ).outcome is Outcome.true
    assert evaluate(
        response, "Lucifer's Marmalade, 200g", Predicate(form=PredicateForm.absent)
    ).outcome is Outcome.false


def test_absent_against_a_response_with_no_page_in_it_is_unresolved():
    # An empty or non-page response satisfies "absent" for every string in the
    # language. Treating that as proof would make the form worthless.
    network = {"eventId": "evt_001", "count": 0, "calls": []}
    verdict = evaluate(network, "Out of stock", Predicate(form=PredicateForm.absent))
    assert verdict.outcome is Outcome.cannot_evaluate


# --------------------------------------------------------------------------
# the default
# --------------------------------------------------------------------------


@pytest.mark.parametrize("predicate", [None, Predicate(form=PredicateForm.contains)])
def test_no_predicate_means_exactly_what_it_always_meant(predicate):
    # Every assertion written before this module existed carries no predicate,
    # and must keep meaning containment or the change is a silent regression
    # across every run on disk.
    response = products("The Autumnal Hamper", "Lucifer's Marmalade, 200g")

    assert evaluate(response, "Lucifer's Marmalade, 200g", predicate).holds
    assert not evaluate(response, "A thing nobody sold", predicate).holds
