from __future__ import annotations

import logging
import random
import threading
from typing import TYPE_CHECKING

from gi.repository import GLib

from cc_usage.api.models import ApiError
from cc_usage.auth.oauth import OAuthRefreshError
if TYPE_CHECKING:
    from cc_usage.api.client import ClaudeUsageClient
    from cc_usage.api.models import UsageSnapshot
    from cc_usage.config import Config
    from cc_usage.indicator import Indicator
    from cc_usage.ui.notify import Notifier

logger = logging.getLogger("cc_usage")


class Poller:
    def __init__(
        self,
        client: "ClaudeUsageClient",
        indicator: "Indicator",
        config: "Config",
        notifier: "Notifier | None" = None,
    ) -> None:
        self._client = client
        self._indicator = indicator
        self._cfg = config
        self._notifier = notifier
        self._current_interval = config.poll.interval_seconds
        self._timer_id: int | None = None
        self._last_snapshot: "UsageSnapshot | None" = None

    def start(self) -> None:
        self._schedule(delay=0)

    def stop(self) -> None:
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None

    def refresh_now(self) -> None:
        self.stop()
        self._schedule(delay=0)

    def _schedule(self, delay: int) -> None:
        jitter = self._cfg.poll.jitter_seconds
        effective = max(5, delay + int(random.uniform(-jitter, jitter))) if delay > 0 else 0
        logger.debug("Next poll in %ds", effective)
        self._timer_id = GLib.timeout_add_seconds(effective, self._tick_dispatch)

    def _tick_dispatch(self) -> bool:
        # Return False so GLib treats this as one-shot; we re-schedule in _on_result.
        self._timer_id = None
        t = threading.Thread(target=self._tick, daemon=True)
        t.start()
        return False

    def _tick(self) -> None:
        # Proactively refresh the OAuth token if it is near expiry.
        # We access auth via the client so no new constructor parameter is needed.
        try:
            self._client.auth.refresh_if_needed()
        except OAuthRefreshError as exc:
            logger.error("OAuth refresh failed: %s", exc)
            # Let fetch_usage proceed; a 401 will surface as an auth error and
            # the indicator will reflect the failure state.

        try:
            snapshot = self._client.fetch_usage()
            GLib.idle_add(self._on_result, snapshot, None)
        except ApiError as exc:
            GLib.idle_add(self._on_result, None, exc)
        except Exception as exc:
            err = ApiError(status=0, message=str(exc), is_rate_limit=False, is_auth_error=False)
            GLib.idle_add(self._on_result, None, err)

    def _on_result(self, snapshot: "UsageSnapshot | None", error: ApiError | None) -> bool:
        if error is None:
            logger.info("Usage fetched: max=%.1f%%", snapshot.max_utilization())
            # Fire notifications for upward threshold crossings BEFORE updating
            # last_snapshot (so we can compare against the previous state).
            if self._last_snapshot is not None and self._notifier is not None:
                self._check_threshold_crossings(snapshot)
            self._last_snapshot = snapshot
            self._indicator.update(snapshot)
            self._current_interval = self._cfg.poll.interval_seconds
        else:
            logger.warning("Fetch error (status=%d): %s", error.status, error.message)
            self._indicator.set_error(error)
            # On 429 with Retry-After, honor the server's wait — clamped to
            # the configured cap so a hostile/buggy server can't park us
            # indefinitely. Otherwise fall back to exponential backoff.
            if error.is_rate_limit and error.retry_after is not None:
                self._current_interval = min(
                    max(error.retry_after, self._cfg.poll.interval_seconds),
                    self._cfg.poll.backoff_max_seconds,
                )
                logger.info("Honoring Retry-After: %ds", self._current_interval)
            else:
                self._current_interval = min(
                    max(self._current_interval * 2, self._cfg.poll.interval_seconds),
                    self._cfg.poll.backoff_max_seconds,
                )

        self._schedule(self._current_interval)
        return False   # idle_add callback: run once

    def _check_threshold_crossings(self, new_snapshot: "UsageSnapshot") -> None:
        """Compare new snapshot against previous; fire notifications on upward crosses."""
        if self._last_snapshot is None or self._notifier is None:
            return

        warn = float(self._cfg.ui.warn_threshold)
        crit = float(self._cfg.ui.crit_threshold)

        prev_buckets = dict(self._last_snapshot.named_buckets())
        new_buckets = dict(new_snapshot.named_buckets())

        for name, new_bucket in new_buckets.items():
            prev_bucket = prev_buckets.get(name)
            prev_util = prev_bucket.utilization if prev_bucket is not None else 0.0
            new_util = new_bucket.utilization

            if new_bucket.resets_at is None:
                continue

            # Warn crossing: prev < warn and new >= warn (and new < crit, to
            # avoid dual-firing when jumping straight past crit).
            if prev_util < warn <= new_util < crit:
                logger.info("Warn threshold crossed for bucket=%s (%.1f%%→%.1f%%)", name, prev_util, new_util)
                self._notifier.notify_threshold_cross(
                    bucket_name=name,
                    level="warn",
                    util=new_util,
                    resets_at=new_bucket.resets_at,
                )
            # Crit crossing: prev < crit and new >= crit.
            if prev_util < crit <= new_util:
                logger.info("Crit threshold crossed for bucket=%s (%.1f%%→%.1f%%)", name, prev_util, new_util)
                self._notifier.notify_threshold_cross(
                    bucket_name=name,
                    level="crit",
                    util=new_util,
                    resets_at=new_bucket.resets_at,
                )
