"""The session index (SS9.3).

`digest.py` is the only thing the drafter reads. Everything the author knows
about the session -- what was clicked, what changed, what the tester said and
where they declared a new test case -- reaches it through this text and nowhere
else, so an omission here is not a formatting bug: it is the author not being
told.

That is not hypothetical. A `scenario_break` carries no `eventId`, so the loop
over `event.annotations` never saw one, and `twoflows` -- the fixture that
exists to prove two test cases come out of one recording -- shipped a single
scenario with both flows inside it. The index said nothing and the deterministic
net behind it then correctly declined to cut through the middle of a step.

Covered here rather than end to end, because through a cassette a missing line
in the index looks exactly like a model that wrote a bad document.
"""

from __future__ import annotations

from server.evidence.store import EvidenceStore
from server.models import (
    ConsoleEntry,
    DiffNode,
    NarrationSegment,
    RedactionParameter,
    SnapshotDiff,
)
from server.pipeline.digest import (
    IDLE_HINT_MS,
    _recurring_labels,
    build_digest,
    typed_parameters,
)
from tests import factories as f

CASE_MARKER = "THE TESTER DECLARED A NEW TEST CASE HERE"


def digest_of(*events, **recording_kw) -> str:
    recording = f.recording(events=list(events), **recording_kw)
    return build_digest(EvidenceStore(recording=recording)).text


def at(ident: str, seq: int, ms: float, **kw):
    return f.event(ident, seq=seq, at=ms, **kw)


# --------------------------------------------------------------------------
# the header -- what frames everything below it
# --------------------------------------------------------------------------


def test_the_header_states_the_session_before_any_event():
    text = digest_of(
        at("evt_001", 0, 0.0),
        at("evt_002", 1, 3000.0),
        objective="Check that a large order needs approval",
    )

    head, _, _ = text.partition("EVENTS")
    assert "events      2" in head
    assert "duration    3.0s" in head
    # SS9.5 ranks the tester's own words above anything the pipeline infers, so
    # the objective frames the index rather than sitting in an event block
    # halfway down it.
    assert "objective   Check that a large order needs approval" in head


def test_a_recording_with_no_objective_simply_does_not_mention_one():
    head, _, _ = digest_of(at("evt_001", 0, 0.0)).partition("EVENTS")
    assert "objective" not in head


def test_every_event_appears_in_the_index():
    # `event_coverage` makes the drafter account for each one, and it can only
    # account for what it was shown.
    text = digest_of(*(at(f"evt_{i:03d}", i - 1, float(i * 100)) for i in range(1, 6)))
    for i in range(1, 6):
        assert f"evt_{i:03d}" in text


# --------------------------------------------------------------------------
# parameters -- a placeholder is not automatically a test parameter
# --------------------------------------------------------------------------


def test_only_a_placeholder_the_tester_actually_typed_is_published_as_a_parameter():
    # Redaction runs over every request and response body on every origin,
    # which is right. But a placeholder minted inside an analytics beacon is
    # not a test parameter, and the commercial recording produced eleven --
    # numeric strings in tracking payloads that matched the phone pattern,
    # published to the tester as values they must supply. None of them exist.
    typed = f.event("evt_001", tgt=f.target(value="<<user_email_1>>"))
    recording = f.recording(events=[typed])
    recording.parameters = [
        RedactionParameter(
            name="user_email_1",
            placeholder="<<user_email_1>>",
            category="email",
            occurrences=1,
        ),
        RedactionParameter(
            name="phone_3", placeholder="<<phone_3>>", category="phone", occurrences=1
        ),
    ]

    assert [p.name for p in typed_parameters(recording)] == ["user_email_1"]

    head, _, _ = build_digest(EvidenceStore(recording=recording)).text.partition("EVENTS")
    assert "<<user_email_1>>" in head
    assert "<<phone_3>>" not in head


# --------------------------------------------------------------------------
# boundary hints -- advisory, and the drafter decides
# --------------------------------------------------------------------------


def test_a_pause_is_reported_before_the_event_it_precedes():
    # A boundary hint is about the work that follows it, and a reader looking
    # for one expects to find it above the event, not below.
    text = digest_of(at("evt_001", 0, 0.0), at("evt_002", 1, IDLE_HINT_MS + 500))

    lines = [line for line in text.splitlines() if "pause" in line or "evt_002" in line]
    assert "pause" in lines[0] and "evt_002" in lines[1]


def test_a_gap_under_the_floor_is_not_a_hint():
    text = digest_of(at("evt_001", 0, 0.0), at("evt_002", 1, IDLE_HINT_MS - 1))
    assert "pause" not in text


