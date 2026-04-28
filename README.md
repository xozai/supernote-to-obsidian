# supernote-to-obsidian

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

`supernote-to-obsidian` is a Python CLI tool that converts handwritten `.note` files from a
Supernote Manta tablet into searchable Markdown notes inside an Obsidian vault. Each page is
rasterised, run through OCR (Tesseract or Google Cloud Vision), and written as a `.md` file
with YAML frontmatter and embedded page images. The tool can watch a local folder for new
files, pull directly from the device over Wi-Fi, and optionally commit the vault to git after
every conversion.

---

## Architecture

### Data flow

```text
                       ┌─────────────┐
  Supernote device ───►│ WiFiPuller  │ (optional, requires wifi.enabled=true)
                       └──────┬──────┘
                              │ .note files
                    local sync_folder
                              │
                       ┌──────▼──────┐
                       │ DedupCache  │◄─── skip if MD5 already seen
                       └──────┬──────┘
                              │
                       ┌──────▼──────┐
                       │ NoteParser  │  .note → list[NotePage]
                       └──────┬──────┘
                              │ list[NotePage]
                       ┌──────▼──────┐
                       │  OcrEngine  │  NotePage → OcrResult
                       │  (per page) │  (preprocessed before Tesseract)
                       └──────┬──────┘
                              │ list[OcrResult]
                       ┌──────▼──────────┐
                       │ MarkdownBuilder │  pages + results → NoteDocument
                       └──────┬──────────┘
                              │ NoteDocument
                       ┌──────▼──────┐
                       │ VaultWriter │  writes .md + PNGs; optional git push
                       └──────┬──────┘
                              │
                       Obsidian vault
```

On any unhandled error the Pipeline catches the exception, writes a `<stem>_FAILED.md` stub,
and continues with the next file.

### Component table

| Module               | File                            | Responsibility                                            |
|----------------------|---------------------------------|-----------------------------------------------------------|
| `NoteParser`         | `ingestion/note_parser.py`      | Load `.note` file, rasterise each page to a PIL image     |
| `WiFiPuller`         | `ingestion/wifi_puller.py`      | Recursively download `.note` files over the device HTTP   |
| `TesseractEngine`    | `ocr/tesseract_engine.py`       | Local OCR via pytesseract; includes image preprocessing   |
| `GoogleVisionEngine` | `ocr/google_vision_engine.py`   | Cloud OCR via Google Cloud Vision document_text_detection |
| `MarkdownBuilder`    | `formatter/markdown_builder.py` | Assemble frontmatter, OCR text, and image embeds          |
| `VaultWriter`        | `vault/writer.py`               | Write `.md` and attachment PNGs; optionally git push      |
| `DedupCache`         | `utils/dedup.py`                | MD5-based cache to skip already-processed files           |
| `Pipeline`           | `pipeline.py`                   | Orchestrate all stages; owns the watchdog file watcher    |
| `CLI`                | `cli.py`                        | Click entry point: init/once/watch/pull/schedule/status   |

### OCR engines

Use **Tesseract** for a fully local, free setup — no network access, no credentials required.
Before passing a page to Tesseract, the image is preprocessed: converted to grayscale,
contrast-enhanced (2x), sharpened, then binarized at a pixel threshold of 180. This improves
recognition accuracy on the light grey ink typical of Supernote screens.

Use **Google Vision** when handwriting quality is poor or when you need higher accuracy on
non-Latin scripts. It requires a Google Cloud service-account JSON key and incurs per-page API
costs. Both engines flag pages whose average word confidence falls below
`ocr.low_confidence_threshold` (default `0.70`) with an `<!-- OCR_LOW_CONFIDENCE -->` comment.

### Output format

**Converted note** — `<notes_subfolder>/<date>_<stem>.md`:

```markdown
---
title: MySketch
date: 2024-06-15
created: 2024-06-15T10:30:00+00:00
source: supernote
original_file: /home/user/supernote-sync/MySketch.note
tags:
  - supernote
  - handwritten
device: Supernote Manta
---

Hello world this is handwritten text

![[MySketch_page000.png]]

<!-- OCR_LOW_CONFIDENCE -->
hard to read scrawl

![[MySketch_page001.png]]
```

