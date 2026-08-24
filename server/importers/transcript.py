"""A transcript from somewhere else, as narration (SS6.6).

The recorder captures audio and `server/pipeline/transcribe.py` turns it into
`NarrationSegment`s, which is the path a tester takes. This is the other way in,
and it exists for three reasons that are not going away:

* An imported recording (`server/importers/devtools.py`) has no audio and never
  will, but the tester may well have dictated notes alongside it.
* Transcription needs `faster-whisper` and a model download. A machine that
  cannot have those is not a machine that should be unable to use narration.
* It is how a transcript gets *fixed*. Whisper is a reconstruction, and the
  honest answer to a bad segment is to correct the file and re-run, not to argue
  with the model.

WebVTT and SRT are accepted because that is what OS dictation, voice-memo apps
and every transcription service actually emit. Both put the timings on a line
containing `-->`; they differ only in the decimal separator and in what they put
on the line above, so one parser reads both.

**The offset is the thing to get right.** A transcript recorded by a separate
device starts at *its* zero, not the recorder's, and a wrong offset does not
fail -- it silently attributes every sentence to the wrong step, which produces a
grounded, plausible, wrong expected result. `load_transcript` therefore takes the
offset explicitly and the CLI prints the window it mapped onto, so a bad one is
visible rather than deducible.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from server.models import NarrationSegment

#: `HH:MM:SS,mmm --> HH:MM:SS,mmm` (SRT) or `MM:SS.mmm --> MM:SS.mmm` (WebVTT).
#: Hours are optional in WebVTT and the decimal separator differs, so both are.
#: Trailing cue settings (`align:start position:50%`) are matched and ignored.
CUE = re.compile(
    r"^\s*(?P<start>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})"
    r"\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?[.,]\d{1,3})"
    r"(?:\s+\S+)*\s*$"
)

#: WebVTT allows inline markup in a cue payload (`<v Speaker>`, `<i>`). It is
#: presentation, and a literal in a `<b>` tag is a literal `find_text` would
#: never match.
TAG = re.compile(r"</?[^>]+>")


def load_transcript(path: Path, offset_ms: float = 0.0) -> list[NarrationSegment]:
    """Read a transcript file as narration segments, shifted by `offset_ms`.

    Format is sniffed from the content rather than the extension: a transcript
    arrives named whatever the tool that produced it felt like.
    """
    text = path.read_text(encoding="utf-8-sig")
    stripped = text.lstrip()

    if stripped.startswith(("[", "{")):
        segments = _from_json(json.loads(text))
    elif "-->" in text:
        segments = _from_cues(text)
    else:
        raise ValueError(
            f"{path.name} is not a transcript this understands. Expected a JSON array of "
            f"narration segments, or a WebVTT/SRT file (a line containing '-->')."
        )

    return _renumber(segments, offset_ms)


def _from_json(data: Any) -> list[dict[str, Any]]:
    """Our own shape: a bare array, or a whole recording to lift it out of."""
    if isinstance(data, dict):
        data = data.get("narration", data.get("segments", []))
    if not isinstance(data, list):
        raise ValueError("expected a JSON array of narration segments")

    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        if not text:
            continue
        out.append(
            {
                "startMs": float(item.get("startMs", 0.0)),
                "endMs": float(item.get("endMs", item.get("startMs", 0.0))),
                "text": text,
                **({"confidence": float(item["confidence"])} if "confidence" in item else {}),
            }
        )
    return out


def _from_cues(text: str) -> list[dict[str, Any]]:
    """WebVTT and SRT.

    A malformed cue is skipped rather than zeroed. A segment that silently lands
    at 0ms attaches itself to the first step of the recording and reads as
    something the tester said before they had done anything -- worse than a
    sentence that is simply absent, because it is wrong rather than missing.
    """
    out: list[dict[str, Any]] = []
    lines = text.splitlines()

    index = 0
    while index < len(lines):
        match = CUE.match(lines[index])
        if not match:
            index += 1
            continue

        start = _timestamp(match.group("start"))
        end = _timestamp(match.group("end"))
        index += 1

        payload: list[str] = []
        while index < len(lines) and lines[index].strip():
            # A cue can be immediately followed by the next one's id line; the
            # blank-line rule is the format's own separator, so trust it and
            # stop at a line that is itself a timing.
            if CUE.match(lines[index]):
                break
            payload.append(TAG.sub("", lines[index]).strip())
            index += 1

        body = " ".join(part for part in payload if part).strip()
        if body and end >= start:
            out.append({"startMs": start, "endMs": end, "text": body})

    return out


def _timestamp(value: str) -> float:
    """`HH:MM:SS.mmm`, `MM:SS.mmm`, or either with a comma, to milliseconds."""
    head, _, fraction = value.replace(",", ".").partition(".")
    parts = [int(p) for p in head.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts
    millis = int(fraction.ljust(3, "0")[:3])
    return ((hours * 3600 + minutes * 60 + seconds) * 1000) + millis


def _renumber(segments: list[dict[str, Any]], offset_ms: float) -> list[NarrationSegment]:
    """Ids are assigned here, in time order, matching `evt_`/`ann_`.

    Whatever ids the source used are discarded on purpose: they have to be
    unique within the recording, and a transcript merged with another one would
    otherwise collide.
    """
    ordered = sorted(segments, key=lambda s: (s["startMs"], s["endMs"]))
    out: list[NarrationSegment] = []
    for position, segment in enumerate(ordered, start=1):
        out.append(
            NarrationSegment(
                id=f"nar_{position:03d}",
                startMs=max(0.0, segment["startMs"] + offset_ms),
                endMs=max(0.0, segment["endMs"] + offset_ms),
                text=segment["text"],
                **({"confidence": segment["confidence"]} if "confidence" in segment else {}),
            )
        )
    return out


def describe(segments: list[NarrationSegment], duration_ms: float) -> str:
    """One line for the CLI, so a wrong offset is visible rather than deducible.

    A transcript mapped outside the recording entirely is the common failure and
    the one worth naming outright -- it is what a voice memo started before the
    browser looks like.
    """
    if not segments:
        return "Narration:  none"

    first = min(s.startMs for s in segments)
    last = max(s.endMs for s in segments)
    line = (
        f"Narration:  {len(segments)} segment(s), "
        f"{first / 1000:.1f}s-{last / 1000:.1f}s, over a {duration_ms / 1000:.1f}s recording"
    )
    if duration_ms > 0 and (first > duration_ms or last <= 0):
        line += "\n            ^ entirely outside the recording. Check --narration-offset."
    return line
