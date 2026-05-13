from __future__ import annotations

import logging
from datetime import datetime, timezone

import requests

from cc_usage import __version__
from cc_usage.api.models import ApiError, Bucket, UsageSnapshot
from cc_usage.auth.oauth import OAuthProvider, OAuthRefreshError

logger = logging.getLogger("cc_usage")


class ClaudeUsageClient:
    BASE = "https://api.anthropic.com"

    def __init__(self, auth: OAuthProvider) -> None:
        self._auth = auth
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json",
            "User-Agent": f"cc-usage/{__version__} (+https://github.com/user/gnome-cc-usage)",
        })

    @property
    def auth(self) -> OAuthProvider:
        return self._auth

    def fetch_usage(self) -> UsageSnapshot:
        did_refresh = False
        while True:
            token = self._auth.access_token()
            headers = {"Authorization": f"Bearer {token}"}
            try:
                resp = self._session.get(
                    f"{self.BASE}/api/oauth/usage",
                    headers=headers,
                    timeout=15,
                )
            except requests.RequestException as exc:
                raise ApiError(
                    status=0,
                    message=str(exc),
                    is_rate_limit=False,
                    is_auth_error=False,
                ) from exc

            logger.debug("GET /api/oauth/usage → %d", resp.status_code)

            if resp.status_code == 200:
                return self._parse(resp.json())

            # On 401, attempt a single token refresh and retry the request.
            if resp.status_code == 401 and not did_refresh:
                try:
                    if self._auth.force_refresh():
                        did_refresh = True
                        logger.info("fetch_usage: refreshed token after 401; retrying.")
                        continue
                except OAuthRefreshError as exc:
                    logger.error("fetch_usage: token refresh failed: %s", exc)
                    # Fall through to raise ApiError below.

            if resp.status_code in (401, 403):
                msg = _extract_message(resp)
                raise ApiError(status=resp.status_code, message=msg, is_rate_limit=False, is_auth_error=True)
            if resp.status_code == 429:
                msg = _extract_message(resp)
                retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                raise ApiError(
                    status=resp.status_code,
                    message=msg,
                    is_rate_limit=True,
                    is_auth_error=False,
                    retry_after=retry_after,
                )
            msg = _extract_message(resp)
            raise ApiError(status=resp.status_code, message=msg, is_rate_limit=False, is_auth_error=False)

    @staticmethod
    def _parse(data: dict) -> UsageSnapshot:
        extra = data.get("extra_usage") or {}
        extra_enabled = bool(extra.get("is_enabled", False))
        buckets: dict[str, Bucket] = {}
        for key, value in data.items():
            if key == "extra_usage":
                continue
            if isinstance(value, dict) and "utilization" in value:
                bucket = Bucket.from_json(value)
                if bucket is not None:
                    buckets[key] = bucket
        return UsageSnapshot(
            buckets=buckets,
            extra_usage_enabled=extra_enabled,
            fetched_at=datetime.now(tz=timezone.utc),
        )


def _parse_retry_after(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return max(0, int(value.strip()))
    except ValueError:
        # Spec also allows HTTP-date; we don't bother — log and ignore.
        logger.warning("Unparseable Retry-After header: %r", value)
        return None


def _extract_message(resp: requests.Response) -> str:
    try:
        body = resp.json()
        return body.get("error", {}).get("message") or body.get("message") or resp.text
    except Exception:
        return resp.text
