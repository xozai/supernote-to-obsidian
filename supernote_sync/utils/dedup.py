"""File deduplication cache backed by MD5 hashes."""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_CHUNK_SIZE = 8 * 1024  # 8 KB
_CACHE_FILENAME = "processed_hashes.json"


class DedupCache:
    """Persist a ``{filename: md5hex}`` mapping to detect already-processed files.

    The cache is stored in ``<state_dir>/processed_hashes.json``.

    Args:
        state_dir: Directory where the JSON cache file is kept.
    """

    def __init__(self, state_dir: Path) -> None:
        """Initialise and load the existing cache from disk."""
        self.state_dir = state_dir
        self._cache_path = state_dir / _CACHE_FILENAME
        self._data: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        """Load the JSON cache from disk, returning an empty dict if absent.

        Returns:
            The persisted ``{filename: md5hex}`` mapping.
        """
        if self._cache_path.exists():
            try:
                with self._cache_path.open("r", encoding="utf-8") as fh:
                    data: dict[str, str] = json.load(fh)
                    logger.debug("Loaded %d cached hash(es) from %s", len(data), self._cache_path)
                    return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Could not load dedup cache: %s", exc)
        return {}

    def _save(self) -> None:
        """Persist the in-memory cache to disk."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        try:
            with self._cache_path.open("w", encoding="utf-8") as fh:
                json.dump(self._data, fh, indent=2)
        except OSError as exc:
            logger.error("Failed to save dedup cache: %s", exc)

    @staticmethod
    def _md5(path: Path) -> str:
        """Compute the MD5 hex digest of a file in 8 KB chunks.

        Args:
            path: File to hash.

        Returns:
            Lowercase hexadecimal MD5 string.
        """
        h = hashlib.md5()
        with path.open("rb") as fh:
            while chunk := fh.read(_CHUNK_SIZE):
                h.update(chunk)
        return h.hexdigest()

    def already_processed(self, path: Path) -> bool:
        """Return ``True`` if *path* has already been successfully processed.

        Compares the stored MD5 of the file against its current MD5.  A
        changed file (e.g. re-exported with different content) is considered
        new and returns ``False``.

        Args:
            path: Path to the ``.note`` file to check.

        Returns:
            ``True`` only when the stored hash matches the current file hash.
        """
        key = str(path)
        if key not in self._data:
            return False
        try:
            current_hash = self._md5(path)
        except OSError as exc:
            logger.warning("Could not hash %s for dedup check: %s", path, exc)
            return False
        return self._data[key] == current_hash

    def mark_processed(self, path: Path) -> None:
        """Record *path* as successfully processed.

        Computes the current MD5 and persists the cache.

        Args:
            path: Path to the ``.note`` file that was just processed.
        """
        try:
            self._data[str(path)] = self._md5(path)
            self._save()
        except OSError as exc:
            logger.error("Could not mark %s as processed: %s", path, exc)
