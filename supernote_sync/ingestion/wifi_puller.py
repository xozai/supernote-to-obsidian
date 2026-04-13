"""Pull .note files from a Supernote device via its built-in Wi-Fi HTTP server."""

from __future__ import annotations

import logging
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


class WiFiPuller:
    """Download ``.note`` files from the Supernote Wi-Fi HTTP server.

    The Supernote device exposes a simple HTTP API at
    ``http://<host>:<port>/`` that returns JSON directory listings and serves
    files for download.

    Args:
        host: IP address or hostname of the Supernote device.
        port: HTTP port (default ``8089``).
        dest_dir: Local directory where downloaded files are saved.
    """

    def __init__(self, host: str, port: int, dest_dir: Path) -> None:
        """Initialise the puller."""
        self.base_url = f"http://{host}:{port}"
        self.dest_dir = dest_dir

    def pull(self, remote_path: str = "/") -> int:
        """Recursively download all new ``.note`` files from *remote_path*.

        Args:
            remote_path: Path on the device to start scanning from.

        Returns:
            Number of newly downloaded files.
        """
        self.dest_dir.mkdir(parents=True, exist_ok=True)
        return self._pull_recursive(remote_path)

    def _pull_recursive(self, remote_path: str) -> int:
        """Walk the remote directory tree and download ``.note`` files.

        Args:
            remote_path: Current remote path being scanned.

        Returns:
            Count of files downloaded in this subtree.
        """
        url = f"{self.base_url}{remote_path}"
        logger.debug("Listing remote path: %s", url)
        try:
            resp = requests.get(url, timeout=10)
            resp.raise_for_status()
            entries: list[dict[str, str]] = resp.json()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to list %s: %s", url, exc)
            return 0

        downloaded = 0
        for entry in entries:
            name: str = entry.get("name", "")
            entry_type: str = entry.get("type", "")
            path: str = entry.get("path", "")

            if entry_type == "directory":
                downloaded += self._pull_recursive(path)
            elif name.lower().endswith(".note"):
                if self._download_file(name, path):
                    downloaded += 1

        return downloaded

    def _download_file(self, name: str, remote_path: str) -> bool:
        """Download a single file from *remote_path* to :attr:`dest_dir`.

        Skips the download if the destination file already exists.

        Args:
            name: Filename to use locally.
            remote_path: Full path component of the URL to fetch.

        Returns:
            ``True`` if the file was downloaded, ``False`` if skipped or failed.
        """
        dest = self.dest_dir / Path(name).name  # just the filename, not subdirs
        if dest.exists():
            logger.debug("Skipping already-downloaded file: %s", name)
            return False

        url = f"{self.base_url}{remote_path}"
        logger.info("Downloading %s → %s", url, dest)
        try:
            with requests.get(url, timeout=60, stream=True) as resp:
                resp.raise_for_status()
                with dest.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size=8192):
                        fh.write(chunk)
            logger.info("Downloaded %s (%d bytes)", name, dest.stat().st_size)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to download %s: %s", name, exc)
            if dest.exists():
                dest.unlink()
            return False
