"""Load `.env` into the environment.

A four-line dependency is not worth taking for this. Real environment
variables always win over the file, so a shell export or a CI secret overrides
whatever is on disk -- which is the behaviour people expect and the one that
avoids a stale local file quietly beating a deliberate override.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_env(path: Path | None = None, *, override: bool = False) -> dict[str, str]:
    """Read `KEY=value` lines. Returns the names it set, never the values."""
    env_path = path or REPO_ROOT / ".env"
    loaded: dict[str, str] = {}
    if not env_path.exists():
        return loaded

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("\"'")
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
            loaded[key] = "set"
    return loaded
