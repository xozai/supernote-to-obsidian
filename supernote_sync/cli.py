"""Command-line interface for supernote-to-obsidian."""

from __future__ import annotations

import logging
import sys
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
@click.pass_context
def once(ctx: click.Context, path: Path | None, force: bool) -> None:
    """Process .note files once (either a single file, or all in sync_folder).

    PATH  Optional path to a specific .note file or directory.  If omitted,
          all *.note files in the configured sync_folder are processed.

    Use --force to reprocess files that have already been converted, overwriting
    the existing note in the vault rather than creating a new dated copy.
    """
    cfg: dict[str, Any] = _load_cfg(ctx)
    from supernote_sync.pipeline import Pipeline  # noqa: PLC0415

    pipeline = Pipeline(cfg)

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

    if not note_files:
        console.print("[yellow]No .note files found.[/yellow]")
        return

    n = len(note_files)
    if force:
        console.print(f"Processing [bold]{n}[/bold] file(s) [yellow](force)[/yellow] …")
    else:
        console.print(f"Processing [bold]{n}[/bold] file(s) …")

    ok = 0
    fail = 0
    for nf in note_files:
        result = pipeline.process_file(nf, force=force)
        if result:
            ok += 1
            console.print(f"  [green]✓[/green] {nf.name}")
        else:
            fail += 1
            console.print(f"  [red]✗[/red] {nf.name}")

    console.print(f"\n[bold]Done:[/bold] {ok} succeeded, {fail} failed/skipped.")


@main.command()
@click.option(
    "--watch/--no-watch", "watch_mode", default=False, help="Poll continuously for new files."
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
                console.print(f"  Pulled {count} new file(s). Next check in {interval}s …")
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
    ocr_engine = click.prompt("OCR engine [tesseract/google_vision]", default="tesseract")
    wifi_host = click.prompt("Supernote IP address (leave blank to skip WiFi)", default="")

    if example_path.exists():
        cfg = load_config(example_path)
    else:
        cfg = {}

    # Patch values
    cfg.setdefault("supernote", {})["sync_folder"] = sync_folder
    cfg.setdefault("obsidian", {})["vault_path"] = vault_path
    cfg.setdefault("ocr", {})["engine"] = ocr_engine
    wifi_cfg = cfg["supernote"].setdefault("wifi", {})
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
    sync_folder = Path(cfg.get("supernote", {}).get("sync_folder", "~/supernote-sync")).expanduser()

    if not sync_folder.exists():
        console.print(f"[yellow]Sync folder does not exist:[/yellow] {sync_folder}")
        return

    note_files = sorted(sync_folder.glob("*.note"))

    dedup = None
    if proc_cfg.get("deduplicate", True):
        from supernote_sync.utils.dedup import DedupCache  # noqa: PLC0415
        state_dir = Path(proc_cfg.get("state_dir", "~/.supernote-sync")).expanduser()
        dedup = DedupCache(state_dir=state_dir)

    table = Table(show_header=True, header_style="bold")
    table.add_column("File")
    table.add_column("Size")
    table.add_column("Status")

    n_processed = 0
    n_pending = 0
    for nf in note_files:
        size_kb = nf.stat().st_size // 1024
        processed = dedup is not None and dedup.already_processed(nf)
        if processed:
            n_processed += 1
            status_str = "[green]processed[/green]"
        else:
            n_pending += 1
            status_str = "[yellow]pending[/yellow]"
        table.add_row(nf.name, f"{size_kb} KB", status_str)

    if note_files:
        console.print(table)
    console.print(f"\n{n_processed} processed, {n_pending} pending")
