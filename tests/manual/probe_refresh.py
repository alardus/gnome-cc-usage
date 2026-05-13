"""
Manual probe for OAuth refresh — DO NOT run against the real credentials.

Usage (coordinator only, with Opus supervising):

    cp ~/.claude/.credentials.json /tmp/test-creds.json
    PYTHONPATH=src python3 tests/manual/probe_refresh.py /tmp/test-creds.json

This backdates the expiresAt, mocks the HTTP POST, and verifies that
force_refresh() writes the new tokens correctly.  No real network call is made.

To do a live refresh (ROTATES YOUR TOKENS — coordinator-supervised only):
    python3 tests/manual/probe_refresh.py /tmp/test-creds.json --live
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

# Ensure src/ is on path when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from cc_usage.auth.oauth import OAuthProvider

_NEW_TOKENS = {
    "access_token": "sk-ant-oat01-MOCK-NEW",
    "refresh_token": "sk-ant-ort01-MOCK-NEW",
    "expires_in": 3600,
    "token_type": "Bearer",
    "scope": "usage",
}


def run_mock(creds_path: Path) -> None:
    """Backdate expiresAt and run force_refresh with a mocked POST."""
    data = json.loads(creds_path.read_text())
    data["claudeAiOauth"]["expiresAt"] = int(time.time() * 1000) - 10_000  # 10s ago
    creds_path.write_text(json.dumps(data, indent=2))
    os.chmod(creds_path, 0o600)

    provider = OAuthProvider(creds_path)
    print(f"is_available: {provider.is_available()}")
    print(f"is_near_expiry(300): {provider.is_near_expiry(300)}")

    with patch.object(
        provider,
        "_exchange_refresh_token",
        return_value=dict(_NEW_TOKENS),
    ):
        result = provider.refresh_if_needed()

    print(f"refresh_if_needed result: {result}")
    new = json.loads(creds_path.read_text())
    print(f"new accessToken in file: {new['claudeAiOauth']['accessToken']}")
    print(f"new refreshToken in file: {new['claudeAiOauth']['refreshToken']}")
    perms = oct(os.stat(creds_path).st_mode & 0o777)
    print(f"file permissions: {perms}")


def run_live(creds_path: Path) -> None:
    """Live refresh — ROTATES REAL TOKENS. Coordinator use only."""
    print("WARNING: This will make a real POST to the OAuth endpoint and rotate your tokens.")
    confirm = input("Type 'yes' to continue: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return

    provider = OAuthProvider(creds_path)
    print(f"is_near_expiry(300): {provider.is_near_expiry(300)}")
    result = provider.force_refresh()
    print(f"force_refresh result: {result}")
    new = json.loads(creds_path.read_text())
    print(f"new expiresAt: {new['claudeAiOauth']['expiresAt']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    path = Path(sys.argv[1])
    live = "--live" in sys.argv

    if live:
        run_live(path)
    else:
        run_mock(path)
