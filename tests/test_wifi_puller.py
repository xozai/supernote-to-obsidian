"""Tests for WiFiPuller."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from supernote_sync.ingestion.wifi_puller import WiFiPuller


@pytest.fixture()
def dest_dir(tmp_path: Path) -> Path:
    """Return a temporary destination directory."""
    d = tmp_path / "sync"
    d.mkdir()
    return d


@pytest.fixture()
def puller(dest_dir: Path) -> WiFiPuller:
    """Return a WiFiPuller pointed at the temp dir."""
    return WiFiPuller(host="192.168.1.100", port=8089, dest_dir=dest_dir)


class TestWiFiPuller:
    """Tests for WiFiPuller.pull()."""

    def test_pull_returns_zero_when_no_files(self, puller: WiFiPuller) -> None:
        """pull() returns 0 when the listing is empty."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_resp.raise_for_status.return_value = None

        with patch("requests.get", return_value=mock_resp):
            count = puller.pull()

        assert count == 0

    def test_pull_downloads_note_files(self, puller: WiFiPuller, dest_dir: Path) -> None:
        """pull() downloads .note files and returns correct count."""
        listing = [{"name": "my_note.note", "type": "file", "path": "/my_note.note"}]

        list_resp = MagicMock()
        list_resp.json.return_value = listing
        list_resp.raise_for_status.return_value = None

        # Stream response
        file_resp = MagicMock()
        file_resp.raise_for_status.return_value = None
        file_resp.iter_content.return_value = [b"fake note bytes"]
        file_resp.__enter__ = lambda s: s
        file_resp.__exit__ = MagicMock(return_value=False)

        with patch("requests.get", side_effect=[list_resp, file_resp]):
            count = puller.pull()

        assert count == 1
        assert (dest_dir / "my_note.note").exists()

    def test_pull_skips_existing_files(self, puller: WiFiPuller, dest_dir: Path) -> None:
        """pull() skips files that already exist locally."""
        existing = dest_dir / "existing.note"
        existing.write_bytes(b"already here")

        listing = [{"name": "existing.note", "type": "file", "path": "/existing.note"}]
        list_resp = MagicMock()
        list_resp.json.return_value = listing
        list_resp.raise_for_status.return_value = None

        with patch("requests.get", return_value=list_resp):
            count = puller.pull()

        assert count == 0

    def test_pull_recurses_into_directories(self, puller: WiFiPuller, dest_dir: Path) -> None:
        """pull() recurses into sub-directories."""
        root_listing = [{"name": "subdir", "type": "directory", "path": "/subdir"}]
        sub_listing = [{"name": "nested.note", "type": "file", "path": "/subdir/nested.note"}]

        root_resp = MagicMock()
        root_resp.json.return_value = root_listing
        root_resp.raise_for_status.return_value = None

        sub_resp = MagicMock()
        sub_resp.json.return_value = sub_listing
        sub_resp.raise_for_status.return_value = None

        file_resp = MagicMock()
        file_resp.raise_for_status.return_value = None
        file_resp.iter_content.return_value = [b"note content"]
        file_resp.__enter__ = lambda s: s
        file_resp.__exit__ = MagicMock(return_value=False)

        with patch("requests.get", side_effect=[root_resp, sub_resp, file_resp]):
            count = puller.pull()

        assert count == 1

    def test_pull_returns_zero_on_listing_error(self, puller: WiFiPuller) -> None:
        """pull() returns 0 when listing request fails."""
        with patch("requests.get", side_effect=ConnectionError("no network")):
            count = puller.pull()
        assert count == 0

    def test_pull_ignores_non_note_files(self, puller: WiFiPuller) -> None:
        """pull() ignores files that don't end in .note."""
        listing = [
            {"name": "document.pdf", "type": "file", "path": "/document.pdf"},
            {"name": "image.png", "type": "file", "path": "/image.png"},
        ]
        list_resp = MagicMock()
        list_resp.json.return_value = listing
        list_resp.raise_for_status.return_value = None

        with patch("requests.get", return_value=list_resp):
            count = puller.pull()

        assert count == 0

    def test_download_uses_basename_for_nested_path(self, puller: WiFiPuller, dest_dir: Path) -> None:
        """_download_file uses only the basename when remote path contains subdirectories."""
        file_resp = MagicMock()
        file_resp.raise_for_status.return_value = None
        file_resp.iter_content.return_value = [b"data"]
        file_resp.__enter__ = lambda s: s
        file_resp.__exit__ = MagicMock(return_value=False)

        with patch("requests.get", return_value=file_resp):
            result = puller._download_file("my_note.note", "/note/subdir/my_note.note")

        assert result is True
        assert (dest_dir / "my_note.note").exists()
        assert not (dest_dir / "note" / "subdir" / "my_note.note").exists()
