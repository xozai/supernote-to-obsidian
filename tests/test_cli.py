"""Tests for the CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any
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


class TestOnceFilters:
    """Tests for --since, --until, --tag, and --dry-run on the `once` command."""

    def test_since_filters_out_old_files(
        self, config_file: Path, tmp_path: Path
    ) -> None:
        """--since excludes files modified before the given date."""

        note_dir = tmp_path / "notes"
        note_dir.mkdir()
        old_note = note_dir / "old.note"
        old_note.write_bytes(b"\x00")
        # Force mtime to 2000-01-01
        old_ts = 946684800.0  # 2000-01-01 UTC
        import os
        os.utime(old_note, (old_ts, old_ts))

        mock_pipeline = MagicMock()
        mock_pipeline.process_file.return_value = True

        runner = CliRunner()
        with patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline):
            result = runner.invoke(
                main,
                ["--config", str(config_file), "once", str(note_dir), "--since", "2025-01-01"],
            )

        assert result.exit_code == 0
        # old_note should be filtered out → nothing processed
        assert "No .note files found" in result.output

    def test_until_filters_out_new_files(
        self, config_file: Path, tmp_path: Path
    ) -> None:
        """--until excludes files modified after the given date."""
        import os

        note_dir = tmp_path / "notes"
        note_dir.mkdir()
        future_note = note_dir / "future.note"
        future_note.write_bytes(b"\x00")
        # Force mtime to 2099-12-31
        future_ts = 4102444800.0
        os.utime(future_note, (future_ts, future_ts))

        mock_pipeline = MagicMock()
        mock_pipeline.process_file.return_value = True

        runner = CliRunner()
        with patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline):
            result = runner.invoke(
                main,
                ["--config", str(config_file), "once", str(note_dir), "--until", "2025-01-01"],
            )

        assert result.exit_code == 0
        assert "No .note files found" in result.output

    def test_dry_run_prints_table_without_processing(
        self, config_file: Path, tmp_path: Path
    ) -> None:
        """--dry-run prints a preview table and does not call process_file."""
        note = tmp_path / "test.note"
        note.write_bytes(b"\x00" * 16)

        mock_pipeline = MagicMock()
        mock_pipeline._dedup_enabled = False
        mock_pipeline._dedup = None

        runner = CliRunner()
        with patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline):
            result = runner.invoke(
                main,
                ["--config", str(config_file), "once", str(note), "--dry-run"],
            )

        assert result.exit_code == 0
        assert "test.note" in result.output
        assert "would be processed" in result.output
        mock_pipeline.process_file.assert_not_called()

    def test_dry_run_with_force_shows_force_suffix(
        self, config_file: Path, tmp_path: Path
    ) -> None:
        """--dry-run --force shows the (force) label."""
        note = tmp_path / "test.note"
        note.write_bytes(b"\x00" * 16)

        mock_pipeline = MagicMock()
        mock_pipeline._dedup_enabled = False
        mock_pipeline._dedup = None

        runner = CliRunner()
        with patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline):
            result = runner.invoke(
                main,
                ["--config", str(config_file), "once", str(note), "--dry-run", "--force"],
            )

        assert result.exit_code == 0
        assert "force" in result.output.lower()

    def test_since_bad_date_exits_nonzero(self, config_file: Path) -> None:
        """--since with a bad date string exits with a non-zero code."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["--config", str(config_file), "once", "--since", "not-a-date"]
        )
        assert result.exit_code != 0

    def test_until_bad_date_exits_nonzero(self, config_file: Path) -> None:
        """--until with a bad date string exits with a non-zero code."""
        runner = CliRunner()
        result = runner.invoke(
            main, ["--config", str(config_file), "once", "--until", "31/12/2025"]
        )
        assert result.exit_code != 0