`title` is derived from the `.note` filename stem. `date` is the file's modification date (when
the note was last exported from the device), not the processing timestamp. Consecutive identical
OCR lines are collapsed automatically to reduce noise from repeated handwriting artefacts.

**Page images** — `<attachments_subfolder>/<stem>_page000.png`, one PNG per page.

**Failure stub** — `<stem>_FAILED.md` (written when any stage raises an unhandled exception):

```markdown
---
status: failed
---

<!-- OCR_FAILED -->

OCR processing failed for `MySketch.note`.
```

---

## Installation

### System requirements

| Dependency   | Minimum version | Purpose |
|--------------|-----------------|---------|
| Python       | 3.11            | Runtime |
| Tesseract    | 4.x             | Local OCR engine |
| Poppler      | any recent      | PDF/image rendering via `pdf2image` |
| Git          | any             | Optional vault auto-commit |

---

### Step 1 — Clone the repository

```bash
git clone https://github.com/your-user/supernote-to-obsidian.git
cd supernote-to-obsidian
```

---

### Step 2 — Install system dependencies

**macOS** (Homebrew required — install from [brew.sh](https://brew.sh) if needed):

```bash
brew install tesseract poppler
```

**Linux (Debian/Ubuntu):**

```bash
sudo apt-get update
sudo apt-get install -y tesseract-ocr poppler-utils
```

Verify Tesseract is on PATH:

```bash
tesseract --version
# Expected: tesseract 4.x.x or 5.x.x
```

---

### Step 3 — Create the Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

### Step 4 — Install the package

```bash
pip install --upgrade pip
pip install -e ".[dev]"
```

The `[dev]` extra includes `pytest`, `ruff`, and `mypy`. For a production-only install omit it:

```bash
pip install -e "."
```

Verify the CLI installed correctly:

```bash
supernote-sync --help
# Should print: init, once, watch, pull, schedule, status commands
```

---

### Step 5 — Automated alternative

Steps 2–4 above are also handled by the setup script, which auto-detects macOS vs Linux:

```bash
bash scripts/setup.sh
```

---

### supernote-tool (optional)

`supernote-tool` is the library that reads the proprietary `.note` binary format and renders
each page as a PIL image. Without it, the parser falls back to a single blank white stub page
per file — useful for testing the pipeline but not for real notes. Install it with:

```bash
pip install -e ".[supernote]"
```

If the library is present but its API differs from what is expected, run the smoke-test script
against a real file to inspect the actual method names:

```bash
python scripts/test_real_device.py path/to/sample.note
```

---

## Configuration

### Step 6 — Generate config.yaml

The `init` command is the fastest way to create a working config:

```bash
supernote-sync init
```

It prompts for four values:

| Prompt | Example input | What it sets |
|--------|---------------|--------------|
| Obsidian vault path | `~/Documents/MyVault` | `obsidian.vault_path` |
| Local sync folder | `~/supernote-sync` | `supernote.sync_folder` |
| OCR engine | `tesseract` | `ocr.engine` |
| Supernote IP address | `192.168.1.100` or blank | `supernote.wifi.host` + `enabled` |

Or copy the annotated example manually and edit it:

```bash
cp config.yaml.example config.yaml
```

---

### Step 7 — Key configuration values

Open `config.yaml` and set at minimum:

```yaml
supernote:
  sync_folder: ~/supernote-sync      # where .note files land locally

obsidian:
  vault_path: ~/Documents/MyVault    # root of your Obsidian vault
```

**Wi-Fi pull** (to pull files directly from the device):

```yaml
supernote:
  wifi:
    enabled: true
    host: "192.168.1.100"            # device IP — find it in Supernote Settings > Wi-Fi
    port: 8089
    poll_interval_seconds: 60
```

**Google Cloud Vision** (higher accuracy, requires credentials):

```yaml
ocr:
  engine: "google_vision"
  google_vision:
    credentials_path: ~/secrets/google-vision-key.json
```

To get a key: Google Cloud Console → APIs & Services → Credentials → Create service account →
download JSON → enable the Cloud Vision API.

**Git auto-commit** (push vault after every note):

```yaml
obsidian:
  git_sync:
    enabled: true
    commit_message: "chore: supernote sync {timestamp}"
    remote: "origin"
    branch: "main"
```

Your vault must already be a git repo with a configured remote for this to work.

**Output filename pattern:**

```yaml
processing:
  output_filename_pattern: "%Y-%m-%d_{note_name}"
  # Produces: 2024-06-15_MySketch.md
```

`{note_name}` is replaced with the original `.note` filename stem. The pattern is a standard
Python `strftime` format string.

---

### Step 8 — Create required directories

The setup script handles this automatically. If you installed manually:

```bash
mkdir -p ~/.supernote-sync/logs
```

---

### Step 9 — First run

```bash
source .venv/bin/activate

# Preview what would be processed (no vault writes)
supernote-sync --config config.yaml once --dry-run

# Process all .note files in sync_folder once
supernote-sync --config config.yaml once

# Process only files modified in the last week
supernote-sync --config config.yaml once --since 2024-06-08

# Check what was processed (shows new / modified / processed states)
supernote-sync --config config.yaml status

# Start the live watcher (blocks until Ctrl-C)
supernote-sync --config config.yaml watch

# Or run on a recurring 1-hour schedule instead of a system service
supernote-sync --config config.yaml schedule --interval 3600
```

---

### Configuration reference

All settings live in `config.yaml`. See [`config.yaml.example`](config.yaml.example) for the
fully annotated template. The table below lists every top-level key:

| Section                | Key                                             | Description                                             |
|------------------------|-------------------------------------------------|---------------------------------------------------------|
| `supernote`            | `sync_folder`                                   | Local directory that holds `.note` files                |
| `supernote.wifi`       | `enabled`, `host`, `port`, `poll_interval_seconds` | Wi-Fi pull settings                                  |
| `ocr`                  | `engine`                                        | `"tesseract"` or `"google_vision"`                      |
| `ocr`                  | `low_confidence_threshold`                      | Pages below this confidence (0–1) get a warning comment |
| `ocr.tesseract`        | `binary_path`, `lang`                           | Tesseract binary location and language string           |
| `ocr.google_vision`    | `credentials_path`                              | Path to Google service-account JSON key file            |
| `obsidian`             | `vault_path`, `notes_subfolder`, `attachments_subfolder` | Vault layout                               |
| `obsidian.frontmatter` | `default_tags`, `extra_fields`                  | YAML frontmatter fields added to every note             |
| `obsidian.git_sync`    | `enabled`, `commit_message`, `remote`, `branch` | Auto commit and push after each sync                    |
| `processing`           | `deduplicate`, `state_dir`, `render_dpi`, `output_filename_pattern` | Processing options        |
| `logging`              | `level`, `log_dir`, `max_log_files`             | Log level and rotating file settings                    |

---

## CLI Reference

```text
supernote-sync [--config PATH] COMMAND [ARGS]...
```

**Commands:** `init` · `once` · `watch` · `pull` · `schedule` · `status`

**Global option:**

| Option          | Default       | Description                         |
|-----------------|---------------|-------------------------------------|
| `--config PATH` | `config.yaml` | Path to the YAML configuration file |

---

### `init`

```bash
supernote-sync init
```

Interactively create a `config.yaml` (or the path given via `--config`). Prompts for vault
path, sync folder, OCR engine, and device IP. Loads `config.yaml.example` as the template and
patches only the values you provide. If the target file already exists you are asked to confirm
before overwriting.

---

### `once`

```bash
supernote-sync --config config.yaml once [OPTIONS] [PATH]
```

Process `.note` files once and exit. `PATH` is optional:

- omitted — process all `*.note` files in `sync_folder`
- a directory — process all `*.note` files inside it
- a single `.note` file — process only that file

After every batch run a summary line is printed, e.g. `3 new, 1 modified, 12 skipped`.

**Options:**

| Option | Description |
|---|---|
| `--force` | Bypass the dedup cache and overwrite any existing vault note with the same stem instead of creating a new dated file |
| `--dry-run` | Print a table of what *would* be processed (name, size, mtime, status) without writing anything |
| `--since DATE` | Only include files whose mtime is on or after `DATE` (format: `YYYY-MM-DD`) |
| `--until DATE` | Only include files whose mtime is on or before `DATE` |
| `--tag TAG` | Only include files whose existing vault note already contains `TAG` in its frontmatter |

`--since`, `--until`, and `--tag` are combinable. `--dry-run` can be combined with any filter to preview results before committing.

---

### `watch`

```bash
supernote-sync --config config.yaml watch
```

Start a filesystem observer on `sync_folder` (recursive). Any `.note` file that is created or
moved into the folder is processed immediately. Blocks until Ctrl-C.

---

### `pull`

```bash
supernote-sync --config config.yaml pull [--watch]
```

Download `.note` files from the Supernote device's built-in HTTP server to `sync_folder`.
Requires `supernote.wifi.enabled: true` and a valid `host` in `config.yaml`. Pass `--watch`
to poll continuously at the interval set by `poll_interval_seconds`.

---

### `schedule`

```bash
supernote-sync --config config.yaml schedule [--interval SECONDS]
```

Run the full sync loop on a recurring timer using APScheduler. Executes an immediate first run
on startup, then repeats every `--interval` seconds (default `3600`). Useful as an alternative
to the systemd/launchd service when you want in-process scheduling without a separate daemon.

| Option | Default | Description |
|---|---|---|
| `--interval N` | `3600` | Seconds between each sync run |

Press Ctrl-C to stop.

---

### `status`

```bash
supernote-sync --config config.yaml status
```

Print a table of every `.note` file in `sync_folder` with its size, modification date, and
processing status. Three states are reported when deduplication is enabled:

| Status | Meaning |
|---|---|
| `processed` (green) | File was processed and its MD5 matches the stored hash — no action needed |
| `modified` (yellow) | File was processed before, but its content has changed since — re-export detected |
| `new` (blue) | File has never been processed |

Without deduplication, all files show as `pending`. Prints a summary line at the end,
e.g. `4 processed, 1 modified, 2 pending`.

---

## Running as a Background Service

Run `supernote-sync init` first to create your `config.yaml` before installing the service.

### macOS (launchd)

1. Replace all `YOUR_USER` placeholders in the plist with your macOS username:

```bash
sed -i '' "s/YOUR_USER/$(whoami)/g" scripts/com.supernote-sync.plist
```

2. Install and load the agent:

```bash
cp scripts/com.supernote-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.supernote-sync.plist
```

3. Confirm it is running (a non-zero PID in the first column means the process is active):

```bash
launchctl list | grep supernote
```

4. View logs:

```bash
tail -f ~/.supernote-sync/logs/supernote-sync.stdout.log
tail -f ~/.supernote-sync/logs/supernote-sync.stderr.log
```

5. To stop or unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.supernote-sync.plist
```

### Linux (systemd user unit)

1. Verify the `ExecStart` path in `scripts/supernote-sync.service` points to the
   `supernote-sync` binary inside your `.venv`. The `%u` placeholder expands to your username
   automatically.

2. Install and enable:

```bash
mkdir -p ~/.config/systemd/user
cp scripts/supernote-sync.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now supernote-sync
```

3. Check status and view logs:

```bash
systemctl --user status supernote-sync
journalctl --user -u supernote-sync -f
```

4. To stop:

```bash
systemctl --user stop supernote-sync
```

---

## Development

```bash
# Run tests with coverage
pytest tests/ -v --cov=supernote_sync

# Lint
ruff check supernote_sync tests

# Type check
mypy supernote_sync
```

The test suite uses `pytest-mock` to stub all external dependencies (pytesseract, Google Cloud
Vision, watchdog, git). Coverage must remain at or above 80%.

---

## License

This project is licensed under the [Apache License 2.0](LICENSE).

You are free to use, modify, and distribute this software — including in commercial products — provided you include the license and attribution notices. All bundled runtime dependencies (Google Cloud Vision SDK, watchdog, requests, Pillow, click, PyYAML, rich, APScheduler, python-frontmatter) carry Apache 2.0, BSD-3, or MIT licenses, which are fully compatible with Apache 2.0.

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)
