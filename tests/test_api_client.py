"""Tests for api/client.py — all network calls mocked."""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import requests

from cc_usage.api.client import ClaudeUsageClient
from cc_usage.api.models import ApiError, UsageSnapshot
from cc_usage.auth.oauth import OAuthProvider

_FULL_BODY = {
    "five_hour": {"utilization": 23.5, "resets_at": "2026-05-08T14:00:00+00:00"},
    "seven_day": {"utilization": 14.28, "resets_at": "2026-05-15T00:00:00+00:00"},
    "seven_day_opus": None,
    "seven_day_sonnet": {"utilization": 5.0, "resets_at": "2026-05-15T00:00:00+00:00"},
    "seven_day_oauth_apps": None,
    "seven_day_cowork": None,
    "seven_day_omelette": None,
    "extra_usage": {"is_enabled": False, "monthly_limit": None},
}


def _make_client() -> ClaudeUsageClient:
    auth = MagicMock(spec=OAuthProvider)
    auth.access_token.return_value = "sk-ant-oat01-fake"
    return ClaudeUsageClient(auth)


def _mock_response(status: int, json_body=None, raise_exc=None, headers=None):
    resp = MagicMock()
    resp.status_code = status
    if json_body is not None:
        resp.json.return_value = json_body
    if raise_exc is not None:
        resp.json.side_effect = raise_exc
    resp.text = str(json_body)
    resp.headers = headers or {}
    return resp


class TestFetchUsage200:
    def test_full_body_returns_snapshot(self):
        client = _make_client()
        with patch.object(client._session, "get", return_value=_mock_response(200, _FULL_BODY)):
            snap = client.fetch_usage()
        assert isinstance(snap, UsageSnapshot)
        assert "five_hour" in snap.buckets
        assert snap.buckets["five_hour"].utilization == pytest.approx(23.5)
        assert "seven_day" in snap.buckets
        assert "seven_day_opus" not in snap.buckets
        assert "seven_day_sonnet" in snap.buckets
        assert snap.extra_usage_enabled is False
        assert isinstance(snap.fetched_at, datetime)

    def test_all_null_buckets(self):
        body = {
            "five_hour": None,
            "seven_day": None,
            "seven_day_opus": None,
            "seven_day_sonnet": None,
            "seven_day_oauth_apps": None,
            "seven_day_cowork": None,
            "seven_day_omelette": None,
            "extra_usage": {"is_enabled": False},
        }
        client = _make_client()
        with patch.object(client._session, "get", return_value=_mock_response(200, body)):
            snap = client.fetch_usage()
        assert snap.named_buckets() == []
        assert snap.max_utilization() == 0.0
        assert snap.buckets == {}

    def test_extra_usage_enabled(self):
        body = dict(_FULL_BODY)
        body["extra_usage"] = {"is_enabled": True, "monthly_limit": 10}
        client = _make_client()
        with patch.object(client._session, "get", return_value=_mock_response(200, body)):
            snap = client.fetch_usage()
        assert snap.extra_usage_enabled is True


class TestFetchUsageErrors:
    def test_401_raises_auth_error(self):
        client = _make_client()
        resp = _mock_response(401, {"error": {"message": "Unauthorized"}})
        with patch.object(client._session, "get", return_value=resp):
            with pytest.raises(ApiError) as exc_info:
                client.fetch_usage()
        err = exc_info.value
        assert err.is_auth_error is True
        assert err.is_rate_limit is False
        assert err.status == 401

    def test_403_raises_auth_error(self):
        client = _make_client()
        resp = _mock_response(403, {"error": {"message": "Forbidden"}})
        with patch.object(client._session, "get", return_value=resp):
            with pytest.raises(ApiError) as exc_info:
                client.fetch_usage()
        err = exc_info.value
        assert err.is_auth_error is True
        assert err.status == 403

    def test_429_raises_rate_limit(self):
        client = _make_client()
        resp = _mock_response(429, {"error": {"message": "rate_limit_error"}})
        with patch.object(client._session, "get", return_value=resp):
            with pytest.raises(ApiError) as exc_info:
                client.fetch_usage()
        err = exc_info.value
        assert err.is_rate_limit is True
        assert err.is_auth_error is False
        assert err.status == 429
        assert err.retry_after is None    # no header → None

    def test_429_with_retry_after_header(self):
        client = _make_client()
        resp = _mock_response(
            429, {"error": {"message": "rate_limit"}}, headers={"Retry-After": "908"}
        )
        with patch.object(client._session, "get", return_value=resp):
            with pytest.raises(ApiError) as exc_info:
                client.fetch_usage()
        assert exc_info.value.retry_after == 908

    def test_429_with_unparseable_retry_after(self):
        client = _make_client()
        resp = _mock_response(
            429, {"error": {"message": "rate_limit"}},
            headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"},
        )
        with patch.object(client._session, "get", return_value=resp):
            with pytest.raises(ApiError) as exc_info:
                client.fetch_usage()
        # HTTP-date form falls back to None — we don't crash.
        assert exc_info.value.retry_after is None

    def test_500_raises_generic_error(self):
        client = _make_client()
        resp = _mock_response(500, {"message": "Internal Server Error"})
        with patch.object(client._session, "get", return_value=resp):
            with pytest.raises(ApiError) as exc_info:
                client.fetch_usage()
        err = exc_info.value
        assert err.is_rate_limit is False
        assert err.is_auth_error is False
        assert err.status == 500

    def test_network_error_raises_api_error(self):
        client = _make_client()
        with patch.object(
            client._session, "get", side_effect=requests.ConnectionError("Network unreachable")
        ):
            with pytest.raises(ApiError) as exc_info:
                client.fetch_usage()
        err = exc_info.value
        assert err.is_rate_limit is False
        assert err.is_auth_error is False
        assert err.status == 0
        assert "Network unreachable" in err.message
