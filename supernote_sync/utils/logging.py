"""Logging configuration for supernote-to-obsidian."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Any

_FORMAT = "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s"


def setup_logging(cfg: dict[str, Any]) -> None:
    """Configure the root logger with console and rotating file handlers.

    A :class:`~logging.StreamHandler` is attached at the configured level.
    A :class:`~logging.handlers.TimedRotatingFileHandler` rotates at midnight
    and retains up to ``max_log_files`` backup files.

    Args:
        cfg: Top-level configuration dictionary.  Expected keys under
            ``cfg["logging"]`` are ``level``, ``log_dir``, and
            ``max_log_files``.
    """
    log_cfg: dict[str, Any] = cfg.get("logging", {})
    level_name: str = log_cfg.get("level", "INFO").upper()
    level: int = getattr(logging, level_name, logging.INFO)
    log_dir = Path(log_cfg.get("log_dir", "~/.supernote-sync/logs")).expanduser()
    max_log_files: int = int(log_cfg.get("max_log_files", 7))

    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "supernote-sync.log"

    formatter = logging.Formatter(_FORMAT)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(log_file),
        when="midnight",
        backupCount=max_log_files,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
