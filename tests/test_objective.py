"""The objective, on the way in to the model.

The recorder coaches the tester as they type (`objective.ts`); this decides
whether the sentence they typed is shown to the author at all. The two must
agree, so the cases below are the ones `objective.test.ts` runs, and they are
the real objectives on disk labelled by the verdict the judge gave the run each
one produced.

The measured fact underneath: **a vague objective is worse than none.** Four of
four vague ones produced output the judge called bad; five of five sharp ones
were acceptable. A vague objective names a mechanism, and the mechanism is what
the test then gets written about instead of the outcome.
"""

from __future__ import annotations

import pytest

from server.pipeline.objective import coach, usable

#: Real objectives whose runs the judge scored `good` or `needs-work`.
SHARP = [
    "Check that an order over EUR500 requires approval",
    "Check that adding an item updates the cart badge",
    "Check that an order can be exported after approval",
    "Check the cart badge, then that a large order needs approval",
    # docs/RECORDING.md's own worked examples of a good objective.
    "Check that removing the last item empties the cart",
    "Check that an expired card is rejected at payment",
    "Check that a hamper cannot be upgraded past the largest size",
]

#: Real objectives whose runs the judge scored `bad`.
VAGUE = [
    "check if hamper sizes change correctly",
    "check if filters are working correctly",
    "check if i can add cafe products correctly to the bag",
    "I will test if I can add the coffee products correctly to the cart",
    "Exercise the awkward parts of the checkout page",
    # docs/RECORDING.md's own worked examples of a bad objective.
    "Test the checkout page",
    "Cart stuff",
    "Payment flow",
    "Verify the checkout handles slow server-side validation",
    # The coffee session that prompted this work.
    "Check that coffee products can be added correctly to the bag",
]


@pytest.mark.parametrize("text", SHARP)
def test_a_sharp_objective_reaches_the_model_unchanged(text):
    # A checker that flags a GOOD objective is a nag, a nag gets ignored, and an
    # ignored coach is worse than none because it occupies the space where a
    # working one would go. These are the cases that matter.
    assert coach(text).verdict == "sharp"
    assert usable(text) == text


@pytest.mark.parametrize("text", VAGUE)
def test_a_vague_objective_is_not_shown_to_the_model(text):
    assert coach(text).verdict == "vague"
    assert usable(text) == ""


@pytest.mark.parametrize("empty", ["", "   ", "\n", None])
def test_an_empty_box_is_left_alone(empty):
    # Blank beats vague, measured. Nagging someone who left it empty would push
    # them toward the worse of the two.
    assert coach(empty).verdict == "empty"
    assert usable(empty) == ""


def test_an_objective_describing_actions_still_reaches_the_model():
    """`actions` is weaker than a proposition, and it is not misleading.

    "Sign in and add a widget" describes what the tester did rather than what
    they were checking. That is worth coaching in the popup -- the recorder can
    already see the actions -- but it is true, it is theirs, and it names the
    part of the session they cared about. Only `vague` actively steers the test
    at the wrong thing, so only `vague` is dropped.
    """
    text = "Sign in and add a widget"
    assert coach(text).verdict == "actions"
    assert usable(text) == text


def test_the_recording_keeps_the_sentence_the_tester_typed():
    # This module decides what the MODEL sees. The recorder must never rewrite
    # what was typed (SS6.7), and a recording already on disk has to keep
    # meaning what it meant when it was made.
    from server.evidence.store import EvidenceStore
    from tests import factories as f

    vague = "check if filters are working correctly"
    store = EvidenceStore(recording=f.recording(objective=vague))

    assert store.objective == vague
    assert usable(store.objective) == ""


def test_the_digest_shows_a_sharp_objective_and_hides_a_vague_one():
    from server.evidence.store import EvidenceStore
    from server.pipeline.digest import build_digest
    from tests import factories as f

    sharp = "Check that adding an item updates the cart badge"
    events = [f.event("evt_001", 0, at=0.0)]

    shown = build_digest(EvidenceStore(recording=f.recording(events=events, objective=sharp)))
    hidden = build_digest(
        EvidenceStore(recording=f.recording(events=events, objective="Cart stuff"))
    )

    assert sharp in shown.text
    assert "objective" in shown.text
    assert "Cart stuff" not in hidden.text
