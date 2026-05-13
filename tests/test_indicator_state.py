"""Tests for _icon_for() — the pure icon-selection helper in indicator.py.

No GTK is imported here.  _icon_for is a module-level function placed
*before* the GTK try/except in indicator.py, so importing it is safe in a
headless venv that has no gi/AyatanaAppIndicator3 installed.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# Inject lightweight gi stubs so the module-level GTK try/except in
# indicator.py does not propagate an ImportError into this test file.
# Even if the try/except fails, _icon_for is already defined above it.
_gi_stub = MagicMock()
_gi_stub.require_version = MagicMock()  # no-op
sys.modules.setdefault("gi", _gi_stub)
sys.modules.setdefault("gi.repository", MagicMock())

from datetime import datetime, timezone  # noqa: E402

from cc_usage.indicator import _icon_for, _format_until, _ICON_OK, _ICON_WARN, _ICON_CRIT  # noqa: E402


WARN = 75.0
CRIT = 90.0


class TestIconForOk:
    def test_zero_util_returns_ok(self):
        assert _icon_for(0.0, WARN, CRIT) == _ICON_OK

    def test_just_below_warn_returns_ok(self):
        assert _icon_for(WARN - 1, WARN, CRIT) == _ICON_OK

    def test_midrange_returns_ok(self):
        assert _icon_for(50.0, WARN, CRIT) == _ICON_OK

    def test_fractionally_below_warn_returns_ok(self):
        assert _icon_for(74.9, WARN, CRIT) == _ICON_OK


class TestIconForWarn:
    def test_at_warn_threshold_returns_warn(self):
        assert _icon_for(WARN, WARN, CRIT) == _ICON_WARN

    def test_above_warn_below_crit_returns_warn(self):
        assert _icon_for(WARN + 1, WARN, CRIT) == _ICON_WARN

    def test_just_below_crit_returns_warn(self):
        assert _icon_for(CRIT - 1, WARN, CRIT) == _ICON_WARN

    def test_fractionally_below_crit_returns_warn(self):
        assert _icon_for(89.9, WARN, CRIT) == _ICON_WARN


class TestIconForCrit:
    def test_at_crit_threshold_returns_crit(self):
        assert _icon_for(CRIT, WARN, CRIT) == _ICON_CRIT

    def test_above_crit_returns_crit(self):
        assert _icon_for(CRIT + 1, WARN, CRIT) == _ICON_CRIT

    def test_100_percent_returns_crit(self):
        assert _icon_for(100.0, WARN, CRIT) == _ICON_CRIT

    def test_over_100_returns_crit(self):
        # Defensive: util should never exceed 100, but must not crash.
        assert _icon_for(105.0, WARN, CRIT) == _ICON_CRIT


class TestIconForEdgeCases:
    def test_warn_equals_crit_threshold(self):
        # When warn==crit everything at or above the threshold is crit.
        assert _icon_for(90.0, 90.0, 90.0) == _ICON_CRIT
        assert _icon_for(89.9, 90.0, 90.0) == _ICON_OK

    def test_zero_thresholds(self):
        # Zero thresholds: everything ≥ 0 is crit.
        assert _icon_for(0.0, 0.0, 0.0) == _ICON_CRIT
        assert _icon_for(50.0, 0.0, 0.0) == _ICON_CRIT

    def test_custom_thresholds(self):
        assert _icon_for(60.0, 50.0, 80.0) == _ICON_WARN
        assert _icon_for(49.9, 50.0, 80.0) == _ICON_OK
        assert _icon_for(80.0, 50.0, 80.0) == _ICON_CRIT


_NOW = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)


def _at(seconds_from_now: int) -> datetime:
    return datetime.fromtimestamp(_NOW.timestamp() + seconds_from_now, tz=timezone.utc)


class TestFormatUntil:
    def test_none_returns_empty(self):
        assert _format_until(None, now=_NOW) == ""

    def test_past_returns_empty(self):
        assert _format_until(_at(-60), now=_NOW) == ""

    def test_zero_returns_empty(self):
        assert _format_until(_NOW, now=_NOW) == ""

    def test_under_one_minute(self):
        assert _format_until(_at(30), now=_NOW) == "in <1m"

    def test_minutes_only(self):
        assert _format_until(_at(5 * 60), now=_NOW) == "in 5m"

    def test_one_hour_exact(self):
        assert _format_until(_at(3600), now=_NOW) == "in 1h 0m"

    def test_hours_and_minutes(self):
        assert _format_until(_at(3600 + 23 * 60), now=_NOW) == "in 1h 23m"

    def test_just_under_a_day(self):
        assert _format_until(_at(86400 - 60), now=_NOW) == "in 23h 59m"

    def test_one_day_exact(self):
        assert _format_until(_at(86400), now=_NOW) == "in 1d 0h"

    def test_days_and_hours(self):
        assert _format_until(_at(2 * 86400 + 5 * 3600), now=_NOW) == "in 2d 5h"

    def test_naive_now_default(self):
        # When now=None it uses datetime.now(); just check the return type/shape
        # for a far-future timestamp so flakiness is impossible.
        future = datetime(2099, 1, 1, tzinfo=timezone.utc)
        result = _format_until(future)
        assert result.startswith("in ") and result.endswith("h")