def test_a_declared_scenario_break_lands_on_the_event_it_opens():
    # The defect this whole marker exists for. The break carries no `eventId`
    # -- `export.ts` attaches an annotation to an event only when it is a fact
    # ABOUT that event, and a boundary sits between two of them -- so it
    # resolves FORWARD to the first event at or after its timestamp.
    text = digest_of(
        at("evt_001", 0, 0.0),
        at("evt_002", 1, 1000.0),
        at("evt_003", 2, 2000.0),
        annotations=[f.annotation("ann_1", "scenario_break", at=1500.0)],
    )

    lines = text.splitlines()
    marker = next(i for i, line in enumerate(lines) if CASE_MARKER in line)
    assert "evt_003" in lines[marker + 1]


def test_a_break_at_the_end_of_a_session_opens_nothing():
    # There is no event after it, so there is no scenario to start. Saying so
    # would be an instruction the drafter cannot follow.
    text = digest_of(
        at("evt_001", 0, 0.0),
        annotations=[f.annotation("ann_1", "scenario_break", at=9000.0)],
    )
    assert CASE_MARKER not in text


def test_a_recording_with_no_break_says_nothing_about_test_cases():
    assert CASE_MARKER not in digest_of(at("evt_001", 0, 0.0), at("evt_002", 1, 1000.0))


# --------------------------------------------------------------------------
# the noise filter -- a node that changes on every event changed because of none
# --------------------------------------------------------------------------


def carousel(ident: str, seq: int, extra: str = "") -> object:
    added = [DiffNode(ref="0.1", role="text", name="Festivities start early")]
    if extra:
        added.append(DiffNode(ref="0.2", role="alert", name=extra))
    return f.event(
        ident, seq=seq, at=float(seq * 100), diff=SnapshotDiff(added=added, removed=[], changed=[])
    )


def test_a_label_that_changes_on_most_events_is_suppressed_from_the_summary():
    # A promotional carousel rotates on a timer, so every click reports it as
    # newly added and six slots of the diff summary go to marketing copy.
    events = [carousel(f"evt_{i:03d}", i) for i in range(1, 7)]
    events[-1] = carousel("evt_006", 6, extra="Order confirmed")

    assert any("Festivities start early" in label for label in _recurring_labels(events))

    text = digest_of(*events)
    assert "Festivities start early" not in text
    # Suppressed from the SUMMARY only. The node is still in the recording and
    # still retrievable, so a drafter with a reason to care can go and look.
    assert "Order confirmed" in text


def test_a_short_session_is_never_filtered():
    # With three events, "changed on most of them" is not evidence of anything.
    events = [carousel(f"evt_{i:03d}", i) for i in range(1, 4)]
    assert _recurring_labels(events) == set()
    assert "Festivities start early" in digest_of(*events)


def test_a_label_that_changed_once_survives():
    events = [f.event(f"evt_{i:03d}", seq=i, at=float(i * 100)) for i in range(1, 6)]
    events[2] = f.event("evt_003", seq=3, at=300.0, diff=f.confirmation_diff())

    assert _recurring_labels(events) == set()
    assert "Order confirmed" in digest_of(*events)


# --------------------------------------------------------------------------
# what an event block carries
# --------------------------------------------------------------------------


def test_an_annotation_is_written_above_everything_else_in_its_block():
    # The tester pointing at something changes how the rest of the block should
    # be read, so it goes first rather than in timestamp order.
    marked = f.event(
        "evt_001",
        diff=f.confirmation_diff(),
        annotations=[f.annotation("ann_1", "assertion", role="alert", name="Order confirmed")],
    )
    lines = digest_of(marked).splitlines()

    block = lines[lines.index(next(line for line in lines if "evt_001" in line)) :]
    assert "tester:" in block[1]


def test_a_state_changing_request_is_reported_and_an_analytics_beacon_is_not():
    event = f.event(
        "evt_001",
        network=[
            f.network_call("net_001", "POST", "https://demo.local/api/orders", 500),
            f.network_call("net_002", "POST", "https://analytics.example/collect", 200),
        ],
    )
    text = digest_of(event)

    assert "/api/orders" in text and "500" in text


def test_console_output_reaches_the_author():
    # An uncaught exception is one of the three signals bug mode takes, and it
    # cannot be one if the author never sees it.
    event = f.event(
        "evt_001",
        console=[
            ConsoleEntry(
                id="con_001",
                level="error",
                text="TypeError: undefined is not a function",
                timestamp=10.0,
            )
        ],
    )
    assert "TypeError" in digest_of(event)


def test_what_the_recorder_could_not_capture_is_stated_rather_than_hidden():
    # SS6.4: a gap the tester can see beats a document that quietly omits it.
    assert "not captured" in digest_of(f.event("evt_001", fidelity=["closed_shadow_root"]))


