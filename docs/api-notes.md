# API Notes — Phase 1 empirical findings

> Captured 2026-05-08 against a live `Claude Max` account.
> Endpoints are undocumented and unsupported — Anthropic can change them at any time.
> Probe scripts under `tests/manual/` (gitignored).

## TL;DR — recommended endpoint and auth

```
GET https://api.anthropic.com/api/oauth/usage
Authorization: Bearer sk-ant-oat01-...
```

- **Works** with the OAuth `accessToken` from `~/.claude/.credentials.json`.
- **No org_id in URL.** The token implicitly identifies the account/org.
- Returns the same data shown on `claude.ai/settings/usage`.
- Mirror endpoint exists at `https://claude.ai/api/oauth/usage` with identical behavior.

## Response shape

Top-level keys observed:

```
five_hour, seven_day, seven_day_opus, seven_day_sonnet,
seven_day_oauth_apps, seven_day_cowork, seven_day_omelette,
tangelo, iguana_necktie, omelette_promotional, extra_usage
```

Each rate-limit bucket is one of:
- `null` (bucket inactive for this account/plan), OR
- `{"utilization": <float 0..100>, "resets_at": "<ISO8601 UTC>"}`

`extra_usage` is `{"is_enabled": false, "monthly_limit": null, ...}` — separate object.

> ⚠ The field is `utilization`, **not** `utilization_pct`. Other docs in the wild
> get this wrong. The value is already a percentage (0..100), not a fraction.

Buckets to surface in the indicator:
- **`five_hour`** — the active session window. Always present.
- **`seven_day`** — the rolling weekly cap. Always present.
- **`seven_day_opus`** — only when the account uses Opus and the bucket is non-null.
- (Opt-in/advanced) `seven_day_sonnet`, `seven_day_oauth_apps`, others.

## What does NOT work

- `GET https://claude.ai/api/organizations/{orgId}/usage` with **OAuth Bearer** → `403 account_session_invalid`. (This endpoint exists but requires the **`sessionKey` cookie** auth, not OAuth tokens.)
- `GET https://api.anthropic.com/api/account` with OAuth Bearer → `403 account_session_invalid`.
- `GET https://claude.ai/api/account` with OAuth Bearer → `403 account_session_invalid`.

So the OAuth Bearer namespace is narrow: only `/api/oauth/*` endpoints accept OAuth tokens directly. The web-app `/api/organizations/...` namespace only accepts sessionKey cookies.

## Org-id discovery (no longer needed for usage, but useful)

```
GET https://api.anthropic.com/api/oauth/profile
Authorization: Bearer sk-ant-oat01-...
→ 200
{
  "account": {"uuid": "...", "full_name": "...", "email": "...",
              "has_claude_max": true, "has_claude_pro": false, "created_at": "..."},
  "organization": {"uuid": "...", "name": "...", "organization_type": "claude_max",
                   "billing_type": "stripe_subscription",
                   "rate_limit_tier": "default_claude_max_5x",
                   "subscription_status": "active", ...}
}
```

The `accessToken` (`sk-ant-oat01-...`) is **opaque, not a JWT**, so we can't decode claims from it locally. If we need org_id we go through `/api/oauth/profile`.

We display `organization.name` (or `account.email` as fallback) in the menu's "About" / status area — purely cosmetic.

## OAuth refresh endpoint (unverified — not exercised to avoid burning the token)

Confirmed-existing endpoints (HEAD returns 405 "method not allowed" — path exists; empty POST returns 400 "Invalid JSON body" — endpoint accepts JSON):

- `https://console.anthropic.com/v1/oauth/token` ← most likely (Claude Code uses this)
- `https://api.anthropic.com/v1/oauth/token`
- `https://claude.ai/v1/oauth/token`

Confirmed **not** existing:
- `https://api.anthropic.com/api/oauth/token` → 404
- `https://claude.ai/api/oauth/token` → 404

Expected request shape (OAuth 2.0 RFC 6749 § 6, JSON variant Anthropic uses elsewhere):
```
POST https://console.anthropic.com/v1/oauth/token
Content-Type: application/json

{
  "grant_type": "refresh_token",
  "refresh_token": "sk-ant-ort01-...",
  "client_id": "<TBD — Claude Code's constant; must be discovered>"
}
```

**Open question for Phase 3**: the `client_id` constant. Claude Code passes one when refreshing; without it we may get `invalid_client`. To discover:
- (a) Inspect Claude Code with mitmproxy during a forced refresh.
- (b) Check public Claude Code source / OAuth metadata at well-known URLs (`/.well-known/oauth-authorization-server`).
- (c) Try without it first — some Anthropic OAuth clients accept `null`/missing `client_id` for refresh.

If refresh fails, the user simply re-runs `claude` (which performs its own refresh) and we re-read the file. This is the documented escape hatch.

## Rate limiting

- `GET /api/oauth/usage` is **rate-limited**. Three calls in ~30s already returned `429 rate_limit_error` during probing.
- Default poll interval should be **≥ 5 minutes**. Add explicit 429 backoff (double interval to a 30-min cap).
- The `seven_day` reset window is 7 days, so even a 30-min cadence is overkill for that bucket. The 5-hour bucket benefits from ≤ 5min cadence near the limit.

## Token expiry

The `expiresAt` field in `.credentials.json` is **milliseconds since epoch** (note: ms, not seconds). E.g. `1778274039475` → `2026-05-09T08:20:39Z`. Token TTL appears to be ~24h.

## Cookies / Set-Cookie

`/api/oauth/usage` does **NOT** issue Set-Cookie. It is purely Bearer-token authenticated. So the "cookie rotation" pattern from the original plan is **not applicable** to the OAuth path — only relevant if we keep a sessionKey fallback against `/api/organizations/{org}/usage`.

## Architectural impact on the plan

Compared to the original plan:

| Aspect | Original plan | Reality |
|---|---|---|
| Endpoint | `claude.ai/api/organizations/{orgId}/usage` | `api.anthropic.com/api/oauth/usage` (no org in URL) |
| Org-id discovery | JWT decode or bootstrap fallback | Not needed for usage; `/api/oauth/profile` if wanted |
| Auth (primary) | OAuth Bearer | OAuth Bearer (works, this part was right) |
| Auth (fallback) | sessionKey cookie | sessionKey would target the **other** endpoint and require org_id discovery |
| Cookie rotation | Important for sessionKey | Only relevant if we keep the sessionKey fallback |
| Field name | `utilization_pct` | `utilization` |

**Recommendation**: drop the sessionKey fallback for v1. The OAuth path is cleaner, doesn't require manual paste, and the sessionKey path would now require parallel implementation of a *different* endpoint with org_id discovery, cookie rotation, and a separate response parser. Reintroduce sessionKey only if a real user needs it.
