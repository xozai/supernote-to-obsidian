"""Write converted note documents to an Obsidian vault."""

from __future__ import annotations

import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class VaultWriter:
    """Write note documents (markdown + attachments) to an Obsidian vault.

    Optionally commits and pushes the vault via git after each write.

    Args:
        cfg: Top-level configuration dictionary.
    """

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Initialise the writer from configuration."""
        obs_cfg: dict[str, Any] = cfg.get("obsidian", {})
        self.vault_path = Path(obs_cfg.get("vault_path", "~/Documents/MyVault")).expanduser()
        self.attachments_folder = (
            self.vault_path / obs_cfg.get("attachments_subfolder", "Supernote/attachments")
        )
        git_cfg: dict[str, Any] = obs_cfg.get("git_sync", {})
        self.git_enabled: bool = bool(git_cfg.get("enabled", False))
        raw_message: str = git_cfg.get("commit_message", "chore: supernote sync {timestamp}")
        self.commit_message: str = raw_message
        self.git_remote: str = git_cfg.get("remote", "origin")
        self.git_branch: str = git_cfg.get("branch", "main")

    def write(self, document: Any) -> None:
        """Write *document* to the vault.

        Steps:
        1. Save all attachment files to :attr:`attachments_folder`.
        2. Write the rendered Markdown to :attr:`~.Document.output_path`.
        3. If ``git_sync.enabled``, run ``git add``, ``git commit``, and
           ``git push``.  Git errors are logged but never re-raised.

        Args:
            document: Any object satisfying the
                :class:`~supernote_sync.formatter.markdown_builder.Document`
                protocol.
        """
        # Write attachments
        self.attachments_folder.mkdir(parents=True, exist_ok=True)
        for filename, data in document.attachments:
            dest = self.attachments_folder / filename
            try:
                dest.write_bytes(data)
                logger.debug("Wrote attachment: %s", dest)
            except OSError as exc:
                logger.error("Failed to write attachment %s: %s", dest, exc)

        # Write markdown note
        output_path: Path = document.output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            output_path.write_text(document.render(), encoding="utf-8")
            logger.info("Wrote note: %s", output_path)
        except OSError as exc:
            logger.error("Failed to write note %s: %s", output_path, exc)
            raise

        # Optional git sync
        if self.git_enabled:
            self._git_sync()

    def _git_sync(self) -> None:
        """Stage, commit, and push all vault changes via git."""
        timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        message = self.commit_message.replace("{timestamp}", timestamp)
        vault_str = str(self.vault_path)

        commands: list[list[str]] = [
            ["git", "-C", vault_str, "add", "."],
            ["git", "-C", vault_str, "commit", "-m", message],
            ["git", "-C", vault_str, "push", self.git_remote, self.git_branch],
        ]

        for cmd in commands:
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                logger.debug("git command succeeded: %s", " ".join(cmd[2:]))
            except subprocess.CalledProcessError as exc:
                logger.error(
                    "git command failed (non-fatal): %s\nstdout: %s\nstderr: %s",
                    " ".join(cmd),
                    exc.stdout,
                    exc.stderr,
                )
