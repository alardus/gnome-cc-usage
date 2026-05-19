from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_TOML = """\
[poll]
interval_seconds = 300
jitter_seconds = 30
backoff_max_seconds = 1800

[ui]
show_label = "max"
warn_threshold = 75
crit_threshold = 90
"""


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "cc-usage"


@dataclass
class PollConfig:
    interval_seconds: int = 300
    jitter_seconds: int = 30
    backoff_max_seconds: int = 1800


@dataclass
class UiConfig:
    show_label: str = "max"
    warn_threshold: int = 75
    crit_threshold: int = 90
    autostart_enabled: bool = False
    show_time_remaining: bool = False


@dataclass
class Config:
    poll: PollConfig = field(default_factory=PollConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    _path: Path = field(default_factory=lambda: _config_dir() / "config.toml", repr=False)

    @classmethod
    def load(cls) -> "Config":
        path = _config_dir() / "config.toml"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_DEFAULT_TOML)
            return cls()

        data = tomllib.loads(path.read_text())
        poll_raw = data.get("poll", {})
        ui_raw = data.get("ui", {})
        cfg = cls(
            poll=PollConfig(
                interval_seconds=int(poll_raw.get("interval_seconds", 300)),
                jitter_seconds=int(poll_raw.get("jitter_seconds", 30)),
                backoff_max_seconds=int(poll_raw.get("backoff_max_seconds", 1800)),
            ),
            ui=UiConfig(
                show_label=str(ui_raw.get("show_label", "max")),
                warn_threshold=int(ui_raw.get("warn_threshold", 75)),
                crit_threshold=int(ui_raw.get("crit_threshold", 90)),
                autostart_enabled=bool(ui_raw.get("autostart_enabled", False)),
                show_time_remaining=bool(ui_raw.get("show_time_remaining", False)),
            ),
        )
        cfg._path = path
        return cfg

    def save(self) -> None:
        autostart_str = "true" if self.ui.autostart_enabled else "false"
        time_remaining_str = "true" if self.ui.show_time_remaining else "false"
        toml = (
            "[poll]\n"
            f"interval_seconds = {self.poll.interval_seconds}\n"
            f"jitter_seconds = {self.poll.jitter_seconds}\n"
            f"backoff_max_seconds = {self.poll.backoff_max_seconds}\n"
            "\n"
            "[ui]\n"
            f'show_label = "{self.ui.show_label}"\n'
            f"warn_threshold = {self.ui.warn_threshold}\n"
            f"crit_threshold = {self.ui.crit_threshold}\n"
            f"autostart_enabled = {autostart_str}\n"
            f"show_time_remaining = {time_remaining_str}\n"
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(toml)
