"""Phase 1 verification 1c — find an OAuth-Bearer-accepting usage endpoint.

We found /api/oauth/profile works. The org UUID is in that response.
Now probe usage endpoints under several plausible paths.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

CREDS = Path.home() / ".claude" / ".credentials.json"
ACCESS = json.loads(CREDS.read_text())["claudeAiOauth"]["accessToken"]

# Discover org_id via /api/oauth/profile (verified working)
profile_req = urllib.request.Request(
    "https://api.anthropic.com/api/oauth/profile",
    headers={"Authorization": f"Bearer {ACCESS}", "Accept": "application/json"},
)
with urllib.request.urlopen(profile_req, timeout=10) as r:
    profile = json.loads(r.read())
ORG = profile["organization"]["uuid"]
print("org_uuid:", ORG)

candidates = [
    # /api/oauth/* namespace — most likely
    f"https://api.anthropic.com/api/oauth/usage",
    f"https://api.anthropic.com/api/oauth/usage_limits",
    f"https://api.anthropic.com/api/oauth/rate_limits",
    f"https://api.anthropic.com/api/oauth/organizations/{ORG}/usage",
    f"https://api.anthropic.com/api/oauth/claude_cli/usage",
    f"https://api.anthropic.com/api/oauth/claude_code/usage",
    f"https://claude.ai/api/oauth/usage",
    f"https://claude.ai/api/oauth/organizations/{ORG}/usage",
    # /api/account_usage variants
    f"https://api.anthropic.com/api/usage",
    f"https://api.anthropic.com/api/rate_limits",
    f"https://api.anthropic.com/api/claude_cli/usage",
    # rate_limit_status (used by some Anthropic clients)
    f"https://api.anthropic.com/api/rate_limit_status",
    f"https://api.anthropic.com/api/oauth/rate_limit_status",
    # Maybe the org-scoped variants accept OAuth after all
    f"https://api.anthropic.com/api/organizations/{ORG}/usage",
    f"https://claude.ai/api/organizations/{ORG}/usage",
    f"https://claude.ai/api/organizations/{ORG}/rate_limits",
]

for url in candidates:
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {ACCESS}",
            "Accept": "application/json",
            "User-Agent": "cc-usage-probe/0.1",
            "anthropic-beta": "oauth-2025-04-20",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            print(f"  200  {url}")
            print(f"       body[:500]: {body[:500]}")
    except urllib.error.HTTPError as e:
        body = e.read()[:200].decode(errors="replace")
        # Skip the standard 404/403 noise; only show interesting ones
        marker = "*" if e.code not in (403, 404) else " "
        print(f"  {marker}{e.code}  {url}  | {body[:120]}")
    except urllib.error.URLError as e:
        print(f"  ERR  {url}  | {e}")
