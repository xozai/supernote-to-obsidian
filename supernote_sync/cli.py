"""Command-line interface for supernote-to-obsidian."""

from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from supernote_sync.config import load_config
from supernote_sync.utils.logging import setup_logging

console = Console()
logger = logging.getLogger(__name__)


def _load_cfg(ctx: click.Context) -> dict[str, Any]:
    """Load and return config from the path stored in ctx.obj.

    Args:
        ctx: Click context containing 'config_path' in obj.

    Returns:
        Parsed configuration dictionary.
    """
    config_path: Path = ctx.find_root().obj["config_path"]
    try:
        cfg: dict[str, Any] = load_config(config_path)
    except FileNotFoundError:
        console.print(f"[red]Config file not found:[/red] {config_path}")
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Failed to load config:[/red] {exc}")
        sys.exit(1)
    setup_logging(cfg)
    return cfg


def _parse_date_arg(value: str, param_name: str) -> date:
    """Parse a ``YYYY-MM-DD`` string into a :class:`datetime.date`.

    Args:
        value: The raw string value from the CLI.
        param_name: The option name, used in error messages.

    Returns:
        A :class:`datetime.date` instance.

    Raises:
        :exc:`click.BadParameter` when the format is invalid.
    """
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise click.BadParameter(
            f"Expected YYYY-MM-DD, got '{value}'",
            param_hint=f"'--{param_name}'",
        )


def _mtime_date(path: Path) -> date:
    """Return the UTC modification date of *path*."""
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).date()


def _vault_note_has_tag(note_path: Path, tag: str, notes_dir: Path) -> bool:
    """Return ``True`` if an existing vault note for *note_path* has *tag*.

    Scans *notes_dir* for Markdown files whose name contains the note stem,
    then checks their YAML frontmatter for the given tag.

    Args:
        note_path: The ``.note`` source file.
        tag: The tag string to look for.
        notes_dir: Directory in the vault where notes are stored.

    Returns:
        ``True`` when a matching vault note with the tag is found.
    """
    import frontmatter  # noqa: PLC0415

    stem = note_path.stem
    for md_path in notes_dir.glob(f"*{stem}*.md"):
        try:
            post = frontmatter.load(str(md_path))
            tags: Any = post.get("tags", [])
            if isinstance(tags, list) and tag in tags:
                return True
            if isinstance(tags, str) and tag == tags:
                return True
        except Exception:  # noqa: BLE001
            continue
    return False


@click.group()
@click.option(
    "--config",
    default="config.yaml",
    show_default=True,
    required=False,
    help="Path to the YAML configuration file.",
    type=click.Path(dir_okay=False, path_type=Path),
)
@click.pass_context
def main(ctx: click.Context, config: Path) -> None:
    """supernote-sync — sync Supernote handwritten notes to an Obsidian vault.

    Load configuration from CONFIG, set up logging, and store both in the
    Click context so sub-commands can access them.
    """
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config


@main.command()
@click.pass_context
def watch(ctx: click.Context) -> None:
    """Watch the sync folder and process new .note files automatically."""
    cfg: dict[str, Any] = _load_cfg(ctx)
    from supernote_sync.pipeline import Pipeline  # noqa: PLC0415

    pipeline = Pipeline(cfg)
    console.print("[green]Starting file watcher …[/green]  (Ctrl-C to stop)")
    pipeline.watch()


