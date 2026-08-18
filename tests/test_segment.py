"""Segmentation is deterministic code, so it can be tested exhaustively.

The property that matters most is coverage: every event in exactly one segment.
Everything downstream indexes by event id, and a segmenter that quietly drops
one would corrupt the whole run in a way no later stage could detect.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.models import Recording, SegmentsDocument
from server.pipeline.segment import (
    IDLE_GAP_MS,
    MAX_EVENTS_PER_SEGMENT,
    segment_recording,
)
from tests import factories as f

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run(recording: Recording) -> SegmentsDocument:
    return segment_recording(recording, run_id="run_test")


def event_ids(doc: SegmentsDocument) -> list[str]:
    return [eid for s in doc.segments for eid in s.eventIds]


# --------------------------------------------------------------------------
# coverage
# --------------------------------------------------------------------------


def test_every_event_lands_in_exactly_one_segment():
    events = [f.event(f"evt_{i:03d}", i, at=i * 500.0) for i in range(25)]
    doc = run(f.recording(events=events))

    assert event_ids(doc) == [e.id for e in events]
    assert doc.eventCount == 25
    assert len(set(event_ids(doc))) == 25


def test_segment_count_is_stable_across_runs():
    # Reproducibility is the reason this stage is code (SS9.2): QA artifacts are
    # audit material, and the same recording producing different step counts
    # twice is a real problem for users.
    events = [f.event(f"evt_{i:03d}", i, at=i * 700.0) for i in range(14)]
    rec = f.recording(events=events)
    assert [s.eventIds for s in run(rec).segments] == [s.eventIds for s in run(rec).segments]


def test_an_empty_recording_produces_no_segments():
    doc = run(f.recording(events=[]))
    assert doc.segments == []
    assert doc.eventCount == 0


# --------------------------------------------------------------------------
# boundary triggers, in priority order
# --------------------------------------------------------------------------


def test_idle_gap_starts_a_new_segment():
    events = [
        f.event("evt_001", 0, at=0.0),
        f.event("evt_002", 1, at=100.0),
        f.event("evt_003", 2, at=100.0 + IDLE_GAP_MS + 1),
    ]
    doc = run(f.recording(events=events))
    assert [s.eventIds for s in doc.segments] == [["evt_001", "evt_002"], ["evt_003"]]
    assert doc.segments[1].boundaryReason.value == "idle_gap"


def test_a_submit_closes_the_segment_it_completes():
    # The submit is the culmination of the step, not the start of the next one.
    events = [
        f.event("evt_001", 0, at=0.0, etype="input"),
        f.event("evt_002", 1, at=100.0, etype="submit"),
        f.event("evt_003", 2, at=200.0),
    ]
    doc = run(f.recording(events=events))
    assert [s.eventIds for s in doc.segments] == [["evt_001", "evt_002"], ["evt_003"]]
    assert doc.segments[1].boundaryReason.value == "form_submit"


def test_a_successful_mutation_closes_the_segment():
    events = [
        f.event("evt_001", 0, at=0.0),
        f.event("evt_002", 1, at=100.0, network=[f.network_call(status=201)]),
        f.event("evt_003", 2, at=200.0),
    ]
    doc = run(f.recording(events=events))
    assert [s.eventIds for s in doc.segments] == [["evt_001", "evt_002"], ["evt_003"]]
    assert doc.segments[0].mutations == ["POST /api/orders 201"]


def test_a_rejected_mutation_does_not_cut_the_step():
    # A 409 leaves the tester on the same screen, still working on the same
    # step. Cutting here would split one attempt into two steps.
    events = [
        f.event("evt_001", 0, at=0.0, network=[f.network_call(status=409)]),
        f.event("evt_002", 1, at=100.0),
    ]
    doc = run(f.recording(events=events))
    assert len(doc.segments) == 1
    assert doc.segments[0].mutations is None


def test_a_url_change_closes_the_segment():
    nav = f.event("evt_001", 0, at=0.0)
    nav.diff.urlChanged = f.url_change()
    doc = run(f.recording(events=[nav, f.event("evt_002", 1, at=50.0)]))
    assert [s.eventIds for s in doc.segments] == [["evt_001"], ["evt_002"]]
    assert doc.segments[1].boundaryReason.value == "url_change"


def test_a_checkpoint_annotation_overrides_the_segmenter():
    events = [f.event(f"evt_{i:03d}", i, at=i * 100.0) for i in range(4)]
    rec = f.recording(events=events)
    rec.annotations = [f.annotation("ann_1", "checkpoint", at=150.0)]
    doc = run(rec)
    assert [s.eventIds for s in doc.segments] == [
        ["evt_000", "evt_001"],
        ["evt_002", "evt_003"],
    ]
    assert doc.segments[1].boundaryReason.value == "checkpoint_annotation"


def test_the_hard_cap_stops_a_segment_growing_without_bound():
    events = [f.event(f"evt_{i:03d}", i, at=i * 10.0) for i in range(30)]
    doc = run(f.recording(events=events))
    assert all(len(s.eventIds) <= MAX_EVENTS_PER_SEGMENT for s in doc.segments)
    assert doc.segments[1].boundaryReason.value == "hard_cap"


def test_a_wholesale_region_replacement_closes_the_segment():
    big = f.snapshot(
        root=f.node(
            "0",
            "main",
            "Catalogue",
            children=[f.node(f"0.{i}", "row", f"Product {i}") for i in range(10)],
        )
    )
    replaced = f.event("evt_001", 0, at=0.0, before=big)
    replaced.diff.removed = [f.diff_node(f"0.{i}", "row", f"Product {i}") for i in range(10)]
    doc = run(f.recording(events=[replaced, f.event("evt_002", 1, at=50.0)]))
    assert [s.eventIds for s in doc.segments] == [["evt_001"], ["evt_002"]]
    assert doc.segments[1].boundaryReason.value == "region_replacement"


def test_a_tiny_scope_does_not_trip_the_replacement_ratio():
    # With a two-node scope any change at all exceeds 60%, which would cut a
    # segment at every single event on a sparse page.
    small = f.event("evt_001", 0, at=0.0)
    small.diff.added = [f.diff_node("0.1", "status", "Saved")]
    doc = run(f.recording(events=[small, f.event("evt_002", 1, at=50.0)]))
    assert len(doc.segments) == 1


def test_the_strongest_trigger_is_the_one_recorded():
    # A submit that also mutates and also navigates: url_change outranks both.
    event = f.event("evt_001", 0, at=0.0, etype="submit", network=[f.network_call(status=201)])
    event.diff.urlChanged = f.url_change("https://demo.local/a", "https://demo.local/b")
    doc = run(f.recording(events=[event, f.event("evt_002", 1, at=50.0)]))
    assert doc.segments[1].boundaryReason.value == "url_change"


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------


def test_the_label_summarises_actions_and_their_outcome():
    event = f.event(
        "evt_001",
        0,
        at=0.0,
        diff=f.confirmation_diff(),
        network=[f.network_call(status=201)],
    )
    doc = run(f.recording(events=[event]))
    label = doc.segments[0].label
    assert 'click "Submit order"' in label
    assert "POST /api/orders 201" in label
    assert 'alert "Order confirmed"' in label


# --------------------------------------------------------------------------
# against a real recording
# --------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["checkout", "hardpaths"])
def test_segments_a_real_recorded_session(name: str):
    path = FIXTURES / f"{name}.recording.json"
    if not path.exists():
        pytest.skip("run `pnpm e2e` to regenerate the recorded fixtures")

    recording = Recording.model_validate(json.loads(path.read_text(encoding="utf-8")))
    doc = run(recording)

    assert event_ids(doc) == [e.id for e in recording.events]
    assert doc.segments, "a real session must produce at least one segment"
    assert all(s.label for s in doc.segments)
    # Segment ids are dense and ordered, since the review UI merges and splits
    # by index.
    assert [s.index for s in doc.segments] == list(range(len(doc.segments)))
