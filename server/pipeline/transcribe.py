"""Narration audio -> `NarrationSegment`s, on this machine (SS6.6, SS7.5).

**Narration is the only lossy evidence source in this project, and everything
here is shaped by that.** Snapshot node names, request URLs, response bodies and
console text are all read exactly; the store hands back the same bytes that were
captured. A transcript is a reconstruction, and that difference is not academic:

    The tester says "the total updates to six fifteen".
    Whisper hears  "the total updates to six fifty".

    The assert stage cites it. `evidence_retrieved` passes -- the literal really
    is in the stored tool response. `assertion_grounding` passes -- it really is
    in the index. The claim is grounded, admissible, and FALSE.

Both validators are right, exactly as they both were in the page-URL case in
CLAUDE.md. The admissibility rule guarantees provenance, never correctness, and
this is the first input where the two come apart by construction rather than by
a model's bad judgement.

Two answers, both deliberately outside the model's control:

1. **Confidence gates the rank.** `_confidence` folds Whisper's `avg_logprob`
   and `no_speech_prob` into the `confidence` field the schema has always had,
   and `assertions.py` refuses to let a low-confidence segment support the
   `narrated` provenance. A sentence the transcriber was unsure of cannot
   outrank an honest inference. Deterministic, like noise suppression, because a
   rule a model is merely told about is a rule that holds most of the time.

2. **The audio is kept.** A browser cannot re-check something a person said out
   loud -- `server/runners/playwright.py` maps narration to `not_checkable` and
   is right to. A person can. The review UI plays the clip, which is the only
   verification a lossy source can actually have.

Transcription is local. `faster-whisper` runs CTranslate2 on the CPU here; no
audio is uploaded anywhere, and the pipeline never sees the audio at all -- only
the text, which is what reaches a model.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

from server.models import NarrationSegment

#: SS7.1, applied to speech. Deliberately thin, and honest about it: this is the
#: same best-effort pass `server/importers/devtools.py` makes, minus the DOM that
#: would let it ask whether a field was a password.
#:
#: It cannot catch "john at example dot com", and pretending otherwise would be
#: worse than not doing it -- the tester is told plainly in docs/RECORDING.md
#: that what they say out loud is written down. What this does catch is the case
#: that actually happens: reading a value off the screen verbatim.
EMAIL = re.compile(r"\b[^@\s]+@[^@\s]+\.[a-z]{2,}\b", re.IGNORECASE)
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

#: Whisper emits this for silence and for music. It is not something the tester
#: said, and indexing it would let a claim cite a hallucination.
HALLUCINATED = {
    "",
    ".",
    "thank you.",
    "thanks for watching!",
    "you",
    "bye.",
    "[blank_audio]",
    "[silence]",
    "(silence)",
}


class TranscriptionUnavailable(RuntimeError):
    """`faster-whisper` is not installed, or the model could not be loaded.

    Raised rather than swallowed so a caller can decide. `cmd_run` and the API
    both degrade loudly: the run continues with no narration and says so, in the
    posture `cmd_import` already takes about what an import cannot bring.
    """


@dataclass(frozen=True)
class TranscriptionSettings:
    model: str = "small"
    language: str = "auto"
    #: Segments below this are still returned -- they are kept and shown -- but
    #: `supports_narrated` is false for them.
    min_confidence: float = 0.5


def transcribe(
    audio: Path,
    *,
    settings: TranscriptionSettings | None = None,
    offset_ms: float = 0.0,
) -> list[NarrationSegment]:
    """Transcribe `audio`, shifted onto the recorder's clock by `offset_ms`.

    `offset_ms` is `Recording.metadata.audioOffsetMs`: the microphone takes a
    moment to open, so audio does not start when the recording does. Without it
    every sentence is shifted by that delay and lands on the wrong step -- which
    does not fail, it produces a plausible, grounded, wrong expected result.
    """
    settings = settings or TranscriptionSettings()
    model = _load(settings.model)

    # Decoding and transcription are wrapped together because faster-whisper
    # returns a GENERATOR: the file is opened when `transcribe` is called, but
    # a stream that goes bad partway through raises during iteration instead.
    #
    # Every failure in here becomes TranscriptionUnavailable on purpose. A
    # truncated upload or a half-written WebM must not take the recording with
    # it -- losing a fifteen-minute session because the narration would not
    # decode is a far worse outcome than a run with no narration in it, and the
    # caller reports the reason either way.
    out: list[NarrationSegment] = []
    try:
        segments, _info = model.transcribe(
            str(audio),
            # A QA session is mostly silence. VAD is what keeps a fifteen-minute
            # recording to the few seconds that were actually speech, and it is
            # also what stops Whisper hallucinating sentences into the quiet.
            vad_filter=True,
            language=(
                None if settings.language.strip().lower() in {"", "auto"} else settings.language
            ),
            condition_on_previous_text=False,
        )

        for segment in segments:
            text = redact(segment.text.strip())
            if text.strip().lower() in HALLUCINATED:
                continue
            out.append(
                NarrationSegment(
                    id=f"nar_{len(out) + 1:03d}",
                    startMs=max(0.0, (segment.start * 1000.0) + offset_ms),
                    endMs=max(0.0, (segment.end * 1000.0) + offset_ms),
                    text=text,
                    confidence=_confidence(segment),
                )
            )
    except Exception as exc:  # noqa: BLE001 - every failure degrades the same way
        raise TranscriptionUnavailable(
            f"{audio.name} could not be transcribed: {type(exc).__name__}: {exc}. "
            f"The audio is kept, so it can be transcribed again with "
            f"`python -m server.cli transcribe`."
        ) from exc

    return out


def _load(size: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - depends on the extra
        raise TranscriptionUnavailable(
            "faster-whisper is not installed, so there is nothing to transcribe the "
            "audio with. Install it with:\n"
            "    pip install -e .[transcription]\n"
            "Or supply a transcript from elsewhere with --narration <file.vtt>."
        ) from exc

    try:
        # int8 on CPU: our audio is seconds of clean close-mic speech, and the
        # quantisation costs nothing measurable on that while making `small`
        # comfortable on a laptop.
        return WhisperModel(size, device="cpu", compute_type="int8")
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        raise TranscriptionUnavailable(f"could not load the {size!r} model: {exc}") from exc


def _confidence(segment) -> float:
    """Whisper's two uncertainty signals, folded into one 0-1 number.

    `avg_logprob` is the mean token log-probability, typically about -0.1 for a
    clean sentence and below -1.0 for a guess. `no_speech_prob` is how likely
    the model thinks this was not speech at all -- the signal that catches a
    confident transcription of a door closing.

    The mapping does not need to be principled, only monotone and stable: it
    feeds a threshold, and the threshold is a project setting.
    """
    avg_logprob = float(getattr(segment, "avg_logprob", 0.0) or 0.0)
    no_speech = float(getattr(segment, "no_speech_prob", 0.0) or 0.0)

    spoken = math.exp(min(0.0, avg_logprob))
    return max(0.0, min(1.0, spoken * (1.0 - no_speech)))


def supports_narrated(segment: NarrationSegment, min_confidence: float) -> bool:
    """Whether this segment may support the `narrated` provenance.

    A segment with no confidence at all -- one that came from `--narration`,
    written by a human or by another tool -- is trusted. The gate exists to
    catch a transcriber that was unsure, not to disbelieve a person who typed
    out what they said.
    """
    if segment.confidence is None:
        return True
    return segment.confidence >= min_confidence


def redact(text: str) -> str:
    """Best-effort, and that word is doing real work. See EMAIL/CARD above."""
    text = EMAIL.sub("<<email>>", text)
    return CARD.sub(lambda m: "<<card_number>>" if _luhn(m.group()) else m.group(), text)


def _luhn(digits: str) -> bool:
    """A long number is only a card number if it checksums like one.

    Without this, "PO four four seven one two three four five six seven eight"
    read back as digits would be redacted out of the transcript -- and a
    purchase order number is exactly the kind of literal an assertion needs.
    """
    numbers = [int(c) for c in digits if c.isdigit()]
    if not 13 <= len(numbers) <= 19:
        return False
    total = 0
    for index, digit in enumerate(reversed(numbers)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


__all__ = [
    "TranscriptionSettings",
    "TranscriptionUnavailable",
    "redact",
    "supports_narrated",
    "transcribe",
]
