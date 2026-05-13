from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger("cc_usage")

# ---------------------------------------------------------------------------
# Icon path resolution via importlib.resources and the pure _icon_for()
# helper are defined before any GTK import so that unit tests and headless
# callers can import them without a running display or AyatanaAppIndicator3
# installed.
# ---------------------------------------------------------------------------


def _resolve_icon(name: str) -> str:
    """Return an absolute path to *name* inside the bundled icons directory.

    Uses ``importlib.resources.files`` so it works for both editable and
    wheel installs.  Falls back to an empty string (which AyatanaAppIndicator3
    accepts — it shows a generic icon) and logs a warning when the resource
    package is not importable.
    """
    try:
        from importlib.resources import files
        traversable = files("cc_usage._resources").joinpath("icons", name)
        return str(traversable)
    except Exception as exc:
        logger.warning("Could not resolve icon %r: %s — using empty icon name", name, exc)
        return ""


_ICON_OK   = _resolve_icon("cc-usage-symbolic.svg")
_ICON_WARN = _resolve_icon("cc-usage-warn-symbolic.svg")
_ICON_CRIT = _resolve_icon("cc-usage-crit-symbolic.svg")


def _icon_for(util: float, warn: float, crit: float) -> str:
    """Return the absolute icon path for the given utilisation level.

    The thresholds are *inclusive* — at exactly ``warn`` we return the warn
    icon; at exactly ``crit`` we return the crit icon.

    This is a pure function with no GTK dependency so it can be tested in
    a headless environment.
    """
    if util >= crit:
        return _ICON_CRIT
    if util >= warn:
        return _ICON_WARN
    return _ICON_OK


# ---------------------------------------------------------------------------
# GTK / AyatanaAppIndicator3 imports — only required by Indicator class.
# ---------------------------------------------------------------------------

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
    from gi.repository import GLib, Gtk
    _GTK_AVAILABLE = True
except (ValueError, ImportError) as _gtk_import_exc:
    _GTK_AVAILABLE = False
    _gtk_import_exc_msg = str(_gtk_import_exc)


