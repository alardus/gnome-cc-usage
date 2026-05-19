"""GTK3 settings dialog for cc-usage.

Can be opened from the tray menu (on_settings callback) or as a standalone
process via ``cc-usage --settings``.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cc_usage.config import Config

# Autostart desktop entry source
_AUTOSTART_SRC = (
    Path(__file__).parent.parent.parent.parent / "packaging" / "cc-usage-autostart.desktop"
)
_AUTOSTART_DEST = Path.home() / ".config" / "autostart" / "cc-usage.desktop"


def _get_autostart_enabled() -> bool:
    return _AUTOSTART_DEST.exists()


def _set_autostart_enabled(enabled: bool) -> None:
    if enabled:
        _AUTOSTART_DEST.parent.mkdir(parents=True, exist_ok=True)
        if _AUTOSTART_SRC.exists():
            shutil.copy2(str(_AUTOSTART_SRC), str(_AUTOSTART_DEST))
        else:
            # Fallback: write a minimal desktop entry if source not found.
            _AUTOSTART_DEST.write_text(
                "[Desktop Entry]\n"
                "Type=Application\n"
                "Name=Claude Code Usage\n"
                "Exec=cc-usage\n"
                "Icon=cc-usage-symbolic\n"
                "X-GNOME-Autostart-enabled=true\n"
            )
    else:
        if _AUTOSTART_DEST.exists():
            _AUTOSTART_DEST.unlink()


def open_settings_dialog(cfg: "Config") -> None:
    """Open the settings dialog.  Blocks until the dialog is dismissed."""
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        from gi.repository import Gtk
    except (ValueError, ImportError) as exc:
        print(f"ERROR: Cannot load GTK3: {exc}", file=sys.stderr)
        sys.exit(1)

    dialog = Gtk.Dialog(title="cc-usage Settings")
    dialog.set_default_size(420, -1)
    dialog.set_border_width(8)
    dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
    ok_btn = dialog.add_button("OK", Gtk.ResponseType.OK)
    ok_btn.get_style_context().add_class("suggested-action")

    content = dialog.get_content_area()

    grid = Gtk.Grid()
    grid.set_column_spacing(12)
    grid.set_row_spacing(8)
    grid.set_border_width(8)
    content.pack_start(grid, True, True, 0)

    row = 0

    def _add_label(text: str, r: int) -> None:
        lbl = Gtk.Label(label=text, xalign=1.0)
        lbl.set_halign(Gtk.Align.END)
        grid.attach(lbl, 0, r, 1, 1)

    # Poll interval
    _add_label("Poll interval (s):", row)
    spin_interval = Gtk.SpinButton()
    spin_interval.set_adjustment(Gtk.Adjustment(
        value=cfg.poll.interval_seconds,
        lower=60, upper=1800, step_increment=30, page_increment=60,
    ))
    spin_interval.set_numeric(True)
    spin_interval.set_snap_to_ticks(True)
    grid.attach(spin_interval, 1, row, 1, 1)
    row += 1

    # Warn threshold
    _add_label("Warn threshold (%):", row)
    spin_warn = Gtk.SpinButton()
    spin_warn.set_adjustment(Gtk.Adjustment(
        value=cfg.ui.warn_threshold,
        lower=0, upper=100, step_increment=5, page_increment=10,
    ))
    spin_warn.set_numeric(True)
    grid.attach(spin_warn, 1, row, 1, 1)
    row += 1

    # Crit threshold
    _add_label("Crit threshold (%):", row)
    spin_crit = Gtk.SpinButton()
    spin_crit.set_adjustment(Gtk.Adjustment(
        value=cfg.ui.crit_threshold,
        lower=0, upper=100, step_increment=5, page_increment=10,
    ))
    spin_crit.set_numeric(True)
    grid.attach(spin_crit, 1, row, 1, 1)
    row += 1

    # Show label
    _add_label("Show label:", row)
    combo_label = Gtk.ComboBoxText()
    for opt in ("max", "five_hour", "seven_day"):
        combo_label.append_text(opt)
    show_options = ["max", "five_hour", "seven_day"]
    try:
        combo_label.set_active(show_options.index(cfg.ui.show_label))
    except ValueError:
        combo_label.set_active(0)
    grid.attach(combo_label, 1, row, 1, 1)
    row += 1

    # Show time remaining in menubar label
    _add_label("Show time remaining:", row)
    switch_time_remaining = Gtk.Switch()
    switch_time_remaining.set_active(cfg.ui.show_time_remaining)
    switch_time_remaining.set_halign(Gtk.Align.START)
    grid.attach(switch_time_remaining, 1, row, 1, 1)
    row += 1

    # Autostart toggle
    _add_label("Start on login:", row)
    switch_autostart = Gtk.Switch()
    switch_autostart.set_active(_get_autostart_enabled())
    switch_autostart.set_halign(Gtk.Align.START)
    grid.attach(switch_autostart, 1, row, 1, 1)
    row += 1

    # Open log directory button
    _add_label("Log/cache dir:", row)
    btn_open_log = Gtk.Button(label="Open in file manager")
    btn_open_log.connect("clicked", _on_open_log)
    grid.attach(btn_open_log, 1, row, 1, 1)
    row += 1

    dialog.show_all()
    response = dialog.run()

    if response == Gtk.ResponseType.OK:
        cfg.poll.interval_seconds = int(spin_interval.get_value())
        cfg.ui.warn_threshold = int(spin_warn.get_value())
        cfg.ui.crit_threshold = int(spin_crit.get_value())
        active_label = combo_label.get_active_text()
        if active_label:
            cfg.ui.show_label = active_label
        cfg.ui.show_time_remaining = switch_time_remaining.get_active()
        cfg.ui.autostart_enabled = switch_autostart.get_active()
        _set_autostart_enabled(cfg.ui.autostart_enabled)
        cfg.save()

    dialog.destroy()


def _on_open_log(_widget) -> None:
    import os
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    cache_dir = Path(base) / "cc-usage"
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(["xdg-open", str(cache_dir)])
    except FileNotFoundError:
        print(f"Cache directory: {cache_dir}", file=sys.stderr)
