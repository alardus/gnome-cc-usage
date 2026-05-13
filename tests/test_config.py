"""Tests for config.py — covers load, round-trip, and malformed TOML."""
import tomllib
from pathlib import Path

import pytest

from cc_usage.config import Config, PollConfig, UiConfig


class TestConfigLoadDefaults:
    def test_creates_file_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = Config.load()
        config_file = tmp_path / "cc-usage" / "config.toml"
        assert config_file.exists()

    def test_default_values(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = Config.load()
        assert cfg.poll.interval_seconds == 300
        assert cfg.poll.jitter_seconds == 30
        assert cfg.poll.backoff_max_seconds == 1800
        assert cfg.ui.show_label == "max"
        assert cfg.ui.warn_threshold == 75
        assert cfg.ui.crit_threshold == 90


class TestConfigRoundTrip:
    def test_save_and_reload(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = Config.load()
        cfg.poll.interval_seconds = 120
        cfg.ui.show_label = "five_hour"
        cfg.save()

        cfg2 = Config.load()
        assert cfg2.poll.interval_seconds == 120
        assert cfg2.ui.show_label == "five_hour"

    def test_saved_file_is_valid_toml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = Config.load()
        cfg.save()
        config_file = tmp_path / "cc-usage" / "config.toml"
        data = tomllib.loads(config_file.read_text())
        assert "poll" in data
        assert "ui" in data


class TestConfigMalformed:
    def test_malformed_toml_raises(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        config_dir = tmp_path / "cc-usage"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text("this is not valid toml ][")
        with pytest.raises(Exception):
            Config.load()

    def test_partial_config_uses_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        config_dir = tmp_path / "cc-usage"
        config_dir.mkdir()
        (config_dir / "config.toml").write_text("[poll]\ninterval_seconds = 60\n")
        cfg = Config.load()
        assert cfg.poll.interval_seconds == 60
        assert cfg.ui.warn_threshold == 75  # default


class TestAutostartEnabled:
    def test_default_autostart_disabled(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = Config.load()
        assert cfg.ui.autostart_enabled is False

    def test_autostart_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = Config.load()
        cfg.ui.autostart_enabled = True
        cfg.save()
        cfg2 = Config.load()
        assert cfg2.ui.autostart_enabled is True

    def test_autostart_false_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        cfg = Config.load()
        cfg.ui.autostart_enabled = False
        cfg.save()
        cfg2 = Config.load()
        assert cfg2.ui.autostart_enabled is False