def _require_gtk() -> None:
    """Raise SystemExit with a helpful message if GTK is unavailable."""
    if not _GTK_AVAILABLE:
        print(
            f"ERROR: Cannot load AyatanaAppIndicator3: {_gtk_import_exc_msg}\n"
            "Install the required system package and retry.\n"
            "  Fedora:  sudo dnf install libayatana-appindicator-gtk3\n"
            "  Ubuntu:  sudo apt install gir1.2-ayatanaappindicator3-0.1\n"
            "See README.md for full system dependency list.",
            file=sys.stderr,
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_resets(dt: datetime | None) -> str:
    if dt is None:
        return ""
    local = dt.astimezone()
    now = datetime.now(tz=timezone.utc).astimezone()
    delta = (local - now).total_seconds()
    if abs(delta) < 86400:
        return local.strftime("%H:%M")
    return local.strftime("%a %b %-d")


def _format_until(dt: datetime | None, now: datetime | None = None) -> str:
    """Return a compact relative time-to-reset like ``in 1h 23m`` or ``in 2d 5h``.

    Returns "" if *dt* is None or already in the past.
    *now* is injectable so tests can pin the reference instant.
    """
    if dt is None:
        return ""
    if now is None:
        now = datetime.now(tz=timezone.utc)
    delta = int((dt.astimezone(timezone.utc) - now).total_seconds())
    if delta <= 0:
        return ""
    days, rem = divmod(delta, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days > 0:
        return f"in {days}d {hours}h"
    if hours > 0:
        return f"in {hours}h {minutes}m"
    if minutes > 0:
        return f"in {minutes}m"
    return "in <1m"


# ---------------------------------------------------------------------------
# Indicator
# ---------------------------------------------------------------------------

class Indicator:
    def __init__(
        self,
        on_refresh: Callable[[], None],
        on_quit: Callable[[], None],
        on_settings: Optional[Callable[[], None]] = None,
        warn_threshold: float = 75.0,
        crit_threshold: float = 90.0,
        show_label: str = "max",
    ) -> None:
        _require_gtk()  # fail fast with a clear message if GTK not present

        self._on_refresh = on_refresh
        self._on_quit = on_quit
        self._on_settings = on_settings
        self._warn = warn_threshold
        self._crit = crit_threshold
        self._show_label = show_label
        self._bucket_items: list = []
        self._last_snapshot = None

        self._ind = AppIndicator.Indicator.new(
            "cc-usage",
            _ICON_OK,
            AppIndicator.IndicatorCategory.APPLICATION_STATUS,
        )
        self._ind.set_status(AppIndicator.IndicatorStatus.ACTIVE)
        self._ind.set_label("…", "100%")
        self._ind.set_menu(self._build_menu())

    def _build_menu(self):
        menu = Gtk.Menu()

        # Reserve 7 slots for bucket lines (max buckets we track)
        for _ in range(7):
            item = Gtk.MenuItem(label="")
            item.set_sensitive(False)
            item.hide()
            menu.append(item)
            self._bucket_items.append(item)

        menu.append(Gtk.SeparatorMenuItem())

        refresh_item = Gtk.MenuItem(label="Refresh now")
        refresh_item.connect("activate", lambda _: self._on_refresh())
        menu.append(refresh_item)

        menu.append(Gtk.SeparatorMenuItem())

        settings_item = Gtk.MenuItem(label="Settings…")
        settings_item.connect("activate", self._on_settings_clicked)
        menu.append(settings_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", lambda _: self._on_quit())
        menu.append(quit_item)

        menu.show_all()
        return menu

    def _on_settings_clicked(self, _item) -> None:
        if self._on_settings is not None:
            self._on_settings()

    # ------------------------------------------------------------------
    # Public state-update methods
    # ------------------------------------------------------------------

    def set_loading(self) -> None:
        self._ind.set_icon_full(_ICON_OK, "loading")
        self._ind.set_label("…", "100%")
        for item in self._bucket_items:
            item.hide()

    def apply_config(self, cfg) -> None:
        self._warn = float(cfg.ui.warn_threshold)
        self._crit = float(cfg.ui.crit_threshold)
        self._show_label = cfg.ui.show_label
        if self._last_snapshot is not None:
            self.update(self._last_snapshot)

    def update(self, snapshot) -> None:
        from cc_usage.api.models import UsageSnapshot  # noqa: F401

        self._last_snapshot = snapshot
        buckets = snapshot.named_buckets()
        max_util = snapshot.max_utilization()

        if self._show_label == "max":
            label_util = max_util
        else:
            bucket = snapshot.buckets.get(self._show_label)
            label_util = bucket.utilization if bucket else max_util

        self._ind.set_label(f"{int(round(label_util))}%", "100%")

        icon = _icon_for(max_util, self._warn, self._crit)
        self._ind.set_icon_full(icon, "icon")

        for i, item in enumerate(self._bucket_items):
            if i < len(buckets):
                name, bucket = buckets[i]
                resets = _format_resets(bucket.resets_at)
                until = _format_until(bucket.resets_at)
                if resets and until:
                    resets_str = f"  (resets {resets}, {until})"
                elif resets:
                    resets_str = f"  (resets {resets})"
                else:
                    resets_str = ""
                item.set_label(f"{name}:  {int(round(bucket.utilization))}%{resets_str}")
                item.show()
            else:
                item.hide()

    def set_error(self, err) -> None:
        from cc_usage.api.models import ApiError  # noqa: F401

        if err.is_rate_limit:
            self._ind.set_label("429", "100%")
        elif err.is_auth_error:
            self._ind.set_label("!", "100%")
        else:
            self._ind.set_label("Err", "100%")

        for i, item in enumerate(self._bucket_items):
            if i == 0:
                item.set_label(f"Error: {err.message[:60]}")
                item.show()
            else:
                item.hide()

