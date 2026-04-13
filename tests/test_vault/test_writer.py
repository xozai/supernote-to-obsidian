"""Tests for VaultWriter."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from supernote_sync.vault.writer import VaultWriter


@pytest.fixture()
def vault_path(tmp_path: Path) -> Path:
    """Return a temporary vault path."""
    v = tmp_path / "vault"
    v.mkdir()
    return v


@pytest.fixture()
def cfg(vault_path: Path) -> dict:
    """Return config pointing at the temporary vault."""
    return {
        "obsidian": {
            "vault_path": str(vault_path),
            "notes_subfolder": "Notes",
            "attachments_subfolder": "attachments",
            "git_sync": {"enabled": False},
        }
    }


@pytest.fixture()
def cfg_with_git(vault_path: Path) -> dict:
    """Return config with git_sync enabled."""
    return {
        "obsidian": {
            "vault_path": str(vault_path),
            "notes_subfolder": "Notes",
            "attachments_subfolder": "attachments",
            "git_sync": {
                "enabled": True,
                "commit_message": "chore: sync {timestamp}",
                "remote": "origin",
                "branch": "main",
            },
        }
    }


def _make_document(vault_path: Path, content: str = "# Test", has_attachments: bool = True) -> MagicMock:
    """Return a mock Document."""
    doc = MagicMock()
    doc.output_path = vault_path / "Notes" / "test_note.md"
    doc.render.return_value = content
    if has_attachments:
        doc.attachments = [("page000.png", b"\x89PNG\r\n")]
    else:
        doc.attachments = []
    return doc


class TestVaultWriter:
    """Tests for VaultWriter.write()."""

    def test_write_creates_markdown_file(self, cfg: dict, vault_path: Path) -> None:
        """write() creates the markdown file."""
        writer = VaultWriter(cfg)
        doc = _make_document(vault_path)
        writer.write(doc)
        assert doc.output_path.exists()

    def test_write_markdown_file_has_correct_content(self, cfg: dict, vault_path: Path) -> None:
        """write() saves the rendered content."""
        writer = VaultWriter(cfg)
        doc = _make_document(vault_path, content="# My Note\n\nHello")
        writer.write(doc)
        assert doc.output_path.read_text() == "# My Note\n\nHello"

    def test_write_creates_attachment_files(self, cfg: dict, vault_path: Path) -> None:
        """write() saves attachment files."""
        writer = VaultWriter(cfg)
        doc = _make_document(vault_path)
        writer.write(doc)
        attachment_path = vault_path / "attachments" / "page000.png"
        assert attachment_path.exists()
        assert attachment_path.read_bytes() == b"\x89PNG\r\n"

    def test_write_creates_parent_directories(self, cfg: dict, vault_path: Path) -> None:
        """write() creates parent directories recursively."""
        writer = VaultWriter(cfg)
        doc = MagicMock()
        doc.output_path = vault_path / "Notes" / "deep" / "nested" / "note.md"
        doc.render.return_value = "# Deep"
        doc.attachments = []
        writer.write(doc)
        assert doc.output_path.exists()

    def test_git_called_three_times_when_enabled(self, cfg_with_git: dict, vault_path: Path) -> None:
        """git subprocess is called 3 times (add, commit, push) when git_sync.enabled=True."""
        writer = VaultWriter(cfg_with_git)
        doc = _make_document(vault_path, has_attachments=False)
        doc.output_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            writer.write(doc)

        assert mock_run.call_count == 3

    def test_git_not_called_when_disabled(self, cfg: dict, vault_path: Path) -> None:
        """git subprocess is not called when git_sync.enabled=False."""
        writer = VaultWriter(cfg)
        doc = _make_document(vault_path, has_attachments=False)
        doc.output_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("subprocess.run") as mock_run:
            writer.write(doc)

        mock_run.assert_not_called()

    def test_git_error_does_not_propagate(self, cfg_with_git: dict, vault_path: Path) -> None:
        """CalledProcessError during git does not propagate out of write()."""
        writer = VaultWriter(cfg_with_git)
        doc = _make_document(vault_path, has_attachments=False)
        doc.output_path.parent.mkdir(parents=True, exist_ok=True)

        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "git")):
            # Should not raise
            writer.write(doc)
