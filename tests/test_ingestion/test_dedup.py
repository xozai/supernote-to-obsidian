"""Tests for DedupCache."""

from __future__ import annotations

from pathlib import Path

import pytest

from supernote_sync.utils.dedup import DedupCache


@pytest.fixture()
def state_dir(tmp_path: Path) -> Path:
    """Return a temporary state directory."""
    d = tmp_path / "state"
    d.mkdir()
    return d


@pytest.fixture()
def note_file(tmp_path: Path) -> Path:
    """Return a temporary file with some content."""
    f = tmp_path / "my_note.note"
    f.write_bytes(b"hello supernote")
    return f


class TestDedupCache:
    """Tests for the deduplication cache."""

    def test_new_file_not_already_processed(self, state_dir: Path, note_file: Path) -> None:
        """A new file should not be flagged as already processed."""
        cache = DedupCache(state_dir)
        assert cache.already_processed(note_file) is False

    def test_mark_then_check_returns_true(self, state_dir: Path, note_file: Path) -> None:
        """After marking, already_processed returns True."""
        cache = DedupCache(state_dir)
        cache.mark_processed(note_file)
        assert cache.already_processed(note_file) is True

    def test_modified_file_not_duplicate(self, state_dir: Path, note_file: Path) -> None:
        """A file with changed content is not a duplicate."""
        cache = DedupCache(state_dir)
        cache.mark_processed(note_file)
        note_file.write_bytes(b"completely different content")
        assert cache.already_processed(note_file) is False

    def test_cache_persists_across_instances(self, state_dir: Path, note_file: Path) -> None:
        """Cache survives creating a new DedupCache from the same state_dir."""
        cache1 = DedupCache(state_dir)
        cache1.mark_processed(note_file)

        cache2 = DedupCache(state_dir)
        assert cache2.already_processed(note_file) is True

    def test_two_files_tracked_independently(self, state_dir: Path, tmp_path: Path) -> None:
        """Two different files are tracked independently."""
        file_a = tmp_path / "a.note"
        file_b = tmp_path / "b.note"
        file_a.write_bytes(b"content of a")
        file_b.write_bytes(b"content of b")

        cache = DedupCache(state_dir)
        cache.mark_processed(file_a)

        assert cache.already_processed(file_a) is True
        assert cache.already_processed(file_b) is False
