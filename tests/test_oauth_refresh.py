"""Tests for OAuthProvider refresh logic — NO live network calls."""
from __future__ import annotations

import fcntl
import json
import multiprocessing
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from cc_usage.auth.oauth import OAuthProvider, OAuthRefreshError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_CREDS = {
    "claudeAiOauth": {
        "accessToken": "sk-ant-oat01-OLD",
        "refreshToken": "sk-ant-ort01-OLD",
        "expiresAt": 0,   # overridden per test
    }
}

_NEW_TOKENS = {
    "access_token": "sk-ant-oat01-NEW",
    "refresh_token": "sk-ant-ort01-NEW",
    "expires_in": 3600,
    "token_type": "Bearer",
    "scope": "usage",
}


def _write_creds(path: Path, expires_in_seconds: float) -> None:
    """Write a credentials file whose token expires in *expires_in_seconds*."""
    data = json.loads(json.dumps(_BASE_CREDS))  # deep copy
    data["claudeAiOauth"]["expiresAt"] = int((time.time() + expires_in_seconds) * 1000)
    path.write_text(json.dumps(data, indent=2))
    os.chmod(path, 0o600)


def _provider(path: Path) -> OAuthProvider:
    return OAuthProvider(creds_path=path)


# ---------------------------------------------------------------------------
# is_near_expiry boundary tests
# ---------------------------------------------------------------------------

