"""Tests for utils/logging.py."""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path

import pytest

from supernote_sync.utils.logging import setup_logging


@pytest.fixture(autouse=True)
def reset_root_logger() -> None:
    """Remove handlers added by setup_logging after each test."""
    yield
    root = logging.getLogger()
    for handler in root.handlers[:]:
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:  # noqa: BLE001
            pass


class TestSetupLogging:
    """Tests for setup_logging()."""

    def test_adds_stream_handler(self, tmp_path: Path) -> None:
        """setup_logging adds a StreamHandler to the root logger."""
        cfg = {"logging": {"level": "INFO", "log_dir": str(tmp_path), "max_log_files": 3}}
        setup_logging(cfg)
        root = logging.getLogger()
        stream_handlers = [h for h in root.handlers if isinstance(h, logging.StreamHandler)
                           and not isinstance(h, logging.handlers.TimedRotatingFileHandler)]
        assert len(stream_handlers) >= 1

    def test_adds_file_handler(self, tmp_path: Path) -> None:
        """setup_logging adds a TimedRotatingFileHandler."""
        cfg = {"logging": {"level": "DEBUG", "log_dir": str(tmp_path), "max_log_files": 5}}
        setup_logging(cfg)
        root = logging.getLogger()
        file_handlers = [
            h for h in root.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
        ]
        assert len(file_handlers) >= 1

    def test_creates_log_dir(self, tmp_path: Path) -> None:
        """setup_logging creates the log directory if it does not exist."""
        log_dir = tmp_path / "new" / "log" / "dir"
        cfg = {"logging": {"level": "INFO", "log_dir": str(log_dir), "max_log_files": 3}}
        setup_logging(cfg)
        assert log_dir.exists()

    def test_sets_root_level(self, tmp_path: Path) -> None:
        """setup_logging sets the root logger level."""
        cfg = {"logging": {"level": "WARNING", "log_dir": str(tmp_path), "max_log_files": 3}}
        setup_logging(cfg)
        assert logging.getLogger().level == logging.WARNING

    def test_defaults_used_when_cfg_missing(self, tmp_path: Path) -> None:
        """setup_logging works with an empty logging section."""
        # Override log_dir to avoid writing to home dir
        cfg: dict = {}
        # Monkey-patch expanduser to use tmp_path
        import supernote_sync.utils.logging as log_module  # noqa: PLC0415
        from unittest.mock import patch  # noqa: PLC0415

        with patch.object(
            Path,
            "expanduser",
            return_value=tmp_path / "logs",
        ):
            setup_logging(cfg)

        root = logging.getLogger()
        assert root.level == logging.INFO
