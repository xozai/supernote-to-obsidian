"""Pipeline orchestrator: ties together ingestion, OCR, formatting and vault writing."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from supernote_sync.formatter.markdown_builder import FailureDocument, MarkdownBuilder
from supernote_sync.ingestion.note_parser import NoteParser
from supernote_sync.ocr.engine_factory import build_engine
from supernote_sync.vault.writer import VaultWriter

logger = logging.getLogger(__name__)


class Pipeline:
    """Orchestrate the full note-conversion pipeline.

    Args:
        cfg: Top-level configuration dictionary.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Initialise all pipeline components from *cfg*."""
        self.cfg = cfg
        proc_cfg: dict[str, Any] = cfg.get("processing", {})
        obs_cfg: dict[str, Any] = cfg.get("obsidian", {})

        self.sync_folder = Path(
            cfg.get("supernote", {}).get("sync_folder", "~/supernote-sync")
        ).expanduser()
        vault_path = Path(obs_cfg.get("vault_path", "~/Documents/MyVault")).expanduser()
        notes_subfolder = obs_cfg.get("notes_subfolder", "Supernote")
        notes_dir = vault_path / notes_subfolder

        dpi: int = int(proc_cfg.get("render_dpi", 200))
        self.parser = NoteParser(dpi=dpi)
        self.ocr = build_engine(cfg)
        self.builder = MarkdownBuilder(cfg=cfg, notes_dir=notes_dir)
        self.writer = VaultWriter(cfg=cfg)

        self._dedup_enabled: bool = bool(proc_cfg.get("deduplicate", True))
        self._dedup: Any = None
        if self._dedup_enabled:
            from supernote_sync.utils.dedup import DedupCache  # noqa: PLC0415

            state_dir = Path(proc_cfg.get("state_dir", "~/.supernote-sync")).expanduser()
            self._dedup = DedupCache(state_dir=state_dir)

    def process_file(self, note_path: Path) -> bool:
        """Convert a single ``.note`` file and write it to the vault.

        Steps:
        1. Dedup check — skip if already processed.
        2. Extract pages via :class:`~supernote_sync.ingestion.note_parser.NoteParser`.
        3. Run OCR on each page.
        4. Build the :class:`~supernote_sync.formatter.markdown_builder.NoteDocument`.
        5. Write the document to the vault.
        6. Mark the file as processed in the dedup cache.

        On any unhandled exception the method catches the error, writes a
        :class:`~supernote_sync.formatter.markdown_builder.FailureDocument`,
        and returns ``False``.

        Args:
            note_path: Path to the ``.note`` file to process.

        Returns:
            ``True`` on success, ``False`` if skipped or on failure.
        """
        logger.info("Processing %s", note_path)

        # Deduplication check
        if self._dedup_enabled and self._dedup is not None:
            if self._dedup.already_processed(note_path):
                logger.info("Skipping already-processed file: %s", note_path.name)
                return False

        try:
            pages = self.parser.extract_pages(note_path)
            ocr_results = [self.ocr.run(page) for page in pages]

            # Filter blank pages
            non_blank = [(p, r) for p, r in zip(pages, ocr_results) if not self._is_blank_page(p)]

            if not non_blank and pages:
                logger.warning("All pages in %s are blank — writing failure stub", note_path.name)
                self._write_failure_stub(note_path)
                return False

            filtered_pages = [p for p, r in non_blank]
            filtered_results = [r for p, r in non_blank]

            document = self.builder.build(note_path, filtered_pages, filtered_results)
            self.writer.write(document)

            if self._dedup_enabled and self._dedup is not None:
                self._dedup.mark_processed(note_path)

            logger.info("Successfully processed %s", note_path.name)
            return True

        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to process %s: %s", note_path, exc)
            self._write_failure_stub(note_path)
            return False

    def _is_blank_page(self, page: Any, threshold: float = 0.99) -> bool:
        """Return True if the page image is nearly all white.

        Args:
            page: The page to check.
            threshold: Fraction of near-white pixels (>= 250) that qualifies as blank.
        Returns:
            True if blank, False otherwise.
        """
        gray = page.image.convert("L")
        pixels = list(gray.getdata())
        white_fraction = sum(1 for p in pixels if p >= 250) / len(pixels)
        return white_fraction >= threshold

    def _write_failure_stub(self, note_path: Path) -> None:
        """Write a :class:`~supernote_sync.formatter.markdown_builder.FailureDocument`.

        Args:
            note_path: Path to the file that failed processing.
        """
        try:
            failure_doc = FailureDocument(source_path=note_path)
            self.writer.write(failure_doc)
            logger.info("Wrote failure stub for %s", note_path.name)
        except Exception as stub_exc:  # noqa: BLE001
            logger.error("Could not write failure stub for %s: %s", note_path, stub_exc)

    def watch(self) -> None:
        """Watch :attr:`sync_folder` for new ``.note`` files and process them.

        Uses :mod:`watchdog` to observe filesystem events.  Processes files
        on ``created`` and ``moved`` events whose paths end in ``".note"``.

        Blocks until :exc:`KeyboardInterrupt` is raised.
        """
        from watchdog.events import FileSystemEvent, FileSystemEventHandler  # type: ignore[import]
        from watchdog.observers import Observer  # type: ignore[import]

        self.sync_folder.mkdir(parents=True, exist_ok=True)
        logger.info("Watching %s for new .note files …", self.sync_folder)

        pipeline = self

        class _Handler(FileSystemEventHandler):
            def _handle(self, path_str: str) -> None:
                if path_str.lower().endswith(".note"):
                    pipeline.process_file(Path(path_str))

            def on_created(self, event: FileSystemEvent) -> None:
                self._handle(str(event.src_path))

            def on_moved(self, event: FileSystemEvent) -> None:
                self._handle(str(event.dest_path))

        observer: Any = Observer()
        observer.schedule(_Handler(), str(self.sync_folder), recursive=True)
        observer.start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Stopping file watcher …")
        finally:
            observer.stop()
            observer.join()
