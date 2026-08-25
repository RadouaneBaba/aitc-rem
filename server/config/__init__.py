"""Project-level configuration: how the output reads, and where it may be sent."""

from server.config.project import (
    KNOWN_VOICES,
    KNOWN_WHISPER_MODELS,
    ProjectConfig,
    load_allowed_origins,
    load_project_config,
    normalise_origin,
)

__all__ = [
    "KNOWN_VOICES",
    "KNOWN_WHISPER_MODELS",
    "ProjectConfig",
    "load_allowed_origins",
    "normalise_origin",
    "load_project_config",
]
