"""Importing a Chrome DevTools Recorder export (SS11, SS7.1).

Two things are being tested, and the second matters more than the first.

The mapping works because Chrome's Recorder emits `aria/Name` selectors -- an
accessible-name strategy, which is this project's own primary key. So a
recording somebody already made can come in.

And the *consequence* of importing is visible rather than papered over. A
DevTools recording carries no network, no console and no DOM, so there is
nothing for `find_text` to index and no assertion can be grounded. The
admissibility rule (SS3.2) then does exactly what it should: the tool makes no
claim rather than a weaker one.
"""

from __future__ import annotations

from server.importers import import_devtools


def doc(*steps, title: str = "Sign in and add a widget") -> dict:
    return {
        "title": title,
        "steps": [
            {"type": "setViewport", "width": 1280, "height": 720},
            {"type": "navigate", "url": "http://localhost:5173/"},
            *steps,
        ],
    }


def click(name: str, css: str = "button.primary") -> dict:
    return {"type": "click", "selectors": [[f"aria/{name}"], [css]]}


# --------------------------------------------------------------------------
# the mapping
# --------------------------------------------------------------------------


def test_an_aria_selector_becomes_the_accessible_name():
    # The reason this import is worth doing at all: Chrome records the
    # accessible name, and role+name is what every other stage of this pipeline
    # describes a step by.
    recording = import_devtools(doc(click("Sign in")))
    assert recording.events[0].target.name == "Sign in"
    assert recording.events[0].target.selectors.css == "button.primary"


def test_no_role_selector_is_invented():
    # Chrome records the name but not the role. `getByRole('', { name: ... })`
    # is a selector that cannot resolve, and a fallback chain containing one is
    # worse than a shorter chain -- a replay spends a timeout on it first.
    recording = import_devtools(doc(click("Sign in")))
    assert recording.events[0].target.selectors.role is None
    assert recording.events[0].target.role == ""


def test_navigation_sets_the_url_rather_than_becoming_a_step():
    # A navigate is where the tester was, not something they were trying to do.
    recording = import_devtools(doc(click("Sign in")))
    assert len(recording.events) == 1
    assert recording.metadata.startUrl == "http://localhost:5173/"
    assert recording.metadata.origins == ["http://localhost:5173"]


def test_events_are_spaced_past_the_idle_gap():
    # Chrome records no timing, so order is all there is. Spacing them past the
    # segmenter's idle-gap threshold is the honest default: pretending actions
    # were close together would manufacture step boundaries nobody observed.
    recording = import_devtools(doc(click("Sign in"), click("Add to cart", "button.add")))
    times = [e.timestamp for e in recording.events]
    assert len(times) == 2
    assert times[1] - times[0] >= 2000


# --------------------------------------------------------------------------
# SS7.1 -- redaction, on a path the browser never touched
# --------------------------------------------------------------------------


def test_a_password_never_reaches_disk_in_the_clear():
    # Redaction normally happens in the browser before anything is persisted,
    # and Chrome's Recorder does no such thing: it writes what was typed. An
    # importer that carried that through would put a plaintext secret on disk
    # via a path the rule exists to make impossible.
    recording = import_devtools(
        doc({"type": "change", "value": "hunter2", "selectors": [["aria/Password"], ["#password"]]})
    )
    assert recording.events[0].target.value == "<<password>>"
    assert "hunter2" not in recording.model_dump_json()


def test_an_email_becomes_a_parameter_rather_than_a_value():
    # SS7.2 -- the placeholder is more useful than the value it replaced,
    # because whoever runs the test supplies their own.
    recording = import_devtools(
        doc(
            {
                "type": "change",
                "value": "tester@example.com",
                "selectors": [["aria/Email address"], ["#email"]],
            }
        )
    )
    assert recording.events[0].target.value == "<<user_email_1>>"
    assert [p.placeholder for p in recording.parameters] == ["<<user_email_1>>"]


def test_an_ordinary_value_is_left_alone():
    # Redaction that eats the order total would destroy the assertion the test
    # case exists to make.
    recording = import_devtools(
        doc({"type": "change", "value": "615", "selectors": [["aria/Order total"], ["#total"]]})
    )
    assert recording.events[0].target.value == "615"
    assert recording.parameters == []


# --------------------------------------------------------------------------
# what an import cannot bring
# --------------------------------------------------------------------------


def test_an_imported_recording_carries_no_evidence_to_ground_a_claim():
    # Not a limitation to work around -- it is the admissibility rule (SS3.2)
    # having something to bite on. With no snapshot nodes there is nothing for
    # `find_text` to index, so an assertion about page content cannot be made
    # at all, and `gherkin_style` says the result reads as a transcript.
    recording = import_devtools(doc(click("Sign in")))
    event = recording.events[0]
    assert event.network == []
    assert event.console == []
    assert event.after.root.children == []


def test_the_import_degrades_loudly():
    # SS6.8: a tool that admits what it does not know stays trusted.
    recording = import_devtools(doc(click("Sign in")))
    flags = [f.value for f in recording.events[0].fidelity]
    assert "network_incomplete" in flags
    assert recording.metadata.fidelitySummary


def test_an_element_with_no_accessible_name_says_so():
    recording = import_devtools(doc({"type": "click", "selectors": [["div.icon"]]}))
    flags = [f.value for f in recording.events[0].fidelity]
    assert "no_accessible_name" in flags
