"""Phase 1 verifications 2 and 4 — OAuth refresh endpoint + full response shape.

Captures the full /api/oauth/usage response, then probes plausible
OAuth refresh endpoints to find which one actually rotates the token.

REFRESH SAFETY: refresh attempts here use the *real* refresh_token.
If a candidate succeeds we get a new access/refresh pair which would
*invalidate* Claude Code's existing tokens and require Claude Code to
re-do the dance. So we deliberately STOP at the first success and
print only token prefixes, NOT the new tokens. The user can re-run
`claude` to refresh fresh.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CREDS = Path.home() / ".claude" / ".credentials.json"
oauth = json.loads(CREDS.read_text())["claudeAiOauth"]
ACCESS = oauth["accessToken"]
REFRESH = oauth["refreshToken"]


def get(url: str, headers: dict) -> tuple[int, dict, str]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read().decode(errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode(errors="replace")


# ---- Verification 4: full usage response shape + Set-Cookie behavior ----
print("=== full /api/oauth/usage response ===")
status, headers, body = get(
    "https://api.anthropic.com/api/oauth/usage",
    {"Authorization": f"Bearer {ACCESS}", "Accept": "application/json",
     "User-Agent": "cc-usage-probe/0.1"},
)
print("status:", status)
print("Set-Cookie present:", "set-cookie" in {k.lower() for k in headers})
data = json.loads(body)
print("top-level keys:", sorted(data.keys()))
print("\nfull body:")
print(json.dumps(data, indent=2))

# ---- Verification 2: OAuth refresh endpoint discovery ----
print("\n\n=== OAuth refresh endpoint hunt (HEAD-only / OPTIONS) ===")
# We don't want to actually execute a refresh and burn the token.
# Use OPTIONS / HEAD to detect endpoint existence without state change.
candidates = [
    "https://console.anthropic.com/v1/oauth/token",
    "https://api.anthropic.com/v1/oauth/token",
    "https://api.anthropic.com/api/oauth/token",
    "https://claude.ai/api/oauth/token",
    "https://claude.ai/v1/oauth/token",
    "https://login.anthropic.com/oauth/token",
    "https://auth.anthropic.com/oauth/token",
]
for url in candidates:
    # Try HEAD first; many APIs respond to HEAD with 405 Method Not Allowed
    # which is itself a signal the path exists.
    req = urllib.request.Request(url, method="HEAD",
                                  headers={"User-Agent": "cc-usage-probe/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            print(f"  HEAD {r.status}  {url}")
    except urllib.error.HTTPError as e:
        # 405 (method not allowed) or 400 with hints both indicate the path exists
        kind = "EXISTS" if e.code in (400, 401, 405, 415, 422) else "absent"
        print(f"  HEAD {e.code} [{kind}]  {url}")
    except urllib.error.URLError as ue:
        print(f"  HEAD ERR  {url}  | {ue}")

# Now an OPTIONS to the most-likely candidate
print("\n=== OPTIONS probe to top candidates ===")
for url in [
    "https://console.anthropic.com/v1/oauth/token",
    "https://api.anthropic.com/v1/oauth/token",
    "https://api.anthropic.com/api/oauth/token",
]:
    req = urllib.request.Request(url, method="OPTIONS",
                                  headers={"User-Agent": "cc-usage-probe/0.1",
                                           "Origin": "https://claude.ai",
                                           "Access-Control-Request-Method": "POST"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            print(f"  OPTIONS {r.status}  {url}")
            print("    Allow:", r.headers.get("Allow"))
            print("    AC-Allow-Methods:", r.headers.get("Access-Control-Allow-Methods"))
    except urllib.error.HTTPError as e:
        print(f"  OPTIONS {e.code}  {url}")
        for h in ("Allow", "Access-Control-Allow-Methods"):
            print(f"    {h}:", e.headers.get(h))

# Send an empty POST (no body) — server should respond with 400 telling us
# what's missing if the endpoint exists. This does NOT execute a refresh.
print("\n=== empty POST probe (we send NO refresh_token) ===")
for url in [
    "https://console.anthropic.com/v1/oauth/token",
    "https://api.anthropic.com/v1/oauth/token",
    "https://api.anthropic.com/api/oauth/token",
    "https://claude.ai/api/oauth/token",
]:
    req = urllib.request.Request(url, method="POST", data=b"",
                                  headers={"User-Agent": "cc-usage-probe/0.1",
                                           "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            print(f"  POST {r.status}  {url}  body[:200]: {r.read()[:200]!r}")
    except urllib.error.HTTPError as e:
        body = e.read()[:300].decode(errors="replace")
        print(f"  POST {e.code}  {url}\n    body: {body}")
