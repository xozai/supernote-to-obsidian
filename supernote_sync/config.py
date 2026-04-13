"""Configuration loading and validation for supernote-to-obsidian."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _expand_paths(obj: Any) -> Any:
    """Recursively expand ``~`` in all string values within a nested dict/list."""
    if isinstance(obj, dict):
        return {k: _expand_paths(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_expand_paths(item) for item in obj]
    if isinstance(obj, str) and obj.startswith("~"):
        return str(Path(obj).expanduser())
    return obj


def load_config(path: Path) -> dict[str, Any]:
    """Load and return configuration from a YAML file.

    All string values that start with ``~`` are expanded via
    :func:`pathlib.Path.expanduser`.

    Args:
        path: Path to the YAML configuration file.

    Returns:
        A nested dictionary of configuration values.

    Raises:
        FileNotFoundError: If *path* does not exist.
        yaml.YAMLError: If the file cannot be parsed.
    """
    logger.debug("Loading configuration from %s", path)
    with path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    expanded: dict[str, Any] = _expand_paths(raw)
    logger.debug("Configuration loaded successfully")
    return expanded
