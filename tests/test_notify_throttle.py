"""Tests for ui/notify.py — dedup throttle, state persistence, and pruning.

libnotify (gi.repository.Notify) is mocked throughout so no D-Bus session
or display is required.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Mock gi / Notify before importing the module under test.
# ---------------------------------------------------------------------------

_gi_mock = MagicMock()
_notify_mock = MagicMock()

# We'll patch _try_init_notify to inject our mock and set _notify_ok=True.
# This is simpler than threading through gi.require_version mocks.


def _make_notifier(state_path: Path, notify_mod=None):
    """Create a Notifier with the given state_path and an injected Notify mock."""
    import cc_usage.ui.notify as notify_module

    # Reset module-level state.
    notify_module._notify_ok = False
    notify_module._notify_warned = False
    notify_module._notify_mod = None

    if notify_mod is not None:
        notify_module._notify_mod = notify_mod
        notify_module._notify_ok = True

    return notify_module.Notifier(state_path=state_path)


_NOW = datetime.now(tz=timezone.utc)
# Resets in the future (within the current reset window).
_RESETS_FUTURE = _NOW + timedelta(days=1)
# Resets in the past (expired window).
_RESETS_PAST = _NOW - timedelta(days=2)
# A different future reset window.
_RESETS_FUTURE_2 = _NOW + timedelta(days=2)


@pytest.fixture()
def notify_mod():
    """A fresh MagicMock for gi.repository.Notify."""
    mod = MagicMock()
    notif_instance = MagicMock()
    mod.Notification.new.return_value = notif_instance
    return mod


@pytest.fixture()
def state_file(tmp_path):
    return tmp_path / "notified.json"


class TestFirstCall:
    def test_first_call_fires_notification(self, state_file, notify_mod):
        n = _make_notifier(state_file, notify_mod)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)
        notify_mod.Notification.new.assert_called_once()
        notify_mod.Notification.new.return_value.show.assert_called_once()

    def test_notification_body_contains_bucket_and_util(self, state_file, notify_mod):
        n = _make_notifier(state_file, notify_mod)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)
        args = notify_mod.Notification.new.call_args
        body = args[0][1]  # second positional arg is the body
        assert "5h" in body
        assert "78" in body
        assert "warn" in body

    def test_notification_uses_warn_icon(self, state_file, notify_mod):
        n = _make_notifier(state_file, notify_mod)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)
        icon_arg = notify_mod.Notification.new.call_args[0][2]
        assert "warn" in icon_arg

    def test_notification_uses_crit_icon(self, state_file, notify_mod):
        n = _make_notifier(state_file, notify_mod)
        n.notify_threshold_cross("5h", "crit", 95.0, _RESETS_FUTURE)
        icon_arg = notify_mod.Notification.new.call_args[0][2]
        assert "crit" in icon_arg


class TestDedup:
    def test_second_call_same_key_does_not_show(self, state_file, notify_mod):
        n = _make_notifier(state_file, notify_mod)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)
        n.notify_threshold_cross("5h", "warn", 80.0, _RESETS_FUTURE)
        # show() must have been called exactly once despite two calls.
        assert notify_mod.Notification.new.return_value.show.call_count == 1

    def test_different_bucket_fires_again(self, state_file, notify_mod):
        n = _make_notifier(state_file, notify_mod)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)
        n.notify_threshold_cross("7d", "warn", 78.0, _RESETS_FUTURE)
        assert notify_mod.Notification.new.return_value.show.call_count == 2

    def test_different_level_fires_again(self, state_file, notify_mod):
        n = _make_notifier(state_file, notify_mod)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)
        n.notify_threshold_cross("5h", "crit", 92.0, _RESETS_FUTURE)
        assert notify_mod.Notification.new.return_value.show.call_count == 2

    def test_different_resets_at_fires_again(self, state_file, notify_mod):
        """After the window resets, a new notification should fire."""
        n = _make_notifier(state_file, notify_mod)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE_2)
        assert notify_mod.Notification.new.return_value.show.call_count == 2


class TestStatePersistence:
    def test_state_written_to_file(self, state_file, notify_mod):
        n = _make_notifier(state_file, notify_mod)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)
        assert state_file.exists()
        data = json.loads(state_file.read_text())
        assert any("5h|warn" in k for k in data)

    def test_second_instance_deduplicates_from_file(self, state_file, notify_mod):
        """A fresh Notifier instance should read the state file and not re-fire."""
        n1 = _make_notifier(state_file, notify_mod)
        n1.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)

        # Create a brand-new Notifier — simulates restart.
        n2 = _make_notifier(state_file, notify_mod)
        n2.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)

        # show() should still have been called only once total.
        assert notify_mod.Notification.new.return_value.show.call_count == 1


class TestPruning:
    def test_stale_entries_pruned_on_next_write(self, state_file, notify_mod):
        """Entries with resets_at in the past should be dropped on the next write."""
        # Pre-seed the state file with a stale entry.
        stale_key = f"5h|warn|{_RESETS_PAST.isoformat()}"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({stale_key: "2026-05-07T00:00:00+00:00"}))

        n = _make_notifier(state_file, notify_mod)
        # Trigger a write by sending a new notification (different key).
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)

        data = json.loads(state_file.read_text())
        # Stale key should be gone.
        assert stale_key not in data
        # Fresh key should be present.
        fresh_key = f"5h|warn|{_RESETS_FUTURE.isoformat()}"
        assert fresh_key in data

    def test_only_stale_entries_pruned(self, state_file, notify_mod):
        """Fresh entries must survive pruning."""
        fresh_key = f"7d|crit|{_RESETS_FUTURE.isoformat()}"
        stale_key = f"5h|warn|{_RESETS_PAST.isoformat()}"
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({
            fresh_key: "2026-05-08T10:00:00+00:00",
            stale_key: "2026-05-07T00:00:00+00:00",
        }))

        n = _make_notifier(state_file, notify_mod)
        # Writing any new entry triggers pruning.
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)

        data = json.loads(state_file.read_text())
        assert fresh_key in data
        assert stale_key not in data


class TestGracefulDegradation:
    def test_notify_unavailable_does_not_crash(self, state_file):
        """When libnotify is not available, notify_threshold_cross must not raise."""
        import cc_usage.ui.notify as notify_module
        notify_module._notify_ok = False
        notify_module._notify_warned = True   # suppress re-attempt
        notify_module._notify_mod = None

        n = notify_module.Notifier(state_path=state_file)
        # Should complete without raising.
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)

    def test_state_file_still_written_when_notify_unavailable(self, state_file):
        """Even without libnotify we still write state (to prevent re-firing on next start)."""
        import cc_usage.ui.notify as notify_module
        notify_module._notify_ok = False
        notify_module._notify_warned = True
        notify_module._notify_mod = None

        n = notify_module.Notifier(state_path=state_file)
        n.notify_threshold_cross("5h", "warn", 78.0, _RESETS_FUTURE)
        assert state_file.exists()
