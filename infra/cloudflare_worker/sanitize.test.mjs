// Zero-dependency test for worker.js's pure sanitize() function, using
// Node's built-in test runner (node --test) — no package.json, no npm
// dependency, no bundler. WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1: the Worker
// itself has no other test setup in this repo; this covers only the
// allowlist/truncation change, not fetch()/env/Workers-runtime behavior.

import assert from "node:assert/strict";
import { test } from "node:test";
import { sanitize, missingContact } from "./worker.js";

// WORKER_CONTACT_REQUIREMENTS_V1: sanitize() now rejects a missing/empty
// email or phone, so BASE carries both — every existing structural test
// below exercises its own concern (allowlist, truncation, trimming …)
// against an otherwise-valid, contact-complete payload.
const BASE = {
  event_date: "2026-09-20",
  guest_count_estimate: 15,
  email: "info@musterfirma.de",
  phone: "0151 2345678",
};

test("website_form fields pass through the allowlist", () => {
  const out = sanitize({
    ...BASE,
    company: "Musterfirma GmbH",
    name: "Frau Muster",
    event_type: "Firmenfeier",
    phone: "0151 2345678",
    email: "info@musterfirma.de",
    message: "Bitte Rückruf.",
    submission_id: "web-42",
  });
  assert.ok(out !== null);
  assert.equal(out.company, "Musterfirma GmbH");
  assert.equal(out.name, "Frau Muster");
  assert.equal(out.event_type, "Firmenfeier");
  assert.equal(out.phone, "0151 2345678");
  assert.equal(out.email, "info@musterfirma.de");
  assert.equal(out.message, "Bitte Rückruf.");
  assert.equal(out.submission_id, "web-42");
});

test("wix_form's original fields still pass through unchanged", () => {
  const out = sanitize({
    ...BASE,
    time_window_text: "abends",
    location_text: "München",
    planning_mode: "caterer_suggestion",
    customer_linkage: { customer_id: "x" },
  });
  assert.ok(out !== null);
  assert.equal(out.time_window_text, "abends");
  assert.equal(out.location_text, "München");
  assert.equal(out.planning_mode, "caterer_suggestion");
  assert.deepEqual(out.customer_linkage, { customer_id: "x" });
});

test("unknown fields are stripped", () => {
  const out = sanitize({
    ...BASE,
    price: 999,
    admin: true,
    __proto__: "ignored",
    order_id: "should-not-pass",
  });
  assert.ok(out !== null);
  assert.equal(out.price, undefined);
  assert.equal(out.admin, undefined);
  assert.equal(out.order_id, undefined);
});

test("short text fields (e.g. company) are capped at 500 chars", () => {
  const out = sanitize({ ...BASE, company: "X".repeat(600) });
  assert.equal(out.company.length, 500);
});

test("message is capped at 5000 chars, not 500", () => {
  const out = sanitize({ ...BASE, message: "Y".repeat(6000) });
  assert.equal(out.message.length, 5000);
});

test("message under 500 chars is untouched (regression guard for the old shared cap)", () => {
  const msg = "A reasonably short but real message. ".repeat(10); // ~380 chars
  const out = sanitize({ ...BASE, message: msg.trim() });
  assert.equal(out.message, msg.trim());
});

test("text fields are trimmed", () => {
  const out = sanitize({ ...BASE, company: "  Musterfirma  ", message: "  Hallo  " });
  assert.equal(out.company, "Musterfirma");
  assert.equal(out.message, "Hallo");
});

test("missing event_date is still rejected", () => {
  assert.equal(sanitize({ guest_count_estimate: 15 }), null);
});

test("invalid event_date format is still rejected", () => {
  assert.equal(sanitize({ event_date: "20.09.2026" }), null);
});

test("guest_count_estimate digit-string coercion still works", () => {
  const out = sanitize({ ...BASE, guest_count_estimate: "15" });
  assert.equal(out.guest_count_estimate, 15);
});

test("non-integer guest_count_estimate is still rejected", () => {
  assert.equal(sanitize({ event_date: "2026-09-20", guest_count_estimate: "abc" }), null);
});

// -- WORKER_CONTACT_REQUIREMENTS_V1: email/phone required -------------------

test("missing email is rejected", () => {
  const { email, ...rest } = BASE;
  assert.equal(sanitize(rest), null);
});

test("empty email is rejected", () => {
  assert.equal(sanitize({ ...BASE, email: "" }), null);
});

test("whitespace-only email is rejected", () => {
  assert.equal(sanitize({ ...BASE, email: "   " }), null);
});

test("missing phone is rejected", () => {
  const { phone, ...rest } = BASE;
  assert.equal(sanitize(rest), null);
});

test("empty phone is rejected", () => {
  assert.equal(sanitize({ ...BASE, phone: "" }), null);
});

test("whitespace-only phone is rejected", () => {
  assert.equal(sanitize({ ...BASE, phone: "   " }), null);
});

test("valid request with both email and phone (trimmed) is accepted", () => {
  const out = sanitize({ ...BASE, email: "  info@musterfirma.de  ", phone: "  0151 2345678  " });
  assert.ok(out !== null);
  assert.equal(out.email, "info@musterfirma.de");
  assert.equal(out.phone, "0151 2345678");
});

test("missingContact: true when raw email is absent, empty, or whitespace-only", () => {
  assert.equal(missingContact({ phone: "0151 2345678" }), true);
  assert.equal(missingContact({ phone: "0151 2345678", email: "" }), true);
  assert.equal(missingContact({ phone: "0151 2345678", email: "   " }), true);
});

test("missingContact: true when raw phone is absent, empty, or whitespace-only", () => {
  assert.equal(missingContact({ email: "info@musterfirma.de" }), true);
  assert.equal(missingContact({ email: "info@musterfirma.de", phone: "" }), true);
  assert.equal(missingContact({ email: "info@musterfirma.de", phone: "   " }), true);
});

test("missingContact: false when both raw email and phone are non-empty", () => {
  assert.equal(
    missingContact({ email: "info@musterfirma.de", phone: "0151 2345678" }),
    false
  );
});
