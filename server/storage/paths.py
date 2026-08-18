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