@main.command()
@click.argument("path", required=False, type=click.Path(path_type=Path))
@click.option(
    "--force",
    is_flag=True,
    default=False,
    help="Bypass the dedup cache and overwrite existing notes in the vault.",
)
@click.option(
    "--dry-run",
    "dry_run",
    is_flag=True,
    default=False,
    help="Print what would be processed without writing any files.",
)
@click.option(
    "--since",
    "since_date",
    default=None,
    metavar="DATE",
    help="Only include files modified on or after DATE (YYYY-MM-DD).",
)
@click.option(
    "--until",
    "until_date",
    default=None,
    metavar="DATE",
    help="Only include files modified on or before DATE (YYYY-MM-DD).",
)
@click.option(
    "--tag",
    "filter_tag",
    default=None,
    metavar="TAG",
    help="Only include files whose vault note already has TAG in frontmatter.",
)
@click.pass_context
def once(
    ctx: click.Context,
    path: Path | None,
    force: bool,
    dry_run: bool,
    since_date: str | None,
    until_date: str | None,
    filter_tag: str | None,
) -> None:
    """Process .note files once (a file, directory, or the configured sync_folder).

    PATH  Optional path to a specific .note file or directory.  If omitted,
          all *.note files in the configured sync_folder are processed.

    \b
    Filtering flags (combinable):
      --since / --until  narrow by file modification date
      --tag              narrow by existing vault-note frontmatter tag

    Use --force to reprocess files that have already been converted, overwriting
    the existing note in the vault rather than creating a new dated copy.

    Use --dry-run to preview what would run without touching the vault.
    """
    cfg: dict[str, Any] = _load_cfg(ctx)
    from supernote_sync.pipeline import Pipeline  # noqa: PLC0415

    pipeline = Pipeline(cfg)

    # ── Resolve note_files ──────────────────────────────────────────────────
    if path is not None:
        target = Path(path)
        if target.is_dir():
            note_files = sorted(target.glob("*.note"))
        elif target.suffix.lower() == ".note":
            note_files = [target]
        else:
            console.print(f"[yellow]Not a .note file or directory:[/yellow] {target}")
            return
    else:
        sync_folder = Path(
            cfg.get("supernote", {}).get("sync_folder", "~/supernote-sync")
        ).expanduser()
        note_files = sorted(sync_folder.glob("*.note"))

    # ── Date filters ─────────────────────────────────────────────────────────
    since_dt = _parse_date_arg(since_date, "since") if since_date else None
    until_dt = _parse_date_arg(until_date, "until") if until_date else None

    if since_dt or until_dt:
        filtered: list[Path] = []
        for nf in note_files:
            nd = _mtime_date(nf)
            if since_dt and nd < since_dt:
                continue
            if until_dt and nd > until_dt:
                continue
            filtered.append(nf)
        note_files = filtered

    # ── Tag filter ───────────────────────────────────────────────────────────
    if filter_tag:
        obs_cfg = cfg.get("obsidian", {})
        vault_path = Path(obs_cfg.get("vault_path", "~/Documents/MyVault")).expanduser()
        notes_dir = vault_path / obs_cfg.get("notes_subfolder", "Supernote")
        note_files = [
            nf for nf in note_files
            if _vault_note_has_tag(nf, filter_tag, notes_dir)
        ]

    if not note_files:
        console.print("[yellow]No .note files found.[/yellow]")
        return

    # ── Dry-run: print table and exit ────────────────────────────────────────
    if dry_run:
        from rich.table import Table  # noqa: PLC0415

        table = Table(show_header=True, header_style="bold")
        table.add_column("File")
        table.add_column("Size")
        table.add_column("Modified")
        table.add_column("Status")

        for nf in note_files:
            size_kb = nf.stat().st_size // 1024
            mtime = _mtime_date(nf).isoformat()
            if pipeline._dedup_enabled and pipeline._dedup is not None:
                if pipeline._dedup.already_processed(nf) and not force:
                    status_label = "[dim]already done[/dim]"
                elif pipeline._dedup.is_modified(nf):
                    status_label = "[yellow]modified[/yellow]"
                else:
                    status_label = "[green]new[/green]"
            else:
                status_label = "[green]pending[/green]"
            table.add_row(nf.name, f"{size_kb} KB", mtime, status_label)

        console.print(table)
        n = len(note_files)
        suffix = " [yellow](force)[/yellow]" if force else ""
        console.print(f"\n[bold]{n}[/bold] file(s) would be processed.{suffix}")
        return

    # ── Live run ─────────────────────────────────────────────────────────────
    n = len(note_files)
    suffix = " [yellow](force)[/yellow]" if force else ""
    console.print(f"Processing [bold]{n}[/bold] file(s){suffix} …")

    n_new = n_modified = n_skipped = n_failed = 0

    for nf in note_files:
        # Classify file before processing for the run summary.
        if pipeline._dedup_enabled and pipeline._dedup is not None:
            if pipeline._dedup.already_processed(nf):
                pre_status = "done"
            elif pipeline._dedup.is_modified(nf):
                pre_status = "modified"
            else:
                pre_status = "new"
        else:
            pre_status = "new"

        result = pipeline.process_file(nf, force=force)

        if result:
            if pre_status == "modified":
                n_modified += 1
            else:
                n_new += 1
            console.print(f"  [green]✓[/green] {nf.name}")
        elif pre_status == "done" and not force:
            n_skipped += 1
            console.print(f"  [dim]─[/dim] {nf.name}")
        else:
            n_failed += 1
            console.print(f"  [red]✗[/red] {nf.name}")

    # Run summary
    parts = []
    if n_new:
        parts.append(f"{n_new} new")
    if n_modified:
        parts.append(f"{n_modified} modified")
    if n_skipped:
        parts.append(f"{n_skipped} skipped")
    if n_failed:
        parts.append(f"[red]{n_failed} failed[/red]")
    summary = ", ".join(parts) if parts else "nothing to do"
    console.print(f"\n[bold]Done:[/bold] {summary}.")


