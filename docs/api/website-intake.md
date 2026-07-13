# Website intake API

This document separates the temporary staging API from the future production
website path. They accept similar business fields but have different trust and
persistence boundaries.

## Production flow

```text
browser → Cloudflare Worker → token-authenticated Lenovo receiver → Core Inquiry
```

The browser must never receive the Lenovo bearer token or call the receiver
directly.

## Public Worker contract

The Worker accepts `POST` JSON only. It removes unknown keys, trims text, checks
the required date format, normalizes a numeric guest-count string, and forwards
the clean payload with a server-side bearer token.

### Fields

| Field | Type | Required | Limit/meaning |
|---|---|---:|---|
| `event_date` | string | yes | ISO `YYYY-MM-DD` |
| `time_window_text` | string | no | 500 characters |
| `location_text` | string | no | 500 characters |
| `guest_count_estimate` | integer or digit string | no | Core accepts 1–2000 |
| `company` | string | no | 500 characters |
| `name` | string | no | 500 characters |
| `event_type` | string | no | 500 characters |
| `phone` | string | no | 500 characters |
| `email` | string | no | 500 characters |
| `message` | string | no | 5000 characters |
| `submission_id` | string | strongly recommended | idempotency key; Core uses at most 200 characters |

Legacy `planning_mode` and `customer_linkage` remain allowlisted for Wix
compatibility but are not trusted as public order truth by the website-form
adapter.

Maximum public request body: **16 KiB**.

### Example request

```json
{
  "event_date": "2027-03-14",
  "time_window_text": "18:00–23:00",
  "location_text": "Hamburg",
  "guest_count_estimate": 80,
  "company": "Beispiel GmbH",
  "name": "Erika Beispiel",
  "email": "erika@example.test",
  "event_type": "Business Event",
  "message": "Vegetarische Optionen gewünscht.",
  "submission_id": "web-01J..."
}
```

Use `.test` addresses and invented information outside production.

### Worker responses

| Status | Meaning |
|---:|---|
| `202` | upstream accepted the request |
| `400` | invalid JSON |
| `405` | method is not POST |
| `413` | request exceeds 16 KiB |
| `422` | invalid public payload |
| `502` | upstream unavailable or rejected request |

The Worker deliberately does not relay upstream response bodies or headers.

## Lenovo receiver contract

Internal URL:

```text
POST http://127.0.0.1:8083/intake/website-form
```

Required headers:

```http
Authorization: Bearer <WEBSITE_INTAKE_TOKEN>
Content-Type: application/json
```

Maximum receiver body: **32 KiB**. Only this route and method are supported.

Successful response:

```json
{
  "accepted": true,
  "inquiry_id": "<uuid>"
}
```

Status codes:

| Status | Meaning |
|---:|---|
| `202` | Inquiry created or idempotent retry resolved |
| `400` | invalid JSON or Core payload |
| `401` | missing or incorrect bearer token |
| `405` | wrong method |
| `413` | body too large |
| `415` | wrong content type |
| `500` | internal duplicate resolution failure |

### Idempotency

`submission_id` becomes the external reference for source `website_form`.
Repeating the same non-empty ID returns the existing `inquiry_id`; a database
unique constraint protects concurrent retries. Generate one stable ID when the
browser submission starts and reuse it for retries.

## Mapping into Inquiry

| Public information | Inquiry field |
|---|---|
| company/name + event type | `intake_subject` |
| company, name, event type, phone, email, message | labelled lines in `intake_message` |
| guest count + date | generated `intake_summary` |
| submission ID | `intake_external_ref` |
| channel | `inquiry_source = website_form` |
| verification | required, status `pending` by default |

Public contact fields are not invented as structured customer linkage. They
remain intake context until office verification.

Keeping both company and name in the labelled context is intentional: the
short subject prefers the company, while the office offer-prefill handoff still
needs the contact person's name.

## Staging form API

Endpoint:

```text
POST http://185.16.60.69:8080/api/inquiries
```

This endpoint has no browser authentication and no TLS. It always validates
against the public-form limits and stores an audit copy in
`/var/lib/catering-staging/staging.db` after acceptance. In isolated mode it
stops there. When the paired server-side `STAGING_CORE_INTAKE_URL` and
`STAGING_CORE_INTAKE_TOKEN` are configured, it first forwards through the
normal Lenovo receiver over the loopback-only reverse SSH tunnel.

Additional rules:

- at least `name` and one of `email`/`phone`;
- guest count 1–2000;
- 16 KiB body;
- hidden honeypot field;
- eight submissions per source IP per minute;
- browser-generated retry key becomes a `vps-staging-…` external reference;
- browser checks the required contact pair before sending and keeps all entered
  values plus the same retry key after network, timeout, or upstream failure;
- browser requests time out after 12 seconds and show stable German messages
  instead of proxy/JSON parser details;
- isolated success is `201`; Core-forwarded success is `202`;
- upstream failure is a generic `502` and is not stored as a local success.

The bearer and upstream URL never reach browser JavaScript. The forwarder
refuses redirects and non-loopback URLs and accepts only the receiver's strict
`202` JSON acknowledgement. This remains a fake-data test channel until HTTPS
and privacy requirements are complete.

## Secret rotation

Rotate `UPSTREAM_TOKEN` in Cloudflare and `WEBSITE_INTAKE_TOKEN` on Lenovo as
one coordinated change:

1. generate a new strong random value outside the repository;
2. update `/etc/catering/website-intake.env` on Lenovo;
3. update the Worker secret;
4. restart the Lenovo receiver;
5. send one controlled test request;
6. confirm the request appears once in the office panel.

Never include the value in shell history, screenshots, or documentation.
