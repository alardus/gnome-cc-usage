"""Phase 1 verification 1b — does OAuth Bearer work against api.anthropic.com?

Tries several plausible URLs for the OAuth-token-accepting usage endpoint.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CREDS = Path.home() / ".claude" / ".credentials.json"
ACCESS = json.loads(CREDS.read_text())["claudeAiOauth"]["accessToken"]

candidates = [
    # Anthropic usage/organization endpoints
    "https://api.anthropic.com/api/oauth/profile",
    "https://api.anthropic.com/api/account",
    "https://api.anthropic.com/api/organizations",
    "https://api.anthropic.com/v1/organizations",
    "https://api.anthropic.com/api/claude_code/usage",
    "https://api.anthropic.com/api/oauth/claude_cli/profile",
    # claude.ai variants beyond the main one already tested
    "https://claude.ai/api/account",
    "https://claude.ai/api/oauth/profile",
    "https://claude.ai/api/auth/current_account",
    "https://claude.ai/api/claude_code/usage",
]

for url in candidates:
    print(f"\n=== {url} ===")
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {ACCESS}",
            "User-Agent": "cc-usage-probe/0.1",
            "Accept": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print("status:", resp.status)
            body = resp.read().decode("utf-8", errors="replace")
            print("body[:600]:", body[:600])
    except urllib.error.HTTPError as e:
        body = e.read()[:400].decode(errors="replace")
        print(f"HTTP {e.code}: {body}")
    except urllib.error.URLError as e:
        print(f"URLError: {e}")