@main.command()
@click.option(
    "--interval",
    default=3600,
    show_default=True,
    type=int,
    help="Seconds between each sync run.",
)
@click.pass_context
def schedule(ctx: click.Context, interval: int) -> None:
    """Process .note files on a recurring schedule using APScheduler.

    Runs immediately on start, then repeats every INTERVAL seconds.
    """
    from apscheduler.schedulers.blocking import BlockingScheduler  # noqa: PLC0415

    from supernote_sync.pipeline import Pipeline  # noqa: PLC0415

    cfg: dict[str, Any] = _load_cfg(ctx)
    pipeline = Pipeline(cfg)
    sync_folder = Path(
        cfg.get("supernote", {}).get("sync_folder", "~/supernote-sync")
    ).expanduser()

    def _run_sync() -> None:
        note_files = sorted(sync_folder.glob("*.note"))
        if not note_files:
            console.print("[yellow]No .note files found in sync folder.[/yellow]")
            return
        ok = fail = 0
        for nf in note_files:
            if pipeline.process_file(nf):
                ok += 1
            else:
                fail += 1
        console.print(f"[bold]Run complete:[/bold] {ok} succeeded, {fail} failed/skipped.")

    scheduler: Any = BlockingScheduler()
    scheduler.add_job(_run_sync, "interval", seconds=interval)
    console.print(
        f"[green]Scheduler started[/green] — running every {interval}s …"
        "  (Ctrl-C to stop)"
    )
    _run_sync()  # immediate first run
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        console.print("\nScheduler stopped.")


@main.command()
@click.option(
    "--watch/--no-watch",
    "watch_mode",
    default=False,
    help="Poll continuously for new files.",
)
@click.pass_context
def pull(ctx: click.Context, watch_mode: bool) -> None:
    """Pull .note files from the Supernote device over Wi-Fi."""
    cfg: dict[str, Any] = _load_cfg(ctx)
    wifi_cfg: dict[str, Any] = cfg.get("supernote", {}).get("wifi", {})

    if not wifi_cfg.get("enabled", False):
        console.print(
            "[yellow]Wi-Fi pull is disabled.[/yellow]  "
            "Set supernote.wifi.enabled=true in your config to enable it."
        )
        return

    from supernote_sync.ingestion.wifi_puller import WiFiPuller  # noqa: PLC0415

    host: str = wifi_cfg.get("host", "")
    port: int = int(wifi_cfg.get("port", 8089))
    dest_dir = Path(
        cfg.get("supernote", {}).get("sync_folder", "~/supernote-sync")
    ).expanduser()

    if not host:
        console.print("[red]supernote.wifi.host is not configured.[/red]")
        return

    console.print(f"Connecting to [bold]{host}:{port}[/bold] …")
    puller = WiFiPuller(host=host, port=port, dest_dir=dest_dir)

    if watch_mode:
        import time  # noqa: PLC0415

        interval = wifi_cfg.get("poll_interval_seconds", 60)
        try:
            while True:
                count = puller.pull()
                console.print(
                    f"  Pulled {count} new file(s). Next check in {interval}s …"
                )
                time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\nStopping pull loop.")
    else:
        count = puller.pull()
        console.print(f"[green]Downloaded {count} new file(s).[/green]")


