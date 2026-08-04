# Employee session introspection (AUTH-2E1)

Private Core Office API contract for trusted backend callers (Configurator BFF
in AUTH-2E2). Not for browser use.

## Endpoint

```http
POST /office/v1/auth/employee/introspect
```

## Service authentication

Required on every request:

```http
Authorization: Bearer <service-token>
```

Tokens are configured server-side only:

- `OFFICE_API_TOKEN` — existing office-panel bearer; **not** authorized for this
  route (`403 forbidden`).
- `EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON` — JSON object mapping trusted
  service client ids to bearer secrets, for example:

```json
{"configurator": "<long-random-secret>"}
```

Rules:

- missing / invalid bearer → `401 {"error":"unauthorized"}` even when the request
  body or `X-Employee-Session` would otherwise be invalid
- valid office-panel bearer → `403 {"error":"forbidden"}`
- ambiguous bearer identity → `403 {"error":"forbidden"}`
- valid configurator bearer → allowed, then request validation runs
- secrets compared with constant-time `hmac.compare_digest`
- never log bearer values

## Employee session input

```http
X-Employee-Session: <opaque session token>
```

Rules:

- header absent or blank → `200`, `authenticated=false`
- malformed or longer than 256 characters → `400 {"error":"invalid_request"}`
- valid token → resolved through existing `EmployeeAuthService` session validation
- the endpoint does **not** read browser `Cookie` headers
- request body must be empty (non-zero body → `400`)

## Response

Always `200` after successful service authentication (except header/body
validation errors):

Authenticated with application access:

```json
{
  "authenticated": true,
  "application_access_allowed": true,
  "principal": {
    "account_id": "...",
    "username": "...",
    "display_name": "...",
    "role": "SUPERADMIN",
    "effective_permissions": ["..."]
  }
}
```

Missing/invalid session:

```json
{
  "authenticated": false,
  "application_access_allowed": false,
  "principal": null
}
```

`must_change_password` sessions return `authenticated=true`,
`application_access_allowed=false`, and an empty permission list on `principal`.

Never returned: raw session token, token hash, password hash, session repository
id, CSRF token, email, or detailed auth-failure reasons.

Permissions are sorted lexicographically.

## Trust boundary

- Server-to-server only over trusted network (Tailscale / loopback).
- No CORS, no browser exposure, no CSRF (opaque session arrives only from an
  authenticated service caller).
- No security audit row per introspection (operational log only: service client
  id, booleans, account id on success).
- Read-only: no session touch, no expiry extension, no business mutations.

## Credential redaction

Do not log `Authorization`, `X-Employee-Session`, `Cookie`, or full principal
payloads.

## Caching

AUTH-2E1 defines no server-side cache. Callers may use a short-lived cache in
AUTH-2E2; invalidate on logout/password change via conservative TTL until
`auth_version` is exposed.

## Deferred work

- **AUTH-2E2** — Configurator BFF integration
- **AUTH-2E3** — signed handoff ticket for inquiry/offer operation binding

## Production activation

1. Add `EMPLOYEE_INTROSPECTION_SERVICE_TOKENS_JSON` to `/etc/catering/office-api.env`
   (mode `600`).
2. Deploy Core with this endpoint.
3. Configure the same secret on the Configurator backend (AUTH-2E2).
4. Restrict `:8084` to trusted backends only (existing Tailscale bind).

## Rollback

Stop Configurator from calling the route. The endpoint remains dormant until a
caller uses it; removing the env JSON disables configurator authorization while
keeping office-panel API behavior unchanged.
