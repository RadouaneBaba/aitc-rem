"""The Storage seam (SS16).

Local filesystem now, S3 later. Roughly sixty lines of indirection buys the
whole hosted path, so the shape is fixed here even though only one
implementation exists.

Layout, per SS8.2 and SS9.11:

    recordings/<recordingId>/recording.json
    recordings/<recordingId>/screens/evt_001.png
    runs/<recordingId>/<runId>/segments.json
    runs/<recordingId>/<runId>/ir.json
    runs/<recordingId>/<runId>/trace.json
    runs/<recordingId>/<runId>/tools/tc_0447.json
    runs/<recordingId>/<runId>/cassettes/<hash>.json

Every stage reads a file and writes a file, so when output is wrong you open the
intermediate artifact and see exactly which stage lied (SS9.1).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from server.util.canonical import canonical_json

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RECORDINGS = REPO_ROOT / "recordings"
DEFAULT_RUNS = REPO_ROOT / "runs"


@dataclass(frozen=True)
class RunPaths:
    """Where one run's artifacts live."""

    recording_id: str
    run_id: str
    root: Path

    @property
    def tools(self) -> Path:
        return self.root / "tools"

    @property
    def cassettes(self) -> Path:
        return self.root / "cassettes"

    def artifact(self, stage: str) -> Path:
        return self.root / f"{stage}.json"

    def tool_response(self, tool_call_id: str) -> Path:
        return self.tools / f"{tool_call_id}.json"

    def relative(self, path: Path) -> str:
        """Paths are stored relative to the run root so a run stays portable."""
        return path.relative_to(self.root).as_posix()


class Storage:
    """Local filesystem implementation of the SS16 Storage seam."""

    def __init__(
        self,
        recordings_dir: Path | None = None,
        runs_dir: Path | None = None,
    ) -> None:
        self.recordings_dir = recordings_dir or DEFAULT_RECORDINGS
        self.runs_dir = runs_dir or DEFAULT_RUNS

    # -- recordings --------------------------------------------------------

    def recording_path(self, recording_id: str) -> Path:
        return self.recordings_dir / recording_id / "recording.json"

    def load_recording_json(self, recording_id: str) -> dict[str, Any]:
        return json.loads(self.recording_path(recording_id).read_text(encoding="utf-8"))

    def save_recording_json(self, recording_id: str, data: dict[str, Any]) -> Path:
        path = self.recording_path(recording_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def save_recording(self, recording: Any) -> Path:
        """Write a `Recording` model back out, in the schema's own vocabulary.

        **`by_alias=True` is the entire reason this exists.** `from` is a Python
        keyword, so codegen emits `from_ = Field(..., alias="from")` on
        `UrlChange`. Dumping without the alias writes `from_`, which the schema
        forbids -- so the file is written successfully and then fails to
        validate on every subsequent read. Nothing complains at write time; the
        recording is simply poisoned, and the error surfaces later somewhere
        unrelated.

        Call sites kept getting this wrong because the wrong version looks
        right, so the correct dump lives here and takes a model rather than a
        dict. If you find yourself writing `model_dump_json` against a
        Recording, use this instead.
        """
        return self.save_recording_json(
            recording.id,
            json.loads(recording.model_dump_json(by_alias=True, exclude_none=True)),
        )

    def audio_path(self, recording_id: str) -> Path:
        """Narration audio, beside its recording (SS7.5).

        Kept rather than discarded after transcription, and that is the whole
        design: narration is the only lossy evidence source here, a browser
        cannot re-check something a person said out loud, and a human listening
        to the clip is the only verification such a claim can have.
        """
        return self.recordings_dir / recording_id / "audio.webm"

    def save_audio(self, recording_id: str, data: bytes) -> Path:
        path = self.audio_path(recording_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def screenshot_path(self, recording_id: str, event_id: str) -> Path:
        """Where one event's screenshot lives.

        SS7.4: a screenshot is never sent to a model. It is captured for the
        human reviewing the step, and this layout has been in the docstring
        above since Phase 1 while nothing wrote to it -- the recorder took the
        pictures and only the "save to Downloads" path ever kept them, so the
        `screenshot` field on every posted recording pointed at a file the
        server did not have.

        The event id is validated rather than trusted: it arrives from an HTTP
        path and is about to become a filename.
        """
        if not event_id or not event_id.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"not a usable event id for a filename: {event_id!r}")
        return self.recordings_dir / recording_id / "screens" / f"{event_id}.png"

    def save_screenshot(self, recording_id: str, event_id: str, data: bytes) -> Path:
        path = self.screenshot_path(recording_id, event_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def list_recordings(self) -> list[str]:
        if not self.recordings_dir.exists():
            return []
        return sorted(
            p.name for p in self.recordings_dir.iterdir() if (p / "recording.json").exists()
        )

    # -- runs --------------------------------------------------------------

    def run(self, recording_id: str, run_id: str) -> RunPaths:
        root = self.runs_dir / recording_id / run_id
        root.mkdir(parents=True, exist_ok=True)
        (root / "tools").mkdir(exist_ok=True)
        return RunPaths(recording_id=recording_id, run_id=run_id, root=root)

    def existing_run(self, recording_id: str, run_id: str) -> RunPaths:
        """The same paths, without creating anything.

        `run()` is for a pipeline about to write; every READ path in the API
        called it too, so a GET for a run that does not exist left an empty
        `runs/<rec>/<run>/tools/` behind before returning 404 -- and the review
        UI lists runs by globbing that directory, so a typo in a URL created a
        row in it.
        """
        root = self.runs_dir / recording_id / run_id
        return RunPaths(recording_id=recording_id, run_id=run_id, root=root)

    def save_artifact(self, run: RunPaths, stage: str, data: Any) -> Path:
        """Stage output. Indented for reading, since these get opened by hand."""
        path = run.artifact(stage)
        payload = (
            data.model_dump(mode="json", exclude_none=True) if hasattr(data, "model_dump") else data
        )
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def save_tool_response(self, run: RunPaths, tool_call_id: str, data: Any) -> Path:
        """Tool responses are written in canonical form, NOT indented.

        The stored bytes are what `evidence_retrieved` re-hashes, so they have
        to match `canonical_json` exactly (SS3.2).
        """
        path = run.tool_response(tool_call_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(canonical_json(data), encoding="utf-8")
        return path

    def load_tool_response(self, run: RunPaths, tool_call_id: str) -> Any:
        return json.loads(run.tool_response(tool_call_id).read_text(encoding="utf-8"))