@main.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Interactively create a config.yaml in the current directory."""
    import yaml  # noqa: PLC0415

    # Determine output path from --config option
    raw_config = ctx.find_root().params.get("config", "config.yaml")
    config_path = Path(raw_config) if raw_config else Path("config.yaml")

    if config_path.exists():
        console.print(f"[yellow]Config already exists:[/yellow] {config_path}")
        if not click.confirm("Overwrite?", default=False):
            console.print("Aborted.")
            return

    # Find config.yaml.example relative to this file
    example_path = Path(__file__).parent.parent / "config.yaml.example"

    vault_path = click.prompt("Obsidian vault path", default="~/Documents/MyVault")
    sync_folder = click.prompt("Local sync folder", default="~/supernote-sync")
    ocr_engine = click.prompt(
        "OCR engine [tesseract/google_vision]", default="tesseract"
    )
    wifi_host = click.prompt(
        "Supernote IP address (leave blank to skip WiFi)", default=""
    )

    if example_path.exists():
        cfg: dict[str, Any] = load_config(example_path)
    else:
        cfg = {}

    # Patch values
    cfg.setdefault("supernote", {})["sync_folder"] = sync_folder
    cfg.setdefault("obsidian", {})["vault_path"] = vault_path
    cfg.setdefault("ocr", {})["engine"] = ocr_engine
    wifi_cfg: dict[str, Any] = cfg["supernote"].setdefault("wifi", {})
    if wifi_host:
        wifi_cfg["host"] = wifi_host
        wifi_cfg["enabled"] = True
    else:
        wifi_cfg["enabled"] = False

    dumped = yaml.dump(cfg, default_flow_style=False, allow_unicode=True)
    config_path.write_text(dumped, encoding="utf-8")
    console.print(f"\n[green]Config written to[/green] {config_path}")
    console.print(f"[bold]Next step:[/bold] supernote-sync --config {config_path} once")


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show processing status of .note files in the sync folder."""
    from rich.table import Table  # noqa: PLC0415

    cfg = _load_cfg(ctx)
    proc_cfg = cfg.get("processing", {})
    sync_folder = Path(
        cfg.get("supernote", {}).get("sync_folder", "~/supernote-sync")
    ).expanduser()

    if not sync_folder.exists():
        console.print(f"[yellow]Sync folder does not exist:[/yellow] {sync_folder}")
        return

    note_files = sorted(sync_folder.glob("*.note"))

    dedup = None
    if proc_cfg.get("deduplicate", True):
        from supernote_sync.utils.dedup import DedupCache  # noqa: PLC0415

        state_dir = Path(
            proc_cfg.get("state_dir", "~/.supernote-sync")
        ).expanduser()
        dedup = DedupCache(state_dir=state_dir)

    table = Table(show_header=True, header_style="bold")
    table.add_column("File")
    table.add_column("Size")
    table.add_column("Modified")
    table.add_column("Status")

    n_processed = n_modified_count = n_pending = 0
    for nf in note_files:
        size_kb = nf.stat().st_size // 1024
        mtime = _mtime_date(nf).isoformat()
        if dedup is not None:
            if dedup.already_processed(nf):
                n_processed += 1
                status_str = "[green]processed[/green]"
            elif dedup.is_modified(nf):
                n_modified_count += 1
                status_str = "[yellow]modified[/yellow]"
            else:
                n_pending += 1
                status_str = "[blue]new[/blue]"
        else:
            n_pending += 1
            status_str = "[yellow]pending[/yellow]"
        table.add_row(nf.name, f"{size_kb} KB", mtime, status_str)

    if note_files:
        console.print(table)

    parts = [f"{n_processed} processed"]
    if n_modified_count:
        parts.append(f"{n_modified_count} modified")
    parts.append(f"{n_pending} pending")
    console.print(f"\n{', '.join(parts)}")
