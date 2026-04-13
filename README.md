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
| `CLI`                | `cli.py`                        | Click entry point exposing init/once/watch/pull/status    |

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

### Prerequisites

| Dependency   | macOS                           | Linux                           |
|--------------|---------------------------------|---------------------------------|
| Tesseract    | `brew install tesseract`        | `apt-get install tesseract-ocr` |
| Poppler      | `brew install poppler`          | `apt-get install poppler-utils` |
| Python 3.11+ | [python.org](https://www.python.org/downloads/) | system package or pyenv |

### Quick install

**Automated** (recommended) — installs system deps, creates `.venv`, copies config:

```bash
git clone https://github.com/your-user/supernote-to-obsidian.git
cd supernote-to-obsidian
bash scripts/setup.sh
```

**Manual:**

```bash
git clone https://github.com/your-user/supernote-to-obsidian.git
cd supernote-to-obsidian
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp config.yaml.example config.yaml
```

Then run the interactive setup wizard to generate your `config.yaml`:

```bash
supernote-sync init
```

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

All settings live in `config.yaml`. See [`config.yaml.example`](config.yaml.example) for the
fully annotated template. The table below lists every top-level key:

| Section                | Key                                   | Description                                             |
|------------------------|---------------------------------------|---------------------------------------------------------|
| `supernote`            | `sync_folder`                         | Local directory that holds `.note` files                |
| `supernote.wifi`       | `enabled`, `host`, `port`, `poll_interval_seconds` | Wi-Fi pull settings                      |
| `ocr`                  | `engine`                              | `"tesseract"` or `"google_vision"`                      |
| `ocr`                  | `low_confidence_threshold`            | Pages below this confidence (0–1) get a warning comment |
| `ocr.tesseract`        | `binary_path`, `lang`                 | Tesseract binary location and language string           |
| `ocr.google_vision`    | `credentials_path`                    | Path to Google service-account JSON key file            |
| `obsidian`             | `vault_path`, `notes_subfolder`, `attachments_subfolder` | Vault layout                       |
| `obsidian.frontmatter` | `default_tags`, `extra_fields`        | YAML frontmatter fields added to every note             |
| `obsidian.git_sync`    | `enabled`, `commit_message`, `remote`, `branch` | Auto commit and push after each sync          |
| `processing`           | `deduplicate`, `state_dir`, `render_dpi`, `output_filename_pattern` | Processing options  |
| `logging`              | `level`, `log_dir`, `max_log_files`   | Log level and rotating file settings                    |

**Minimal working config:**

```yaml
supernote:
  sync_folder: ~/supernote-sync

obsidian:
  vault_path: ~/Documents/MyVault
```

The `output_filename_pattern` key is a Python `strftime` string with one extra placeholder:
`{note_name}` is replaced with the original `.note` filename stem. For example,
`"%Y-%m-%d_{note_name}"` produces `2024-06-15_MySketch.md`.

---

## CLI Reference

```text
supernote-sync [--config PATH] COMMAND [ARGS]...
```

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
supernote-sync --config config.yaml once [PATH]
```

Process `.note` files once and exit. `PATH` is optional:

- omitted — process all `*.note` files in `sync_folder`
- a directory — process all `*.note` files inside it
- a single `.note` file — process only that file

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

### `status`

```bash
supernote-sync --config config.yaml status
```

Print a table of every `.note` file in `sync_folder` with its size and processing status
(`processed` or `pending`, based on the dedup cache). Prints a summary line at the end.

---

## Running as a Background Service

Run `supernote-sync init` first to create your `config.yaml` before installing the service.

### macOS (launchd)

1. Edit `scripts/com.supernote-sync.plist` and replace all `YOUR_USER` placeholders with your
   macOS username and the correct path to the `supernote-sync` binary in your `.venv`.
2. Install and load the agent:

```bash
cp scripts/com.supernote-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.supernote-sync.plist
```

3. Check status:

```bash
launchctl list | grep supernote
```

### Linux (systemd user unit)

1. Edit `scripts/supernote-sync.service` and verify the `ExecStart` path points to the
   `supernote-sync` binary inside your `.venv`.
2. Install and enable:

```bash
mkdir -p ~/.config/systemd/user
cp scripts/supernote-sync.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now supernote-sync
```

3. View logs:

```bash
journalctl --user -u supernote-sync -f
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
