"""The step library (SS12): approved phrasing, remembered across recordings."""

from pathlib import Path

from server.library.store import (
    DEFAULT_PROJECT,
    REUSE_THRESHOLD,
    SUGGEST_THRESHOLD,
    LibraryEntry,
    Match,
    StepLibrary,
)
from server.storage.paths import REPO_ROOT

#: Local state, alongside the cassettes and the budget file. Gitignored like
#: everything under `runs/`, and worth carrying between machines for the same
#: reason the cassettes are: it is accumulated work, not derived output.
LIBRARY_PATH = REPO_ROOT / "runs" / "_library.db"


def library_path() -> Path:
    return LIBRARY_PATH


__all__ = [
    "LIBRARY_PATH",
    "library_path",
    "DEFAULT_PROJECT",
    "REUSE_THRESHOLD",
    "SUGGEST_THRESHOLD",
    "LibraryEntry",
    "Match",
    "StepLibrary",
]
