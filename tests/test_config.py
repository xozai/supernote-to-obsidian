"""Tests for config.py."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from supernote_sync.config import load_config


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Write a minimal YAML config and return its path."""
    cfg = {
        "supernote": {
            "sync_folder": "~/supernote-sync",
            "wifi": {"enabled": False, "host": "192.168.1.100", "port": 8089},
        },
        "ocr": {"engine": "tesseract", "low_confidence_threshold": 0.70},
        "obsidian": {
            "vault_path": "~/Documents/Vault",
            "notes_subfolder": "Notes",
        },
        "logging": {"level": "INFO", "log_dir": "~/.supernote-sync/logs", "max_log_files": 7},
    }
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(cfg), encoding="utf-8")
    return p


class TestLoadConfig:
    """Tests for load_config()."""

    def test_returns_dict(self, config_file: Path) -> None:
        """load_config returns a dict."""
        result = load_config(config_file)
        assert isinstance(result, dict)

    def test_expands_tilde_in_values(self, config_file: Path) -> None:
        """Tilde-prefixed string values are expanded."""
        result = load_config(config_file)
        sync_folder = result["supernote"]["sync_folder"]
        assert not sync_folder.startswith("~")
        assert "/" in sync_folder

    def test_expands_tilde_in_nested_values(self, config_file: Path) -> None:
        """Tilde in nested string values is expanded."""
        result = load_config(config_file)
        log_dir = result["logging"]["log_dir"]
        assert not log_dir.startswith("~")

    def test_non_tilde_strings_unchanged(self, config_file: Path) -> None:
        """Strings without ~ are not modified."""
        result = load_config(config_file)
        assert result["ocr"]["engine"] == "tesseract"

    def test_raises_file_not_found(self, tmp_path: Path) -> None:
        """load_config raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_loads_all_sections(self, config_file: Path) -> None:
        """load_config loads all top-level sections."""
        result = load_config(config_file)
        assert "supernote" in result
        assert "ocr" in result
        assert "obsidian" in result
        assert "logging" in result

    def test_empty_yaml_returns_empty_dict(self, tmp_path: Path) -> None:
        """An empty YAML file returns an empty dict."""
        p = tmp_path / "empty.yaml"
        p.write_text("", encoding="utf-8")
        result = load_config(p)
        assert result == {}

    def test_list_values_preserved(self, tmp_path: Path) -> None:
        """List values (e.g. default_tags) are preserved."""
        cfg = {"obsidian": {"frontmatter": {"default_tags": ["a", "b"]}}}
        p = tmp_path / "cfg.yaml"
        p.write_text(yaml.dump(cfg), encoding="utf-8")
        result = load_config(p)
        assert result["obsidian"]["frontmatter"]["default_tags"] == ["a", "b"]