def test_moving_to_another_tab_is_announced():
    # SS18 milestone 21. The recorder follows a tab opened from a recorded one,
    # so a payment provider or a PDF lands in the same session. Without a line
    # here the index reads as one continuous page and the author writes "the
    # tester continued" for "a payment window opened" -- the `scenario_break`
    # bug in a third costume: a session-level fact no per-event block carried,
    # silently absent rather than wrong.
    store = EvidenceStore(
        f.recording(
            events=[
                f.event("evt_001", 0, at=0.0, tabId=7),
                f.event("evt_002", 1, at=1000.0, tabId=9),
                f.event("evt_003", 2, at=2000.0, tabId=9),
            ]
        )
    )
    lines = build_digest(store).text.splitlines()
    announced = [i for i, line in enumerate(lines) if "A DIFFERENT BROWSER TAB" in line]
    assert len(announced) == 1, "announced on the move, not on every event in the new tab"
    # And it lands ABOVE the event it belongs to, so the author reads it before
    # anything else about that action.
    assert "evt_002" in lines[announced[0] + 1]


def test_a_single_tab_session_says_nothing_about_tabs():
    # The negative case, and it matters: every recording made before multi-tab
    # existed has no `tabId` at all, and a line claiming a tab change on those
    # would be a fabrication in the one document the author is told to trust.
    store = EvidenceStore(
        f.recording(events=[f.event("evt_001", 0, at=0.0), f.event("evt_002", 1, at=1000.0)])
    )
    assert "DIFFERENT BROWSER TAB" not in build_digest(store).text


# --------------------------------------------------------------------------
# the cost
# --------------------------------------------------------------------------


def test_the_digest_reports_its_own_size_and_the_events_it_covers():
    # `approx_tokens` is the one number that says whether a whole session fits
    # in one drafting call. It is reported, never load-bearing.
    digest = build_digest(
        EvidenceStore(
            recording=f.recording(
                events=[at(f"evt_{i:03d}", i - 1, float(i * 100)) for i in range(1, 4)]
            )
        )
    )

    assert digest.event_count == 3
    assert digest.event_ids == ["evt_001", "evt_002", "evt_003"]
    assert digest.approx_tokens == len(digest.text) // 4


def _narrated(segments):
    from server.pipeline.segment import segment_recording

    rec = f.recording(
        events=[
            f.event("evt_001", 0, at=15600.0),
            f.event("evt_002", 1, at=17000.0),
        ],
        narration=segments,
    )
    return EvidenceStore(recording=rec, segments=segment_recording(rec, run_id="run_001"))


def _said(digest) -> list[str]:
    return [
        line.strip().removeprefix("said: ")
        for line in digest.text.splitlines()
        if line.strip().startswith("said:")
    ]


def test_what_the_tester_says_before_their_first_click_reaches_the_index():
    """The window that did not exist is the one holding the objective.

    `_event_block` emitted `said:` only `if previous is not None`, so nothing
    spoken before the first recorded event was ever indexed -- and a tester
    states what they are about to check BEFORE they start clicking, not during.

    On `rec_MT7VTN7ZRJPO` the events begin at 15.6s and four of five segments
    fall in 0.9s-14.9s. The only sentence the drafter ever saw was "And I will
    add to bag a...", and the run went on to write a document about a quantity
    limit the tester never mentioned.

    The same shape as the `scenario_break` defect: a session-level fact that no
    per-event block can carry, silently absent rather than wrong.
    """
    store = _narrated(
        [
            NarrationSegment(
                id="nar_001",
                startMs=900.0,
                endMs=6000.0,
                text="I will test if I can add the coffee products correctly to the cart",
                confidence=0.9,
            ),
            NarrationSegment(
                id="nar_002",
                startMs=16000.0,
                endMs=16800.0,
                text="And I will add to bag a flat white",
                confidence=0.9,
            ),
        ]
    )

    said = _said(build_digest(store))
    assert any("coffee products correctly" in line for line in said), (
        "the objective the tester spoke before their first click is missing from the index"
    )
    # The later sentence still lands where it always did.
    assert any("flat white" in line for line in said)


def test_narration_can_still_be_withheld_from_the_index():
    """The negative case. `include_narration=False` is A0's, and the flag has to
    keep meaning what it says now that the first event has a window too."""
    store = _narrated(
        [
            NarrationSegment(
                id="nar_001",
                startMs=900.0,
                endMs=6000.0,
                text="I will test if I can add the coffee products correctly to the cart",
                confidence=0.9,
            )
        ]
    )
    assert _said(build_digest(store, include_narration=False)) == []
