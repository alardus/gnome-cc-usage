from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

logger = logging.getLogger("cc_usage")

_DEFAULT_CREDS = Path.home() / ".claude" / ".credentials.json"


class CredentialsUnavailable(Exception):
    pass


class OAuthRefreshError(Exception):
    """Refresh failed — user needs to re-authenticate via `claude`."""
    pass


class OAuthProvider:
    REFRESH_URL = "https://console.anthropic.com/v1/oauth/token"
    REFRESH_LEEWAY_S = 300          # refresh if < 300s until expiry
    SKIP_REFRESH_IF_FILE_TOUCHED_WITHIN_S = 60  # let Claude Code's refresh take precedence

    def __init__(self, creds_path: Path | None = None) -> None:
        self._path = creds_path or _DEFAULT_CREDS

    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text())
            return data["claudeAiOauth"]
        except (FileNotFoundError, KeyError, json.JSONDecodeError) as exc:
            raise CredentialsUnavailable(f"Cannot read credentials: {exc}") from exc

    def is_available(self) -> bool:
        try:
            oauth = self._read()
            return bool(oauth.get("accessToken"))
        except CredentialsUnavailable:
            return False

    def access_token(self) -> str:
        # Re-read every call so Claude Code's own refreshes are picked up.
        oauth = self._read()
        token = oauth.get("accessToken")
        if not token:
            raise CredentialsUnavailable("accessToken missing or empty")
        return token

    def expires_at(self) -> datetime | None:
        try:
            oauth = self._read()
            ms = oauth.get("expiresAt")
            if ms is None:
                return None
            return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)
        except CredentialsUnavailable:
            return None

    def is_near_expiry(self, leeway_seconds: int = 60) -> bool:
        exp = self.expires_at()
        if exp is None:
            return False
        delta = (exp - datetime.now(tz=timezone.utc)).total_seconds()
        return delta < leeway_seconds

    # ------------------------------------------------------------------
    # Refresh logic
    # ------------------------------------------------------------------

    def refresh_if_needed(self) -> bool:
        """Returns True if creds usable after this call, False otherwise.

        Idempotent — safe to call on every poll tick.
        """
        if not self.is_available():
            return False
        if not self.is_near_expiry(self.REFRESH_LEEWAY_S):
            return True
        return self.force_refresh()

    def force_refresh(self) -> bool:
        """Synchronously refresh the token.

        Acquires an advisory exclusive file lock on .credentials.json to
        coexist with Claude Code's own refresh.  If the file's mtime is
        within SKIP_REFRESH_IF_FILE_TOUCHED_WITHIN_S seconds *and* the
        token is no longer near expiry, we assume Claude Code already
        refreshed and skip our own POST.

        Returns True on success, False on permanent failure.
        Raises OAuthRefreshError only on unrecoverable failure (e.g. the
        refresh token has been revoked).
        """
        try:
            f = open(self._path, "r+")  # noqa: WPS515 (open in try is intentional)
        except OSError as exc:
            logger.warning("force_refresh: cannot open credentials file: %s", exc)
            return False

        with f:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                logger.warning("force_refresh: flock failed: %s", exc)
                return False

            try:
                # Re-read under lock; another process may have just refreshed.
                try:
                    data = json.load(f)
                    oauth = data["claudeAiOauth"]
                except (json.JSONDecodeError, KeyError) as exc:
                    logger.error("force_refresh: corrupt credentials file: %s", exc)
                    return False

                # mtime check — if another process (Claude Code) recently
                # wrote the file and the token is no longer near expiry,
                # skip our refresh.
                now = time.time()
                mtime = self._path.stat().st_mtime
                current_exp_ms = oauth.get("expiresAt")
                if current_exp_ms is not None:
                    current_exp = datetime.fromtimestamp(int(current_exp_ms) / 1000, tz=timezone.utc)
                    remaining = (current_exp - datetime.now(tz=timezone.utc)).total_seconds()
                    if (
                        (now - mtime) < self.SKIP_REFRESH_IF_FILE_TOUCHED_WITHIN_S
                        and remaining > self.REFRESH_LEEWAY_S
                    ):
                        logger.info(
                            "force_refresh: token already refreshed by another process "
                            "(mtime %.0fs ago, %.0fs remaining); skipping.",
                            now - mtime,
                            remaining,
                        )
                        return True

                refresh_token = oauth.get("refreshToken")
                if not refresh_token:
                    logger.error("force_refresh: no refreshToken in credentials file")
                    return False

                logger.info("force_refresh: exchanging refresh token …")
                new_tokens = self._exchange_refresh_token(refresh_token)

                # Update the credential file under the lock (atomic-ish:
                # truncate + write + fsync).
                data["claudeAiOauth"]["accessToken"] = new_tokens["access_token"]
                data["claudeAiOauth"]["refreshToken"] = new_tokens["refresh_token"]
                expires_in = int(new_tokens["expires_in"])
                data["claudeAiOauth"]["expiresAt"] = int((time.time() + expires_in) * 1000)

                f.seek(0)
                f.truncate()
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
                os.chmod(self._path, 0o600)

                logger.info("force_refresh: token refreshed, new expiry in %ds.", expires_in)
                return True

            except OAuthRefreshError:
                raise
            except Exception as exc:
                logger.error("force_refresh: unexpected error: %s", exc, exc_info=True)
                return False
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    def _exchange_refresh_token(self, refresh_token: str) -> dict:
        """POST the refresh endpoint and return the new token dict.

        Expected response keys: access_token, refresh_token, expires_in,
        token_type, scope.

        First attempt omits client_id; some Anthropic OAuth clients accept
        refresh without it.  If we get ``invalid_client`` in production,
        add client_id here.

        # TODO: client_id discovery — see docs/api-notes.md
        """
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        try:
            resp = requests.post(
                self.REFRESH_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
        except requests.RequestException as exc:
            raise OAuthRefreshError(f"network/server error: {exc}") from exc

        logger.debug("POST %s → %d", self.REFRESH_URL, resp.status_code)

        if resp.status_code == 200:
            return resp.json()

        # 4xx errors are deterministic — do NOT retry.
        try:
            body = resp.json()
            msg = (
                body.get("error_description")
                or body.get("error")
                or body.get("message")
                or resp.text
            )
        except Exception:
            msg = resp.text

        logger.error(
            "force_refresh: OAuth token endpoint returned %d: %s",
            resp.status_code,
            msg,
        )
        raise OAuthRefreshError(f"HTTP {resp.status_code}: {msg}")
