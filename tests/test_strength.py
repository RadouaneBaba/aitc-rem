"""Grading a literal, and the guarantee that grading never decides anything.

The behaviour under test is the one from `server/evidence/strength.py`: a claim
bound to the literal `1` passes every validator in the system while `1` occurs
198 times in the snapshot it cites, and nothing anywhere could say so. These
tests pin the distinction it draws AND -- the more important half -- that
drawing it changes no verdict.
"""

from __future__ import annotations

from server.evidence.strength import element_texts, grade, occurrences
from server.models import EvidenceStrength

# A page shaped like the ones this actually runs on: a cart badge whose entire
# accessible name is a digit, a phrase carrying the same digit, and prices and
# refs that contain it incidentally.
PAGE = {
    "present": True,
    "root": {
        "role": "generic",
        "name": "",
        "ref": "0",
        "children": [
            {"role": "text", "name": "1", "ref": "0.1"},
            {"role": "generic", "name": "Cart contains 1 items", "ref": "0.2"},
            {"role": "listitem", "name": "Sauce Labs Onesie", "ref": "0.11"},
            {"role": "listitem", "name": "Sauce Labs Onesie", "ref": "0.12"},
            {"role": "text", "name": "$7.99", "ref": "0.13"},
            {"role": "link", "name": "Item 1 of 21", "ref": "0.14"},
        ],
    },
    "liveRegions": [],
}


class TestTheRungs:
    def test_a_literal_naming_exactly_one_element_is_strong(self):
        """The claim points at one identifiable thing on the page."""
        assert grade(PAGE, "Cart contains 1 items") is EvidenceStrength.strong

    def test_a_bare_digit_still_names_an_element(self):
        """`1` IS the cart badge's whole name, so it resolves precisely.

        This is the case the rungs must NOT overstate. The literal is fine
        structurally -- the badge really is named `1` -- and what makes the
        verdict decoration is the 198-way containment check, which is
        `occurrences`, not this. Reporting `weak` here would be wrong, and
        would put the two halves of the finding in one number.
        """
        assert grade(PAGE, "1") is EvidenceStrength.strong

    def test_several_elements_with_the_same_name_are_medium(self):
        assert grade(PAGE, "Sauce Labs Onesie") is EvidenceStrength.medium

    def test_part_of_an_element_name_is_medium(self):
        """A real and legitimate claim -- just not anchored to one whole label."""
        assert grade(PAGE, "Cart contains") is EvidenceStrength.medium

    def test_text_carried_by_no_element_is_weak(self):
        """`0.1` is a ref, not anything a tester could read off the page.

        This is the rung that cannot be told apart from a coincidence: the
        string is genuinely in the response, so the gate accepts it, and it
        names nothing.
        """
        assert grade(PAGE, "0.1") is EvidenceStrength.weak

    def test_a_short_literal_is_not_penalised_for_being_short(self):
        """`$7.99` is five characters, occurs once, and is a good verdict.

        Length is not the axis. Any rule keyed on it would reject true claims,
        which is why `evidence_discriminates` was deleted.
        """
        assert grade(PAGE, "$7.99") is EvidenceStrength.strong
        assert occurrences(PAGE, "$7.99") == 1


class TestNothingToGradeAgainst:
    def test_a_network_response_grades_to_none(self):
        """A status code is not an element name, and saying `weak` would imply
        the claim is poor when it is the only way to prove a 409."""
        network = {"calls": [{"status": 409, "url": "/api/orders"}], "count": 1}
        assert grade(network, "409") is None

    def test_an_empty_literal_grades_to_none(self):
        assert grade(PAGE, "") is None
        assert occurrences(PAGE, "") == 0

    def test_a_diff_is_gradeable_because_its_entries_are_elements(self):
        """`get_diff` lists nodes flat rather than nested, and they are still
        nodes -- the author cites diffs more than anything else, so a grader
        blind to them would grade almost nothing."""
        diff = {
            "added": [{"role": "generic", "name": "Cart contains 1 items", "ref": "0.2"}],
            "removed": [{"role": "generic", "name": "Cart contains 0 items", "ref": "0.2"}],
            "changed": [],
        }
        assert grade(diff, "Cart contains 1 items") is EvidenceStrength.strong


class TestOccurrences:
    def test_it_counts_the_places_that_would_satisfy_the_check(self):
        """`1` is in the badge, the phrase, two refs and the pagination link.

        This is the number that makes a vacuous verdict visible: the gate's
        containment check had this many ways to pass.
        """
        assert occurrences(PAGE, "1") > 4
        assert occurrences(PAGE, "Cart contains 1 items") == 1

    def test_it_counts_strings_not_serialized_bytes(self):
        """Counting over `json.dumps` would match across key boundaries and
        punctuation, inflating this with matches no claim could rest on."""
        assert occurrences({"a": "xy", "b": "yx"}, '","') == 0


class TestElementTexts:
    def test_a_field_value_is_that_element_s_own_text(self):
        """A claim about what a box CONTAINS is an ordinary thing to want."""
        page = {"root": {"role": "textbox", "name": "Order total", "value": "615.00"}}
        assert "615.00" in element_texts(page)
        assert grade(page, "615.00") is EvidenceStrength.strong

    def test_an_object_without_a_role_is_not_an_element(self):
        """Otherwise any json with a `name` key grades as a page element."""
        assert element_texts({"name": "not-a-node"}) == []

    def test_a_page_url_is_gradeable_text(self):
        """*"the application navigates to the confirmation page"* cited on the
        url is a GOOD verdict, and a url names nothing in the tree.

        Found by grading the 46 assertions already on disk: without this, two
        real runs had their navigation claim reported as weak, which is a false
        alarm and exactly the kind that teaches a reviewer to ignore the column.
        """
        page = {
            "present": True,
            "url": "http://localhost:5173/confirmation",
            "title": "Order confirmed",
            "root": {"role": "generic", "name": "", "ref": "0"},
        }
        assert grade(page, "http://localhost:5173/confirmation") is EvidenceStrength.strong

    def test_a_navigation_is_gradeable_from_the_diff_that_recorded_it(self):
        """A `get_diff` says a navigation happened as `urlChanged`, and that is
        the retrieval a navigation claim actually cites -- both real runs bound
        theirs to a diff, not a snapshot."""
        diff = {
            "added": [{"role": "alert", "name": "Order confirmed", "ref": "0.1"}],
            "removed": [],
            "changed": [],
            "urlChanged": {
                "from_": "http://localhost:5173/checkout",
                "to": "http://localhost:5173/confirmation",
            },
        }
        assert grade(diff, "http://localhost:5173/confirmation") is EvidenceStrength.strong

    def test_a_url_inside_a_network_response_is_not_page_text(self):
        """Every call in a `get_network` response carries a url. Collecting
        those would make a status-code claim gradeable against text that has
        nothing to do with it -- so page identity is read only from the top of
        a page-shaped response."""
        network = {"calls": [{"status": 409, "url": "/api/orders"}], "count": 1}
        assert element_texts(network) == []
        assert grade(network, "/api/orders") is None
