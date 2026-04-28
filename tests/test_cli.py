"""Tests for the CLI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from click.testing import CliRunner

from supernote_sync.cli import main


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Write a minimal config and return its path."""
    vault = tmp_path / "vault"
    vault.mkdir()
    sync = tmp_path / "sync"
    sync.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    cfg = {
        "supernote": {
            "sync_folder": str(sync),
            "wifi": {"enabled": False, "host": "", "port": 8089},
        },
        "ocr": {"engine": "tesseract", "low_confidence_threshold": 0.70,
                "tesseract": {"binary_path": "", "lang": "eng"}},
        "obsidian": {
            "vault_path": str(vault),
            "notes_subfolder": "Notes",
            "attachments_subfolder": "attachments",
            "frontmatter": {"default_tags": ["test"], "extra_fields": {}},
            "git_sync": {"enabled": False},
        },
        "processing": {
            "deduplicate": False,
            "state_dir": str(tmp_path / "state"),
            "render_dpi": 200,
            "output_filename_pattern": "%Y-%m-%d_{note_name}",
        },
        "logging": {"level": "INFO", "log_dir": str(log_dir), "max_log_files": 3},
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


class TestMainGroup:
    """Tests for the main CLI group."""

    def test_help_displays(self) -> None:
        """--help displays usage information."""
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "supernote-sync" in result.output

    def test_missing_config_exits_nonzero(self, tmp_path: Path) -> None:
        """Non-existent config file causes exit code 2 (click path validation)."""
        runner = CliRunner()
        result = runner.invoke(main, ["--config", str(tmp_path / "no_config.yaml"), "once"])
        assert result.exit_code != 0


class TestOnceCommand:
    """Tests for the `once` command."""

    def test_once_no_notes_reports_none_found(self, config_file: Path) -> None:
        """once with no .note files in sync_folder prints warning."""
        runner = CliRunner()
        result = runner.invoke(main, ["--config", str(config_file), "once"])
        assert result.exit_code == 0
        assert "No .note files found" in result.output

    def test_once_with_note_file(self, config_file: Path, tmp_path: Path) -> None:
        """once processes a single .note file when PATH is specified."""
        note = tmp_path / "test.note"
        note.write_bytes(b"\x00" * 16)

        mock_pipeline = MagicMock()
        mock_pipeline.process_file.return_value = True

        runner = CliRunner()
        with patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline):
            result = runner.invoke(
                main, ["--config", str(config_file), "once", str(note)]
            )

        assert result.exit_code == 0
        mock_pipeline.process_file.assert_called_once_with(note, force=False)

    def test_once_with_directory(self, config_file: Path, tmp_path: Path) -> None:
        """once processes all .note files in a directory when PATH is a dir."""
        note_dir = tmp_path / "notes"
        note_dir.mkdir()
        (note_dir / "a.note").write_bytes(b"\x00")
        (note_dir / "b.note").write_bytes(b"\x00")
        (note_dir / "c.txt").write_bytes(b"not a note")

        mock_pipeline = MagicMock()
        mock_pipeline.process_file.return_value = True

        runner = CliRunner()
        with patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline):
            result = runner.invoke(
                main, ["--config", str(config_file), "once", str(note_dir)]
            )

        assert result.exit_code == 0
        assert mock_pipeline.process_file.call_count == 2

    def test_once_with_non_note_path(self, config_file: Path, tmp_path: Path) -> None:
        """once warns and returns when PATH is not a .note file or directory."""
        txt_file = tmp_path / "document.txt"
        txt_file.write_text("hello")

        runner = CliRunner()
        result = runner.invoke(
            main, ["--config", str(config_file), "once", str(txt_file)]
        )
        assert result.exit_code == 0
        assert "Not a .note file" in result.output


class TestPullCommand:
    """Tests for the `pull` command."""

    def test_pull_disabled_prints_message(self, config_file: Path) -> None:
        """pull warns when wifi.enabled=False."""
        runner = CliRunner()
        result = runner.invoke(main, ["--config", str(config_file), "pull"])
        assert result.exit_code == 0
        assert "disabled" in result.output.lower()

    def test_pull_enabled_calls_wifi_puller(self, config_file: Path, tmp_path: Path) -> None:
        """pull calls WiFiPuller when wifi.enabled=True."""
        import yaml  # noqa: PLC0415

        cfg = yaml.safe_load(config_file.read_text())
        cfg["supernote"]["wifi"]["enabled"] = True
        cfg["supernote"]["wifi"]["host"] = "192.168.1.100"
        config_file.write_text(yaml.dump(cfg))

        mock_puller = MagicMock()
        mock_puller.pull.return_value = 3

        runner = CliRunner()
        with patch("supernote_sync.ingestion.wifi_puller.WiFiPuller", return_value=mock_puller):
            result = runner.invoke(main, ["--config", str(config_file), "pull"])

        assert result.exit_code == 0
        assert "3" in result.output
        mock_puller.pull.assert_called_once()


def test_status_empty_sync_folder(tmp_path, mocker):
    """status command with empty sync folder prints 0 processed, 0 pending."""
    from click.testing import CliRunner

    from supernote_sync.cli import main

    cfg = {
        "supernote": {"sync_folder": str(tmp_path), "wifi": {"enabled": False}},
        "obsidian": {"vault_path": str(tmp_path / "vault")},
        "ocr": {"engine": "tesseract", "low_confidence_threshold": 0.7},
        "processing": {
            "deduplicate": False, "state_dir": str(tmp_path / "state"), "render_dpi": 200
        },
        "logging": {"level": "WARNING", "log_dir": str(tmp_path / "logs"), "max_log_files": 3},
    }
    mocker.patch("supernote_sync.cli.load_config", return_value=cfg)
    mocker.patch("supernote_sync.cli.setup_logging")

    runner = CliRunner()
    # Create a dummy config file so --config path check doesn't fail
    config_file = tmp_path / "config.yaml"
    config_file.write_text("dummy: true")

    result = runner.invoke(main, ["--config", str(config_file), "status"])
    assert "0 processed, 0 pending" in result.output
