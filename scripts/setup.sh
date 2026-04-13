#!/usr/bin/env bash
# =============================================================================
# setup.sh — Bootstrap supernote-to-obsidian on macOS or Linux
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== supernote-to-obsidian setup ==="
echo "Repository: ${REPO_ROOT}"
echo ""

# ---------------------------------------------------------------------------
# 1. Detect OS and install system dependencies
# ---------------------------------------------------------------------------
OS="$(uname -s)"

if [[ "${OS}" == "Darwin" ]]; then
    echo "[1/5] macOS detected — installing dependencies via Homebrew …"
    if ! command -v brew &>/dev/null; then
        echo "ERROR: Homebrew is required on macOS. Install it from https://brew.sh/" >&2
        exit 1
    fi
    brew install tesseract poppler
elif [[ "${OS}" == "Linux" ]]; then
    echo "[1/5] Linux detected — installing dependencies via apt-get …"
    sudo apt-get update -qq
    sudo apt-get install -y tesseract-ocr poppler-utils
else
    echo "WARNING: Unknown OS '${OS}'. Skipping system dependency installation." >&2
fi

# ---------------------------------------------------------------------------
# 2. Create Python virtual environment
# ---------------------------------------------------------------------------
echo ""
echo "[2/5] Creating Python virtual environment …"
cd "${REPO_ROOT}"

if [[ -d ".venv" ]]; then
    echo "  .venv already exists — skipping creation."
else
    python3 -m venv .venv
    echo "  Created .venv"
fi

# ---------------------------------------------------------------------------
# 3. Install the package and dev dependencies
# ---------------------------------------------------------------------------
echo ""
echo "[3/5] Installing supernote-to-obsidian[dev] …"
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -e ".[dev]"

# ---------------------------------------------------------------------------
# 4. Copy example config if needed
# ---------------------------------------------------------------------------
echo ""
echo "[4/5] Checking configuration …"
if [[ ! -f "${REPO_ROOT}/config.yaml" ]]; then
    cp "${REPO_ROOT}/config.yaml.example" "${REPO_ROOT}/config.yaml"
    echo "  Copied config.yaml.example → config.yaml"
    echo "  Edit config.yaml and fill in your vault_path and device settings."
else
    echo "  config.yaml already exists — skipping copy."
fi

# ---------------------------------------------------------------------------
# 5. Create required directories
# ---------------------------------------------------------------------------
echo ""
echo "[5/5] Creating state and log directories …"
mkdir -p ~/.supernote-sync/logs
echo "  Created ~/.supernote-sync/logs"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit ${REPO_ROOT}/config.yaml with your Supernote and Obsidian settings."
echo "  2. Activate the virtual environment:  source ${REPO_ROOT}/.venv/bin/activate"
echo "  3. Run a one-time sync:               supernote-sync --config config.yaml once"
echo "  4. Start the file watcher:            supernote-sync --config config.yaml watch"
echo ""
echo "To run as a background service:"
echo "  macOS:  scripts/com.supernote-sync.plist  (launchd)"
echo "  Linux:  scripts/supernote-sync.service    (systemd)"