class TestRunSummary:
    """Tests for the per-run summary line in `once`."""

    def test_summary_shows_new_count(self, config_file: Path, tmp_path: Path) -> None:
        """Run summary includes 'N new' when new files are processed."""
        note = tmp_path / "fresh.note"
        note.write_bytes(b"\x00" * 16)

        mock_pipeline = MagicMock()
        mock_pipeline.process_file.return_value = True
        mock_pipeline._dedup_enabled = True
        mock_dedup = MagicMock()
        mock_dedup.already_processed.return_value = False
        mock_dedup.is_modified.return_value = False
        mock_pipeline._dedup = mock_dedup

        runner = CliRunner()
        with patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline):
            result = runner.invoke(
                main, ["--config", str(config_file), "once", str(note)]
            )

        assert result.exit_code == 0
        assert "1 new" in result.output

    def test_summary_shows_skipped_count(
        self, config_file: Path, tmp_path: Path
    ) -> None:
        """Run summary includes 'N skipped' when files are already processed."""
        note = tmp_path / "done.note"
        note.write_bytes(b"\x00" * 16)

        mock_pipeline = MagicMock()
        mock_pipeline.process_file.return_value = False
        mock_pipeline._dedup_enabled = True
        mock_dedup = MagicMock()
        mock_dedup.already_processed.return_value = True
        mock_dedup.is_modified.return_value = False
        mock_pipeline._dedup = mock_dedup

        runner = CliRunner()
        with patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline):
            result = runner.invoke(
                main, ["--config", str(config_file), "once", str(note)]
            )

        assert result.exit_code == 0
        assert "1 skipped" in result.output

    def test_summary_shows_modified_count(
        self, config_file: Path, tmp_path: Path
    ) -> None:
        """Run summary includes 'N modified' when re-exported files are processed."""
        note = tmp_path / "changed.note"
        note.write_bytes(b"\x00" * 16)

        mock_pipeline = MagicMock()
        mock_pipeline.process_file.return_value = True
        mock_pipeline._dedup_enabled = True
        mock_dedup = MagicMock()
        mock_dedup.already_processed.return_value = False
        mock_dedup.is_modified.return_value = True
        mock_pipeline._dedup = mock_dedup

        runner = CliRunner()
        with patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline):
            result = runner.invoke(
                main, ["--config", str(config_file), "once", str(note)]
            )

        assert result.exit_code == 0
        assert "1 modified" in result.output


class TestScheduleCommand:
    """Tests for the `schedule` command."""

    def test_schedule_calls_process_file(
        self, config_file: Path, tmp_path: Path
    ) -> None:
        """schedule runs process_file for each .note in the sync folder."""
        import yaml

        cfg = yaml.safe_load(config_file.read_text())
        sync = Path(cfg["supernote"]["sync_folder"])
        sync.mkdir(parents=True, exist_ok=True)
        (sync / "a.note").write_bytes(b"\x00")

        mock_pipeline = MagicMock()
        mock_pipeline.process_file.return_value = True

        # APScheduler's BlockingScheduler.start() blocks; patch it to return immediately
        mock_scheduler = MagicMock()
        mock_scheduler.start.side_effect = KeyboardInterrupt

        runner = CliRunner()
        with (
            patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline),
            patch(
                "apscheduler.schedulers.blocking.BlockingScheduler",
                return_value=mock_scheduler,
            ),
        ):
            result = runner.invoke(
                main, ["--config", str(config_file), "schedule", "--interval", "60"]
            )

        assert result.exit_code == 0
        # process_file called at least once (the immediate first run)
        mock_pipeline.process_file.assert_called()

    def test_schedule_no_notes_prints_warning(self, config_file: Path) -> None:
        """schedule prints a warning when the sync folder is empty."""
        mock_pipeline = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.start.side_effect = KeyboardInterrupt

        runner = CliRunner()
        with (
            patch("supernote_sync.pipeline.Pipeline", return_value=mock_pipeline),
            patch(
                "apscheduler.schedulers.blocking.BlockingScheduler",
                return_value=mock_scheduler,
            ),
        ):
            result = runner.invoke(
                main, ["--config", str(config_file), "schedule"]
            )

        assert result.exit_code == 0
        assert "No .note files found" in result.output


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


def test_status_shows_modified_files(tmp_path: Path, mocker: Any) -> None:
    """status shows 'modified' for files in the dedup cache with changed content."""
    from click.testing import CliRunner

    from supernote_sync.cli import main
    from supernote_sync.utils.dedup import DedupCache

    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    note = sync_dir / "changed.note"
    note.write_bytes(b"original content")

    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # Mark as processed, then change the file content
    cache = DedupCache(state_dir)
    cache.mark_processed(note)
    note.write_bytes(b"re-exported different content")

    cfg = {
        "supernote": {"sync_folder": str(sync_dir), "wifi": {"enabled": False}},
        "obsidian": {"vault_path": str(tmp_path / "vault")},
        "ocr": {"engine": "tesseract", "low_confidence_threshold": 0.7},
        "processing": {
            "deduplicate": True, "state_dir": str(state_dir), "render_dpi": 200
        },
        "logging": {
            "level": "WARNING", "log_dir": str(tmp_path / "logs"), "max_log_files": 3
        },
    }
    mocker.patch("supernote_sync.cli.load_config", return_value=cfg)
    mocker.patch("supernote_sync.cli.setup_logging")

    config_file = tmp_path / "config.yaml"
    config_file.write_text("dummy: true")

    runner = CliRunner()
    result = runner.invoke(main, ["--config", str(config_file), "status"])
    assert "modified" in result.output
