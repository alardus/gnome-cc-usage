"""libnotify wrapper with per-bucket-per-reset-window deduplication.

Notifications are deduped by the key (bucket_name, level, resets_at ISO string).
State is persisted to XDG_STATE_HOME/cc-usage/notified.json so dedup
survives restarts within the same reset window.

Stale entries (resets_at in the past) are pruned on every write.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger("cc_usage")

# Lazy-load libnotify so the module can be imported without the
# GObject runtime present (e.g. in headless unit tests).
_notify_mod = None
_notify_ok = False
_notify_warned = False


def _state_dir() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "cc-usage"


def _default_state_path() -> Path:
    return _state_dir() / "notified.json"


def _try_init_notify() -> bool:
    """Attempt to import and initialise libnotify. Returns True on success."""
    global _notify_mod, _notify_ok, _notify_warned
    if _notify_ok:
        return True
    if _notify_warned:
        return False
    try:
        import gi
        gi.require_version("Notify", "0.7")
        from gi.repository import Notify
        if not Notify.init("cc-usage"):
            raise RuntimeError("Notify.init returned False")
        _notify_mod = Notify
        _notify_ok = True
        return True
    except Exception as exc:
        logger.warning("libnotify unavailable — notifications disabled: %s", exc)
        _notify_warned = True
        return False


class Notifier:
    """libnotify wrapper with per-bucket-per-reset-window dedup.

    Parameters
    ----------
    state_path:
        Path to the JSON file that persists which notifications have already
        been sent.  Defaults to XDG_STATE_HOME/cc-usage/notified.json.
        Override in tests to avoid touching the real filesystem.
    """

    def __init__(self, state_path: Path | None = None) -> None:
        self._state_path = state_path or _default_state_path()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def notify_threshold_cross(
        self,
        bucket_name: str,
        level: str,
        util: float,
        resets_at: datetime,
    ) -> None:
        """Fire a libnotify notification unless one was already sent for this
        exact (bucket, level, resets_at) combination during the current window.

        Parameters
        ----------
        bucket_name:
            Human-readable bucket label (e.g. ``"5h"``).
        level:
            ``"warn"`` or ``"crit"``.
        util:
            Current utilisation percentage (0..100).
        resets_at:
            When the bucket resets — used as the dedup key's time component.
        """
        resets_iso = resets_at.isoformat()
        key = f"{bucket_name}|{level}|{resets_iso}"

        state = self._load_state()
        if key in state:
            logger.debug("Notification already sent for key=%s — skipping", key)
            return

        # Record before attempting to show; avoids duplicate on show() error.
        state[key] = datetime.now(tz=timezone.utc).isoformat()
        self._save_state(state)

        if not _try_init_notify():
            return

        resets_local = resets_at.astimezone()
        resets_str = resets_local.strftime("%H:%M")
        body = f"{bucket_name}: {util:.0f}% ({level})\nResets at {resets_str}"
        icon = (
            "cc-usage-crit-symbolic"
            if level == "crit"
            else "cc-usage-warn-symbolic"
        )
        try:
            notif = _notify_mod.Notification.new("Claude Code Usage", body, icon)
            notif.show()
            logger.info("Notification sent: %s", key)
        except Exception as exc:
            logger.warning("Failed to show notification: %s", exc)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_state(self) -> dict[str, str]:
        if not self._state_path.exists():
            return {}
        try:
            return json.loads(self._state_path.read_text())
        except Exception as exc:
            logger.warning("Could not read notification state file: %s", exc)
            return {}

    def _save_state(self, state: dict[str, str]) -> None:
        now = datetime.now(tz=timezone.utc)
        # Prune entries whose resets_at is in the past.
        pruned: dict[str, str] = {}
        for key, seen_at in state.items():
            try:
                # key format: "bucket|level|resets_iso"
                resets_iso = key.rsplit("|", 1)[-1]
                resets_dt = datetime.fromisoformat(resets_iso)
                if resets_dt > now:
                    pruned[key] = seen_at
                # else: stale, drop it
            except Exception:
                # Malformed key — keep it to be safe (won't grow unboundedly).
                pruned[key] = seen_at

        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(pruned, indent=2))
        except Exception as exc:
            logger.warning("Could not write notification state file: %s", exc)
