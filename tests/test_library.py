"""The step library (SS12).

    "The number-one reason generated-Gherkin tools get abandoned. Ten testers
     record ten sessions and you get ten phrasings of one action."

These tests are about the two things that make a library useful rather than
dangerous: it finds the phrasing you already agreed on, and it refuses to
substitute wording that would change what the step claims.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from server.library import REUSE_THRESHOLD, StepLibrary


@pytest.fixture
def library(tmp_path: Path) -> StepLibrary:
    lib = StepLibrary(tmp_path / "library.db")
    for text in (
        'the tester signs in as "<<user_email_1>>" with "<<password>>"',
        "the tester adds a Blue Widget to the cart",
        "the tester places the order",
    ):
        lib.add(text)
    return lib


def top(library: StepLibrary, query: str):
    matches = library.search(query, limit=1)
    return matches[0] if matches else None


# --------------------------------------------------------------------------
# finding what you already said
# --------------------------------------------------------------------------


def test_the_same_step_worded_the_same_way_is_recommended_for_reuse(library: StepLibrary):
    match = top(library, "the tester places the order")
    assert match is not None
    assert match.reuse


def test_a_step_nobody_has_approved_finds_nothing_worth_reusing(library: StepLibrary):
    match = top(library, "the tester downloads the invoice as a PDF")
    assert match is None or not match.reuse


def test_the_voice_prefix_is_not_a_similarity(library: StepLibrary):
    # Every step in a project starts "the tester ", so scoring the raw sentence
    # gives every pair a long identical head. Measured before this was fixed,
    # "signs in" scored 85 against "adds a Blue Widget to the cart" -- which is
    # not a resemblance, it is a shared prefix, and at that level everything
    # looks like everything.
    match = top(library, "the tester proceeds to checkout")
    assert match is None or match.score < REUSE_THRESHOLD


# --------------------------------------------------------------------------
# refusing to change what a step says
# --------------------------------------------------------------------------


def test_a_repeat_is_not_the_same_step_however_similar_it_looks(library: StepLibrary):
    # "places the order" and "places the order again" score 95. The second is
    # exactly what the naming stage writes to mark a deliberate repeat, so
    # substituting one for the other would erase the distinction it exists to
    # draw -- and the test would then claim the order was placed once.
    match = top(library, "the tester places the order again")
    assert match is not None
    assert match.score >= REUSE_THRESHOLD
    assert not match.reuse


def test_reuse_is_refused_when_the_quoted_values_differ(library: StepLibrary):
    # SS7.2 makes quoted values the test's parameters. Reusing an entry that
    # quotes values the drafted step does not would add parameters nobody
    # supplied.
    match = top(library, "the tester signs in")
    assert match is not None
    assert not match.reuse


def test_a_recommendation_is_never_an_automatic_rewrite(library: StepLibrary):
    # "adds a widget to the cart" scores 95 against the approved "adds a Blue
    # Widget to the cart", and the widget may not have been blue. The library
    # offers; only something looking at the recording can decide. Nothing in
    # `search` mutates anything, which is what keeps that true.
    before = [e.text for e in library.entries()]
    library.search("the tester adds a widget to the cart")
    assert [e.text for e in library.entries()] == before


# --------------------------------------------------------------------------
# the store
# --------------------------------------------------------------------------


def test_an_entry_id_is_stable_across_processes(tmp_path: Path):
    # Python salts string hashing per process, so an id built with hash() would
    # differ between runs and `libraryRef` would stop resolving across exactly
    # the session boundary this library exists to cross.
    first = StepLibrary(tmp_path / "a.db").add("the tester signs in")
    second = StepLibrary(tmp_path / "b.db").add("the tester signs in")
    assert first is not None and second is not None
    assert first.id == second.id


def test_approving_the_same_wording_again_counts_a_use(library: StepLibrary):
    # When two entries score alike, the one more people have already accepted
    # is the better one to converge on.
    again = library.add("the tester places the order")
    assert again is not None
    assert again.uses == 2


def test_exact_is_what_sets_a_reuse_claim(library: StepLibrary):
    # `libraryRef` records "this step IS that entry". Fuzzy matching here would
    # make `library_verbatim` -- which rejects a step that claims reuse and was
    # then rewritten -- unable to fail.
    assert library.exact("the tester places the order") is not None
    assert library.exact("the tester places the order again") is None
    assert library.exact("  the tester   places the order  ") is not None


def test_an_empty_library_answers_nothing_rather_than_failing(tmp_path: Path):
    lib = StepLibrary(tmp_path / "empty.db")
    assert lib.search("the tester signs in") == []
    assert lib.exact("the tester signs in") is None
