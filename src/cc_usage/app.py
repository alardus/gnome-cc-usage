from __future__ import annotations

import argparse
import sys

from cc_usage import __version__
from cc_usage import log as _log
from cc_usage.api.client import ClaudeUsageClient
from cc_usage.api.models import ApiError
from cc_usage.auth.oauth import CredentialsUnavailable, OAuthProvider
from cc_usage.config import Config


def _parse_argv() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="cc-usage",
        description="Claude Code usage tray indicator",
    )
    parser.add_argument("--version", action="version", version=f"cc-usage {__version__}")
    parser.add_argument("--once", action="store_true", help="Fetch once, print snapshot, and exit")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--settings", action="store_true", help="Open settings dialog")
    return parser.parse_args()


def main() -> None:
    args = _parse_argv()
    _log.setup(debug=args.debug)

    cfg = Config.load()

    if args.settings:
        from cc_usage.ui.settings_dialog import open_settings_dialog
        open_settings_dialog(cfg)
        return

    auth = OAuthProvider()

    if not auth.is_available():
        print(
            "ERROR: ~/.claude/.credentials.json not found or missing accessToken.\n"
            "Run `claude` to log in first.",
            file=sys.stderr,
        )
        sys.exit(2)

    if auth.is_near_expiry(60):
        print(
            "WARN: OAuth token expires soon. Run `claude` to refresh, then restart cc-usage.",
            file=sys.stderr,
        )

    client = ClaudeUsageClient(auth)

    if args.once:
        try:
            snapshot = client.fetch_usage()
        except ApiError as exc:
            if exc.is_rate_limit:
                print(f"Rate limited (429) — try again later. Message: {exc.message}", file=sys.stderr)
                sys.exit(3)
            if exc.is_auth_error:
                print(f"Auth error ({exc.status}) — run `claude` to refresh credentials.", file=sys.stderr)
                sys.exit(2)
            print(f"API error ({exc.status}): {exc.message}", file=sys.stderr)
            sys.exit(1)
        except CredentialsUnavailable as exc:
            print(f"Credentials unavailable: {exc}", file=sys.stderr)
            sys.exit(2)

        print(f"Fetched at: {snapshot.fetched_at}")
        print(f"Extra usage enabled: {snapshot.extra_usage_enabled}")
        print(f"Max utilization: {snapshot.max_utilization():.1f}%")
        for label, bucket in snapshot.named_buckets():
            resets = f"  resets {bucket.resets_at}" if bucket.resets_at else ""
            print(f"  {label}: {bucket.utilization:.1f}%{resets}")
        return

    # Tray mode — import GTK-dependent modules only here so --once works headlessly.
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    from cc_usage.indicator import Indicator
    from cc_usage.poller import Poller
    from cc_usage.ui.notify import Notifier
    from cc_usage.ui.settings_dialog import open_settings_dialog

    notifier = Notifier()

    # poller is assigned after indicator so the lambda closure captures it correctly.
    poller: Poller | None = None

    def _on_refresh() -> None:
        if poller is not None:
            poller.refresh_now()

    def _on_settings() -> None:
        old_interval = cfg.poll.interval_seconds
        open_settings_dialog(cfg)
        indicator.apply_config(cfg)
        if cfg.poll.interval_seconds != old_interval and poller is not None:
            poller.refresh_now()

    indicator = Indicator(
        on_refresh=_on_refresh,
        on_quit=Gtk.main_quit,
        on_settings=_on_settings,
        warn_threshold=float(cfg.ui.warn_threshold),
        crit_threshold=float(cfg.ui.crit_threshold),
        show_label=cfg.ui.show_label,
    )
    indicator.set_loading()

    poller = Poller(client, indicator, cfg, notifier=notifier)
    poller.start()

    Gtk.main()