class TestIsNearExpiry:
    def test_expiring_soon_returns_true(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, 299)   # 299s < 300s leeway
        p = _provider(creds)
        assert p.is_near_expiry(leeway_seconds=300) is True

    def test_expiring_later_returns_false(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, 301)   # 301s > 300s leeway
        p = _provider(creds)
        assert p.is_near_expiry(leeway_seconds=300) is False

    def test_already_expired_returns_true(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, -10)   # expired 10s ago
        p = _provider(creds)
        assert p.is_near_expiry(leeway_seconds=300) is True

    def test_no_expires_at_returns_false(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        data = {"claudeAiOauth": {"accessToken": "tok", "refreshToken": "rt"}}
        creds.write_text(json.dumps(data))
        p = _provider(creds)
        assert p.is_near_expiry(leeway_seconds=300) is False


# ---------------------------------------------------------------------------
# refresh_if_needed
# ---------------------------------------------------------------------------

class TestRefreshIfNeeded:
    def test_not_near_expiry_returns_true_without_refreshing(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, 9999)   # far future
        p = _provider(creds)
        with patch.object(p, "force_refresh") as mock_force:
            result = p.refresh_if_needed()
        assert result is True
        mock_force.assert_not_called()

    def test_near_expiry_calls_force_refresh(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, 10)    # 10s — within 300s leeway
        p = _provider(creds)
        with patch.object(p, "force_refresh", return_value=True) as mock_force:
            result = p.refresh_if_needed()
        assert result is True
        mock_force.assert_called_once()

    def test_unavailable_returns_false(self, tmp_path):
        creds = tmp_path / "missing.json"
        p = _provider(creds)
        result = p.refresh_if_needed()
        assert result is False


# ---------------------------------------------------------------------------
# force_refresh — success path
# ---------------------------------------------------------------------------

class TestForceRefreshSuccess:
    def test_writes_new_tokens_to_file(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, -10)   # expired
        p = _provider(creds)

        with patch.object(p, "_exchange_refresh_token", return_value=dict(_NEW_TOKENS)):
            result = p.force_refresh()

        assert result is True
        updated = json.loads(creds.read_text())
        oauth = updated["claudeAiOauth"]
        assert oauth["accessToken"] == "sk-ant-oat01-NEW"
        assert oauth["refreshToken"] == "sk-ant-ort01-NEW"
        # expiresAt should be roughly now + 3600s (allow 10s tolerance)
        expected_ms = (time.time() + 3600) * 1000
        assert abs(oauth["expiresAt"] - expected_ms) < 10_000

    def test_preserves_0600_permissions(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, -10)
        p = _provider(creds)

        with patch.object(p, "_exchange_refresh_token", return_value=dict(_NEW_TOKENS)):
            p.force_refresh()

        mode = stat.S_IMODE(creds.stat().st_mode)
        assert mode == 0o600

    def test_file_is_valid_json_after_refresh(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, -10)
        p = _provider(creds)

        with patch.object(p, "_exchange_refresh_token", return_value=dict(_NEW_TOKENS)):
            p.force_refresh()

        # Must be parseable without error
        data = json.loads(creds.read_text())
        assert "claudeAiOauth" in data


# ---------------------------------------------------------------------------
# force_refresh — error paths
# ---------------------------------------------------------------------------

class TestForceRefreshErrors:
    def test_400_response_raises_oauth_refresh_error(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, -10)
        p = _provider(creds)

        with patch.object(
            p,
            "_exchange_refresh_token",
            side_effect=OAuthRefreshError("HTTP 400: invalid_request"),
        ):
            with pytest.raises(OAuthRefreshError, match="invalid_request"):
                p.force_refresh()

    def test_5xx_raises_oauth_refresh_error(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, -10)
        p = _provider(creds)

        with patch.object(
            p,
            "_exchange_refresh_token",
            side_effect=OAuthRefreshError("HTTP 500: Internal Server Error"),
        ):
            with pytest.raises(OAuthRefreshError, match="500"):
                p.force_refresh()

    def test_network_error_raises_oauth_refresh_error(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, -10)
        p = _provider(creds)

        with patch.object(
            p,
            "_exchange_refresh_token",
            side_effect=OAuthRefreshError("network/server error: Connection refused"),
        ):
            with pytest.raises(OAuthRefreshError, match="network"):
                p.force_refresh()

    def test_missing_file_returns_false(self, tmp_path):
        creds = tmp_path / "does_not_exist.json"
        p = _provider(creds)
        result = p.force_refresh()
        assert result is False

    def test_missing_refresh_token_returns_false(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        data = {
            "claudeAiOauth": {
                "accessToken": "tok",
                "expiresAt": int((time.time() - 10) * 1000),
            }
        }
        creds.write_text(json.dumps(data))
        os.chmod(creds, 0o600)
        p = _provider(creds)
        result = p.force_refresh()
        assert result is False


# ---------------------------------------------------------------------------
# mtime skip — Claude Code already refreshed
# ---------------------------------------------------------------------------

class TestMtimeSkip:
    def test_skip_when_file_recently_touched_and_token_still_valid(self, tmp_path):
        """If another process wrote the file within 60s and token is no longer
        near expiry, force_refresh must NOT make a POST and must return True."""
        creds = tmp_path / ".credentials.json"
        # Token has 600s remaining — NOT near expiry with 300s leeway.
        _write_creds(creds, 600)
        # Touch mtime to now (simulating Claude Code just refreshed).
        now = time.time()
        os.utime(creds, (now, now))

        p = _provider(creds)
        with patch.object(p, "_exchange_refresh_token") as mock_exchange:
            result = p.force_refresh()

        assert result is True
        mock_exchange.assert_not_called()

    def test_no_skip_when_file_old_even_if_token_valid(self, tmp_path):
        """If the file is old (>60s) but token is still valid, we refresh
        because our pre-check logic passes the mtime guard."""
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, 600)  # token valid for 600s (>300s leeway)
        # Backdate mtime to 120s ago — beyond the 60s skip window.
        old_time = time.time() - 120
        os.utime(creds, (old_time, old_time))

        p = _provider(creds)
        with patch.object(p, "_exchange_refresh_token", return_value=dict(_NEW_TOKENS)):
            result = p.force_refresh()

        # Exchange is called because mtime guard is not satisfied (file is old).
        assert result is True


# ---------------------------------------------------------------------------
# flock is acquired with LOCK_EX
# ---------------------------------------------------------------------------

class TestFileLock:
    def test_flock_called_with_lock_ex(self, tmp_path):
        creds = tmp_path / ".credentials.json"
        _write_creds(creds, -10)
        p = _provider(creds)

        with patch("fcntl.flock") as mock_flock, \
             patch.object(p, "_exchange_refresh_token", return_value=dict(_NEW_TOKENS)):
            p.force_refresh()

        # Verify that LOCK_EX was requested as the first lock call.
        assert mock_flock.call_count >= 2  # LOCK_EX + LOCK_UN
        first_lock_call_args = mock_flock.call_args_list[0]
        assert first_lock_call_args[0][1] == fcntl.LOCK_EX


# ---------------------------------------------------------------------------
# _exchange_refresh_token unit tests (mocking requests.post)
# ---------------------------------------------------------------------------

class TestExchangeRefreshToken:
    def test_200_returns_parsed_json(self, tmp_path):
        p = _provider(tmp_path / ".credentials.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = dict(_NEW_TOKENS)

        with patch("cc_usage.auth.oauth.requests.post", return_value=mock_resp):
            result = p._exchange_refresh_token("sk-ant-ort01-FAKE")

        assert result["access_token"] == "sk-ant-oat01-NEW"
        assert result["expires_in"] == 3600

    def test_400_raises_oauth_refresh_error(self, tmp_path):
        p = _provider(tmp_path / ".credentials.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {
            "error": "invalid_request",
            "error_description": "Invalid JSON body",
        }

        with patch("cc_usage.auth.oauth.requests.post", return_value=mock_resp):
            with pytest.raises(OAuthRefreshError, match="Invalid JSON body"):
                p._exchange_refresh_token("sk-ant-ort01-FAKE")

    def test_401_invalid_client_raises_oauth_refresh_error(self, tmp_path):
        p = _provider(tmp_path / ".credentials.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.json.return_value = {"error": "invalid_client"}

        with patch("cc_usage.auth.oauth.requests.post", return_value=mock_resp):
            with pytest.raises(OAuthRefreshError, match="invalid_client"):
                p._exchange_refresh_token("sk-ant-ort01-FAKE")

    def test_500_raises_oauth_refresh_error(self, tmp_path):
        p = _provider(tmp_path / ".credentials.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.json.side_effect = Exception("not JSON")
        mock_resp.text = "Internal Server Error"

        with patch("cc_usage.auth.oauth.requests.post", return_value=mock_resp):
            with pytest.raises(OAuthRefreshError, match="HTTP 500"):
                p._exchange_refresh_token("sk-ant-ort01-FAKE")

    def test_network_exception_raises_oauth_refresh_error(self, tmp_path):
        import requests as req_lib
        p = _provider(tmp_path / ".credentials.json")

        with patch(
            "cc_usage.auth.oauth.requests.post",
            side_effect=req_lib.ConnectionError("Connection refused"),
        ):
            with pytest.raises(OAuthRefreshError, match="network/server error"):
                p._exchange_refresh_token("sk-ant-ort01-FAKE")

    def test_no_retry_on_4xx(self, tmp_path):
        """Verify that _exchange_refresh_token calls requests.post exactly once
        even on a 4xx — no internal retry loop."""
        p = _provider(tmp_path / ".credentials.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.json.return_value = {"error": "invalid_request"}

        with patch("cc_usage.auth.oauth.requests.post", return_value=mock_resp) as mock_post:
            with pytest.raises(OAuthRefreshError):
                p._exchange_refresh_token("sk-ant-ort01-FAKE")

        assert mock_post.call_count == 1

    def test_request_uses_json_content_type(self, tmp_path):
        """Ensure the POST includes Content-Type: application/json."""
        p = _provider(tmp_path / ".credentials.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = dict(_NEW_TOKENS)

        with patch("cc_usage.auth.oauth.requests.post", return_value=mock_resp) as mock_post:
            p._exchange_refresh_token("sk-ant-ort01-FAKE")

        _, kwargs = mock_post.call_args
        assert kwargs.get("headers", {}).get("Content-Type") == "application/json"

    def test_request_body_includes_grant_type_and_refresh_token(self, tmp_path):
        p = _provider(tmp_path / ".credentials.json")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = dict(_NEW_TOKENS)

        with patch("cc_usage.auth.oauth.requests.post", return_value=mock_resp) as mock_post:
            p._exchange_refresh_token("MY_REFRESH_TOKEN")

        _, kwargs = mock_post.call_args
        body = kwargs.get("json", {})
        assert body["grant_type"] == "refresh_token"
        assert body["refresh_token"] == "MY_REFRESH_TOKEN"
