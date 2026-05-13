"""Phase 1 verifications 1, 3 — probe the claude.ai usage endpoint and JWT shape.

Reads ~/.claude/.credentials.json. Never prints the access/refresh tokens.
Prints: JWT header claims, JWT payload claims (with anything *_token / *_key
redacted), HTTP status, response headers (cookies redacted), body.

Run with: python3 tests/manual/probe_usage_endpoint.py
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

CREDS = Path.home() / ".claude" / ".credentials.json"
SECRET_LIKE = re.compile(r"(token|key|secret|cookie|sessionKey)", re.I)


def b64url_decode(s: str) -> bytes:
    s += "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s)


def decode_jwt(token: str) -> tuple[dict, dict]:
    parts = token.split(".")
    if len(parts) != 3:
        return {"_not_a_jwt": True, "prefix": token[:14]}, {}
    header = json.loads(b64url_decode(parts[0]))
    payload = json.loads(b64url_decode(parts[1]))
    return header, payload


def redact(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if SECRET_LIKE.search(k):
            out[k] = f"<redacted len={len(str(v))}>"
        elif isinstance(v, str) and len(v) > 80 and any(p in v for p in ("eyJ", "sk-ant-")):
            out[k] = f"<redacted-token len={len(v)}>"
        else:
            out[k] = v
    return out


def main() -> int:
    if not CREDS.exists():
        print(f"NO CREDS at {CREDS}", file=sys.stderr)
        return 2

    raw = json.loads(CREDS.read_text())
    print("=== credentials.json structure ===")
    print(json.dumps({k: list(v) if isinstance(v, dict) else type(v).__name__
                       for k, v in raw.items()}, indent=2))

    oauth = raw.get("claudeAiOauth", {})
    access = oauth.get("accessToken", "")
    refresh = oauth.get("refreshToken", "")
    print("\naccessToken prefix:", access[:14], "len:", len(access))
    print("refreshToken prefix:", refresh[:14], "len:", len(refresh))
    print("expiresAt:", oauth.get("expiresAt"))
    print("scopes:", oauth.get("scopes"))
    print("subscriptionType:", oauth.get("subscriptionType"))

    print("\n=== JWT claims (accessToken) ===")
    if access.count(".") == 2:
        header, payload = decode_jwt(access)
        print("header:", json.dumps(header, indent=2))
        print("payload:", json.dumps(redact(payload), indent=2, default=str))
        org_id = payload.get("org_id") or payload.get("organization_id") or payload.get("oid")
    else:
        # sk-ant-oat01-...; opaque, not JWT
        print("accessToken is not a JWT (opaque token).")
        org_id = None

    print("\norg_id from JWT:", org_id)

    # Verification 1: try Bearer OAuth against claude.ai usage endpoint with placeholder org id
    print("\n=== verification 1: Bearer OAuth vs claude.ai/api/organizations/{org}/usage ===")
    test_org = org_id or "00000000-0000-0000-0000-000000000000"
    url = f"https://claude.ai/api/organizations/{test_org}/usage"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {access}",
            "User-Agent": "cc-usage-probe/0.1 (Phase 1 empirical)",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print("status:", resp.status)
            print("headers:", json.dumps(
                {k: ("<set-cookie redacted>" if k.lower() == "set-cookie" else v)
                 for k, v in resp.headers.items()}, indent=2))
            body = resp.read().decode("utf-8", errors="replace")
            print("body[:2000]:", body[:2000])
    except urllib.error.HTTPError as e:
        print("HTTPError status:", e.code)
        print("headers:", json.dumps(
            {k: ("<set-cookie redacted>" if k.lower() == "set-cookie" else v)
             for k, v in e.headers.items()}, indent=2))
        body = e.read().decode("utf-8", errors="replace")
        print("body[:2000]:", body[:2000])
    except urllib.error.URLError as e:
        print("URLError:", e)

    # Verification 3 fallback: bootstrap endpoint discovery if no org_id in JWT
    if not org_id:
        print("\n=== verification 3: org-id discovery ===")
        for path in ("/api/bootstrap", "/api/organizations", "/api/account"):
            print(f"\n--- {path} ---")
            req = urllib.request.Request(
                f"https://claude.ai{path}",
                headers={
                    "Authorization": f"Bearer {access}",
                    "User-Agent": "cc-usage-probe/0.1",
                    "Accept": "application/json",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    print("status:", resp.status)
                    body = resp.read().decode("utf-8", errors="replace")
                    print("body[:1500]:", body[:1500])
            except urllib.error.HTTPError as e:
                print("HTTPError:", e.code, "body:", e.read()[:500].decode(errors="replace"))
            except urllib.error.URLError as e:
                print("URLError:", e)

    return 0


if __name__ == "__main__":
    sys.exit(main())
