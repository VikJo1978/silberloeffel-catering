# Inquiry to offer prefill V1

Status: accepted for implementation on 2026-07-13 following the owner's request
that website inquiry data should open directly in the office offer form.

## Purpose

Add one explicit office action, **Angebot vorbereiten**, on an Inquiry. It opens
the separate `fingerfood-app` configurator with the known inquiry values already
filled in. The office still reviews and edits every value before saving an offer
draft.

## Boundary

- Core remains the source of Inquiry facts and does not gain prices, catalog
  lines, offer drafts, or an offer status.
- The configurator receives a copy for prefill only. It never writes back to
  Core through this handoff.
- Opening the handoff creates no Order, OrderVersion, draft, PDF, message, or
  customer notification.
- Existing verification and operational release gates are unchanged.

## Transport

The office panel builds a versioned JSON envelope and base64url-encodes it into
the configurator URL fragment:

```text
http://configurator/#core-inquiry=<base64url JSON>
```

URL fragments are not sent in HTTP requests. The configurator validates the
envelope, removes the fragment from the address bar immediately, and then
prefills its in-memory offer draft. The configured base URL must be HTTP(S),
must not contain credentials, a query, or an existing fragment.

The handoff is dormant unless `CONFIGURATOR_URL` is set for the office panel.

## Mapped data

- event date, time window, location and estimated guest count;
- company, contact name, email, phone and event type when the website adapter
  supplied their labelled intake values;
- remaining subject, wishes and summary as editable inquiry context;
- Core Inquiry ID as traceability metadata.

Unknown guest count stays unknown in the transfer and does not overwrite the
configurator's existing editable default.

## Public intake preservation

Future website Inquiries retain labelled `Firma`, `Name`, `Veranstaltungsart`,
`Telefon`, `E-Mail`, and `Wunsch` lines in intake context. This fixes the current
loss of the contact name when a company is also present, without inventing
structured customer linkage or changing the Inquiry schema.

## Safety and acceptance

- strict schema/version/type/length checks on the configurator side;
- malformed or oversized fragments are discarded and cleared without partial
  application;
- imported data is visibly labelled as a Core prefill that still requires
  office review;
- tests prove no Order/Core write, no fragment retention, correct escaping,
  missing-count behavior, and round-trip handling of non-ASCII German text;
- both repositories must pass their existing lint, type-check, test and build
  gates before publication.
