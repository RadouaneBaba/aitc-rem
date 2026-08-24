"""Narration is the only lossy evidence source, and these are the guards on it.

A mis-heard literal passes `evidence_retrieved` (it really is in the stored tool
response) and `assertion_grounding` (it really is in the index) and is still
false. Both validators are right; the ladder is what has to hold. So the
confidence gate is tested here rather than assumed, and the redaction pass is
tested for what it must NOT eat as much as for what it catches.

Only `test_a_real_clip_is_transcribed` needs faster-whisper. Everything else runs
on any machine, which is the point: the gate is what protects the output, and it
must not be the part that only runs where the model is installed.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from server.models import NarrationSegment
from server.pipeline.transcribe import (
    TranscriptionSettings,
    TranscriptionUnavailable,
    _confidence,
    _luhn,
    redact,
    supports_narrated,
    transcribe,
)

FIXTURES = Path(__file__).parent / "fixtures"


def segment(**kwargs) -> NarrationSegment:
    return NarrationSegment(
        **{"id": "nar_001", "startMs": 0, "endMs": 1000, "text": "spoken", **kwargs}
    )


# --------------------------------------------------------------------------
# the confidence gate
# --------------------------------------------------------------------------


def test_a_confident_segment_supports_the_narrated_rank():
    assert supports_narrated(segment(confidence=0.9), 0.5)


def test_an_unsure_segment_does_not_outrank_an_honest_inference():
    """The whole point.

    A transcriber that was guessing must not be able to promote a claim above
    `inferred`, because the claim it promotes may be a sentence nobody said.
    """
    assert not supports_narrated(segment(confidence=0.2), 0.5)


def test_a_segment_with_no_confidence_is_trusted():
    """It came from `--narration`: a human, or another tool they chose.

    The gate exists to catch a transcriber that was unsure, not to disbelieve a
    person who typed out what they said.
    """
    assert supports_narrated(segment(), 0.5)


def test_the_threshold_is_inclusive_at_its_own_value():
    assert supports_narrated(segment(confidence=0.5), 0.5)


def test_a_zero_threshold_trusts_everything():
    assert supports_narrated(segment(confidence=0.0), 0.0)


def test_confidence_falls_with_the_models_own_uncertainty():
    clean = _confidence(SimpleNamespace(avg_logprob=-0.08, no_speech_prob=0.01))
    guess = _confidence(SimpleNamespace(avg_logprob=-1.4, no_speech_prob=0.05))
    assert clean > guess


def test_a_confident_transcription_of_something_that_was_not_speech_scores_low():
    """`avg_logprob` alone is not enough.

    Whisper will confidently transcribe a door closing as a short sentence.
    `no_speech_prob` is the signal that catches it, and folding only the first
    one would let that sentence into the index at full rank.
    """
    door = _confidence(SimpleNamespace(avg_logprob=-0.05, no_speech_prob=0.95))
    assert door < 0.2


def test_confidence_stays_inside_zero_and_one():
    for avg, nsp in [(-9.0, 0.0), (0.5, 0.0), (-0.1, 1.0), (0.0, 0.0)]:
        value = _confidence(SimpleNamespace(avg_logprob=avg, no_speech_prob=nsp))
        assert 0.0 <= value <= 1.0


def test_confidence_survives_a_segment_missing_the_fields():
    assert 0.0 <= _confidence(SimpleNamespace()) <= 1.0


# --------------------------------------------------------------------------
# redaction: best-effort, and what it must not eat
# --------------------------------------------------------------------------


def test_a_spoken_email_read_off_the_screen_is_replaced():
    assert redact("signing in as tester@example.com now") == "signing in as <<email>> now"


def test_a_card_number_read_aloud_is_replaced():
    assert "<<card_number>>" in redact("the card is 4539578763621486 on file")


def test_a_purchase_order_number_survives():
    """The failure that would matter more than the redaction.

    A long digit run is only a card number if it checksums like one. Eating
    "PO-4471" or an order reference would remove exactly the literal an
    assertion needs, and the tester would see a missing expected result with
    nothing to explain it.
    """
    assert redact("purchase order 4471 for 615 euros") == "purchase order 4471 for 615 euros"
    assert redact("reference 1234567890123456789") == "reference 1234567890123456789"


def test_ordinary_narration_is_left_exactly_alone():
    said = "now I'm checking that an order this size needs manager approval"
    assert redact(said) == said


def test_luhn_accepts_a_real_number_and_rejects_a_plausible_one():
    assert _luhn("4539578763621486")
    assert not _luhn("4539578763621487")
    assert not _luhn("12345")  # too short to be a card at all


# --------------------------------------------------------------------------
# the real thing
# --------------------------------------------------------------------------


@pytest.mark.skipif(
    not (FIXTURES / "narration.wav").exists(),
    reason="tests/fixtures/narration.wav is missing; run scripts/make_narration_wav.ps1",
)
def test_a_real_clip_is_transcribed_onto_the_recorders_clock():
    """The one test that needs faster-whisper, and it says so when it skips.

    A skip that reports its reason is the difference between "not installed" and
    "quietly broken" -- the same distinction `no_pruned_assertion` was making
    for a year before anything gave it a recording to work on.
    """
    pytest.importorskip("faster_whisper", reason="pip install -e .[transcription]")

    # tiny: this asserts the wiring and the clock, not the model's accuracy.
    # Pinning `small` here would make a unit test download 250MB.
    segments = transcribe(
        FIXTURES / "narration.wav",
        settings=TranscriptionSettings(model="tiny", language="en"),
        offset_ms=4_000,
    )

    assert segments, "the fixture clip contains speech; an empty result is a wiring failure"
    assert [s.id for s in segments] == [f"nar_{i:03d}" for i in range(1, len(segments) + 1)]

    # The offset is the thing that silently mis-attributes narration to the
    # wrong step, so it is worth asserting rather than eyeballing.
    assert min(s.startMs for s in segments) >= 4_000
    assert all(s.endMs >= s.startMs for s in segments)
    assert all(s.confidence is not None for s in segments)

    spoken = " ".join(s.text for s in segments).lower()
    assert "approval" in spoken


def test_audio_that_will_not_decode_degrades_instead_of_taking_the_run_with_it(tmp_path):
    """The failure mode that would cost a whole session.

    A truncated upload or a half-written WebM raises out of the decoder, and
    that error used to propagate through `POST /api/recordings` and 500 the
    ingest -- losing fifteen minutes of recorded work because the narration
    would not open. Reported as unavailable instead: the audio is kept, the
    recording lands, and the export page says what happened.
    """
    pytest.importorskip("faster_whisper", reason="pip install -e .[transcription]")

    broken = tmp_path / "audio.webm"
    broken.write_bytes(b"\x1a\x45\xdf\xa3 not actually a media file")

    with pytest.raises(TranscriptionUnavailable, match="could not be transcribed"):
        transcribe(broken, settings=TranscriptionSettings(model="tiny", language="en"))
