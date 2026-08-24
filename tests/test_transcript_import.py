"""A transcript from elsewhere, read as narration (SS6.6).

The regexes here get negative cases on purpose. A cue pattern that compiles and
matches nothing is the failure mode this repo has already shipped once, and the
symptom -- a recording with no narration in it -- is indistinguishable from a
tester who did not speak.
"""

from __future__ import annotations

import json

import pytest

from server.importers.transcript import CUE, describe, load_transcript


def write(tmp_path, name: str, body: str):
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


VTT = """WEBVTT

00:00.000 --> 00:03.500
now I'm checking that an order this size

00:03.500 --> 00:06.200
needs manager approval
"""

SRT = """1
00:00:12,000 --> 00:00:15,250
the cart badge should go up to one

2
00:00:20,500 --> 00:00:23,000
and the total updates to six fifteen
"""


def test_webvtt_cues_become_segments_in_order(tmp_path):
    segments = load_transcript(write(tmp_path, "notes.vtt", VTT))

    assert [s.id for s in segments] == ["nar_001", "nar_002"]
    assert segments[0].startMs == 0
    assert segments[0].endMs == 3500
    assert segments[0].text == "now I'm checking that an order this size"
    assert segments[1].startMs == 3500


def test_srt_comma_separator_and_hours_are_read_the_same_way(tmp_path):
    segments = load_transcript(write(tmp_path, "notes.srt", SRT))

    assert len(segments) == 2
    assert segments[0].startMs == 12_000
    assert segments[0].endMs == 15_250
    assert segments[1].text == "and the total updates to six fifteen"
    # The index lines are the format's, not content. A transcript that quotes
    # "1" as something the tester said would put a literal in `find_text` that
    # nobody ever uttered.
    assert not any(s.text.strip() == "1" for s in segments)


def test_offset_shifts_every_segment(tmp_path):
    """A voice memo starts at its own zero, and the recorder's is elsewhere.

    This is the setting that fails silently: a wrong offset does not error, it
    attributes each sentence to the wrong step and produces a grounded,
    plausible, wrong expected result.
    """
    segments = load_transcript(write(tmp_path, "notes.vtt", VTT), offset_ms=10_000)

    assert segments[0].startMs == 10_000
    assert segments[1].endMs == 16_200


def test_a_negative_offset_never_produces_a_negative_timestamp(tmp_path):
    segments = load_transcript(write(tmp_path, "notes.vtt", VTT), offset_ms=-5_000)
    assert all(s.startMs >= 0 and s.endMs >= 0 for s in segments)


def test_our_own_json_round_trips_including_confidence(tmp_path):
    body = json.dumps(
        [
            {"id": "whatever", "startMs": 500, "endMs": 900, "text": "spoken", "confidence": 0.42},
            {"id": "x", "startMs": 100, "endMs": 200, "text": "earlier"},
        ]
    )
    segments = load_transcript(write(tmp_path, "notes.json", body))

    # Sorted by time and renumbered: source ids are discarded because two merged
    # transcripts would otherwise collide on them.
    assert [s.text for s in segments] == ["earlier", "spoken"]
    assert [s.id for s in segments] == ["nar_001", "nar_002"]
    assert segments[1].confidence == pytest.approx(0.42)
    assert segments[0].confidence is None


def test_a_whole_recording_can_be_used_as_the_transcript_source(tmp_path):
    body = json.dumps({"narration": [{"startMs": 0, "endMs": 10, "text": "hello"}]})
    assert load_transcript(write(tmp_path, "rec.json", body))[0].text == "hello"


def test_a_malformed_cue_is_skipped_rather_than_zeroed(tmp_path):
    """0ms is not a safe default.

    A segment silently placed at zero attaches to the first step of the
    recording and reads as something said before the tester had done anything --
    wrong rather than missing, which is the more expensive of the two.
    """
    body = "WEBVTT\n\n00:00:not-a-time --> 00:03.000\nghost\n\n00:05.000 --> 00:06.000\nreal\n"
    segments = load_transcript(write(tmp_path, "bad.vtt", body))

    assert [s.text for s in segments] == ["real"]


def test_an_empty_cue_body_produces_no_segment(tmp_path):
    body = "WEBVTT\n\n00:01.000 --> 00:02.000\n\n00:05.000 --> 00:06.000\nreal\n"
    assert [s.text for s in load_transcript(write(tmp_path, "e.vtt", body))] == ["real"]


def test_a_file_that_is_not_a_transcript_says_so(tmp_path):
    with pytest.raises(ValueError, match="not a transcript"):
        load_transcript(write(tmp_path, "notes.txt", "just some prose about the session"))


@pytest.mark.parametrize(
    "line",
    [
        "00:00.000 --> 00:03.500",
        "00:00:00,000 --> 00:00:03,500",
        "1:02.5 --> 1:03.9",
        "00:00.000 --> 00:03.500 align:start position:50%",
    ],
)
def test_cue_matches_the_shapes_that_exist(line):
    assert CUE.match(line)


@pytest.mark.parametrize(
    "line",
    [
        "WEBVTT",
        "1",
        "now I'm checking --> the total",
        "00:00.000 - 00:03.500",
        "the arrow --> is in the middle of a sentence about time 00:01.000",
    ],
)
def test_cue_rejects_what_is_not_a_timing(line):
    assert CUE.match(line) is None


def test_describe_names_a_transcript_that_landed_outside_the_recording(tmp_path):
    segments = load_transcript(write(tmp_path, "notes.vtt", VTT), offset_ms=600_000)
    text = describe(segments, duration_ms=90_000)

    assert "--narration-offset" in text
    assert "outside the recording" in text


def test_describe_is_quiet_when_the_mapping_is_plausible(tmp_path):
    segments = load_transcript(write(tmp_path, "notes.vtt", VTT))
    assert "outside the recording" not in describe(segments, duration_ms=90_000)


def test_a_recording_written_back_out_still_validates(tmp_path):
    """`from` is a Python keyword, and that has bitten this file twice.

    Codegen emits `from_ = Field(..., alias="from")` on `UrlChange`, so a dump
    without `by_alias=True` writes `from_` -- which the schema forbids. Nothing
    complains at write time. The recording is simply poisoned, and the failure
    surfaces later, somewhere unrelated, as a validation error nobody can trace
    back to the write that caused it.

    Any path that saves a Recording has to survive this round trip.
    """
    from server.models import Recording, SnapshotDiff
    from server.storage.paths import Storage
    from tests import factories as f

    recording = f.recording(
        events=[
            f.event(
                "evt_001",
                0,
                at=0.0,
                diff=SnapshotDiff(
                    added=[],
                    removed=[],
                    changed=[],
                    urlChanged=f.url_change("https://a/", "https://b/"),
                ),
            )
        ]
    )
    storage = Storage(recordings_dir=tmp_path / "rec", runs_dir=tmp_path / "runs")
    path = storage.save_recording(recording)

    written = json.loads(path.read_text(encoding="utf-8"))
    assert "from" in written["events"][0]["diff"]["urlChanged"]
    assert "from_" not in written["events"][0]["diff"]["urlChanged"]

    # The check that actually matters: it can be read back.
    Recording.model_validate(written)
