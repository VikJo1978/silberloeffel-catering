WEBSITE_FORM_INTAKE_IDEMPOTENCY_PACK_V1

0. Purpose

Design-only pack. Closes the gap WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1 §7
deliberately left open: what happens when the Worker (or the future public
site) retries a website_form submission and the same submission_id arrives
twice. No code changes in this pack. Every claim below was checked against
current code on 2026-07-10 (src/catering_system/repositories/
inquiry_repository.py, in_memory_inquiry_repository.py,
sqlite_inquiry_repository.py, sqlite_order_repository.py,
src/catering_system/ui/website_intake_endpoint.py,
src/catering_system/intake/website_form_adapter.py,
tests/unit/test_website_intake_endpoint.py,
WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1.md,
WEBSITE_FORM_INTAKE_TO_INQUIRY_PACK_V1.md,
PROPOSAL_PREVIEW_INTAKE_MAPPING_IMPLEMENTATION_PACK_V1.md).

⸻

1. Current state — evidence base

1.1 InquiryRepository (inquiry_repository.py) exposes exactly four methods:
save, get_by_id, list_all, update. No lookup by any field other than
inquiry_id exists on either implementation (InMemoryInquiryRepository,
SQLiteInquiryRepository) today. A duplicate submission_id cannot currently
be detected anywhere in this chain — website_intake_endpoint.py's do_POST
(0f6e034) calls intake_from_website_form unconditionally on every valid
payload; the adapter itself has no repository read access at all (it only
calls InquiryService.create_inquiry, a write-only call from its point of
view).

1.2 intake_external_ref is not website_form-exclusive. Two separate,
already-accepted mappings write into it: website_form_adapter.py's
submission_id (1baeae3) and the configurator prepare flow's proposal_id
(5d5e007, PROPOSAL_PREVIEW_INTAKE_MAPPING_IMPLEMENTATION_PACK_V1 §4). Any
lookup mechanism this pack designs is therefore a general repository
capability, not a website_form-specific hack — §5 scopes its use narrowly
regardless (only this pack's one call site), but the underlying method is
not invented as a single-purpose bolt-on.

1.3 Decisive finding — the classic check-then-create race condition does
not apply here, structurally, not by policy: website_intake_endpoint.py's
create_website_intake_server (0f6e034) uses HTTPServer, explicitly not
ThreadingHTTPServer, "single-threaded on purpose... the shared sqlite3
connection must stay on the thread that serves requests (bring-up bug,
WORKLOG Entry 048)." One process handles exactly one request at a time —
two near-simultaneous retries cannot both pass a "not found yet" check
before either has saved, because they are never actually concurrent within
one receiver process. The only way to reintroduce the race is running two
receiver processes against the same DB file — already explicitly forbidden
by WEBSITE_INTAKE_RECEIVER_DEPLOYMENT_PACK_V1 §7 ("no reverse proxy or
process manager should ever run multiple instances of this service against
the same DB file concurrently"). This pack does not need to design any
locking, transaction, or unique-constraint mechanism — the existing
single-instance deployment rule already closes that door.

1.4 SQLiteOrderRepository already has a precedent for a dedicated index
(sqlite_order_repository.py: `CREATE INDEX IF NOT EXISTS
idx_order_versions_order_id ON order_versions (order_id, version_number)`)
— confirming an index is an established, accepted pattern in this codebase
if this pack's future implementation wants one, not a new technique.

1.5 worker.js (0f6e034) does not generate or guarantee a submission_id —
it only forwards whatever the caller sent, sanitized. WORKER_TO_CORE_
WEBSITE_INTAKE_PACK_V1 §4 already assigned "generate submission_id" to the
Worker/site layer, not to Core. This pack does not change that assignment;
it only specifies what Core does when a submission_id is present and
repeats, and confirms (§6) what happens when it's absent (unchanged: no
dedup possible, matching already-accepted behavior).

⸻

2. Problem, stated precisely

A Worker retry (network timeout, a 5xx from a transient receiver hiccup, or
a future retry-with-backoff added to worker.js) resends the exact same
sanitized payload, including the same submission_id. Today, that produces a
second Inquiry with the same intake_external_ref, source, and content —
cheap compared to an Order, but real office noise: two rows to review, two
to potentially half-process, a source of confusion during a busy period.
Not dangerous (§3), but worth closing before the receiver goes live.

⸻

3. Boundary (restated for this piece specifically)

	•	Inquiry remains the only object this touches — idempotency here means
		"don't create a second Inquiry," nothing about Order/OrderVersion,
		which this mechanism never touches in the first place
	•	no READY_TO_SEND, no wirksam/effective, no kitchen/kiosk/release
		effect — unaffected by construction, same as every prior pack in
		this chain
	•	no InquiryService method signature change — the new capability is a
		pure repository-layer read, called directly by the receiver (§5),
		never routed through InquiryService
	•	no change to website_form_adapter.py's own contract — it keeps
		creating exactly one Inquiry per call, unconditionally; the decision
		"should I call it at all" moves one layer up, into the receiver
	•	no change to the configurator's own prepare/submit flow (5d5e007) —
		§1.2 notes the underlying field is shared, but this pack's only
		authorized call site is the website intake receiver (§9's open gap
		names the configurator angle explicitly, decides nothing there)
	•	no Worker/worker.js change — submission_id generation stays exactly
		where WORKER_TO_CORE_WEBSITE_INTAKE_PACK_V1 §4 already put it
	•	no new HTTP status code — a retried submission still gets 202,
		matching worker.js's own simple ok/not-ok check (§7)

⸻

4. Design decision — return the existing Inquiry, don't reject, don't
duplicate

Three options exist for what "handling a duplicate" means; one is adopted.

Rejected: reply with an error (409 or similar) on a repeat submission_id.
Wrong shape for this problem — the caller (Worker, ultimately the site) did
nothing wrong by retrying; treating a retry as a client error would make a
transient hiccup on Core's side look like the visitor's fault, and would
give worker.js's simple `upstream.ok` check a reason to report failure to
the public caller for something that, from the visitor's perspective,
already succeeded once.

Rejected: silently create a second Inquiry anyway, only logging a warning.
This is today's actual behavior — the problem this pack exists to fix, not
a real option, listed only for completeness.

Adopted: idempotent replay. On a submission_id match (scoped by
inquiry_source, §5), the receiver does not call the adapter again — it
returns the same 202 response shape as a fresh success, carrying the
already-existing Inquiry's inquiry_id. From the Worker's (and therefore the
site's) point of view, a retry and a first attempt are indistinguishable —
both "succeed." Exactly one Inquiry ever exists per (source, submission_id)
pair.

⸻

5. Repository-layer mechanism

New method on the InquiryRepository protocol (inquiry_repository.py):

	def find_by_source_and_external_ref(
	    self, inquiry_source: str, intake_external_ref: str
	) -> Inquiry | None: ...

Scoped by (inquiry_source, intake_external_ref) together, not
intake_external_ref alone — §1.2's evidence shows two different channels
already write into this field with their own, independently-chosen ID
schemes (a configurator-local counter vs. a website submission UUID);
scoping by source as well removes even the theoretical possibility of an
accidental cross-channel collision being treated as the same idempotency
key.

InMemoryInquiryRepository implementation: a linear scan of self._by_id.values()
filtering on both fields — proportionate to this repository's own existing
list_all()'s own linear-scan-and-sort shape, no new data structure.

SQLiteInquiryRepository implementation: `SELECT * FROM inquiries WHERE
inquiry_source = ? AND intake_external_ref = ? LIMIT 1`. No index is
strictly required for V1 at this table's expected row count (a handful to
low hundreds of Inquiries for a single catering business); §1.4 confirms an
index is available as a follow-up if row counts ever justify it, following
the exact `CREATE INDEX IF NOT EXISTS` pattern SQLiteOrderRepository already
uses — not designed further here, an explicit non-goal (§8).

Empty/None intake_external_ref is never looked up — §6 keeps today's
already-accepted behavior (no submission_id means no dedup, not "dedup
against every other Inquiry that also happens to have no reference").

⸻

6. Receiver-layer behavior

website_intake_endpoint.py's do_POST, after JSON parsing and event_date
conversion, before calling intake_from_website_form: if payload.get(
"submission_id") is a non-empty string, call inquiry_repository.
find_by_source_and_external_ref("website_form", payload["submission_id"]).
If it returns an existing Inquiry, skip the adapter call entirely and
respond 202 with {"accepted": true, "inquiry_id": <existing id>} — the same
shape a fresh success already returns (0f6e034), no new response field
required, though an optional "duplicate": true marker may be added purely
for the receiver's own log correlation (the Worker never reads response
bodies, §1.5/§7 — this is an internal debugging aid only, not
Worker/site-facing signal).

If submission_id is absent, empty, or not a string: no lookup, proceed
exactly as today (the adapter's own existing type-check on submission_id
still applies unchanged — this pack adds a lookup before the adapter runs,
never changes what the adapter itself accepts or rejects).

Logging: on a detected duplicate, log at INFO (not WARNING — a retry
succeeding idempotently is normal, expected operation, not a problem)
"website intake: duplicate submission_id, returning existing inquiry_id=…"
— matching the receiver's own existing "never log the raw payload" rule
(0f6e034); only the resulting inquiry_id is logged, never contact/message
content.

⸻

7. Worker / site interaction

Unchanged. worker.js already treats any upstream 2xx as `upstream.ok` and
replies "accepted"/202 to the public caller either way (0f6e034's own
code) — an idempotent-replay 202 from the receiver requires zero Worker
change to behave correctly. The site's own success message (once it exists,
PUBLIC_SITE §4's "wir rufen Sie zurück" framing) stays identical for a
first submission and a retried one, which is the correct, honest UX: from
the visitor's perspective, their request already succeeded either way.

⸻

8. Non-goals

	•	no code in this pack — repository protocol, both implementations, and
		the receiver stay untouched until a separate implementation step
	•	no SQL index added now (§5 names it as an available, not-yet-needed
		follow-up)
	•	no change to website_form_adapter.py's own contract or validation
	•	no change to worker.js — submission_id generation/guarantee stays
		the Worker/site's job, unchanged from WORKER_TO_CORE_WEBSITE_INTAKE_
		PACK_V1 §4
	•	no wiring of this mechanism into the configurator's prepare/submit
		flow — named as a real, evidence-based possibility (§1.2) but not
		authorized here (§9's open gap)
	•	no locking, transaction, or unique-constraint mechanism — §1.3 shows
		none is needed given the existing single-threaded, single-instance
		deployment constraint
	•	no Order/OrderVersion/READY_TO_SEND/wirksam/kitchen/kiosk change of
		any kind
	•	no Worker/Tunnel/systemd deployment change

⸻

9. Open gaps — not decided here, flagged for the owner

	•	whether the configurator's own prepare/submit flow should eventually
		gain the same dedup mechanism, given proposal_id already lands in
		the same intake_external_ref field (§1.2) — the repository method
		this pack specifies would trivially support it (same method, source
		="configurator" instead), but wiring it in is a separate, small,
		explicitly-scoped future step, not assumed here
	•	whether an index on (inquiry_source, intake_external_ref) is worth
		adding at initial implementation time or only once real row counts
		justify it (§5) — a performance call, not a correctness one, since
		correctness holds either way at this table's realistic V1 size
	•	whether the optional "duplicate": true response marker (§6) is worth
		adding now or is unnecessary until there's an actual operational
		need to distinguish replay-202s from fresh-202s in a log/metrics
		review

⸻

10. Tests for future implementation

Repository-level (tests/unit/test_sqlite_repositories.py and a new
InMemoryInquiryRepository-focused test, following existing patterns):

	•	find_by_source_and_external_ref returns None when no Inquiry has a
		matching (source, ref) pair
	•	returns the correct Inquiry when exactly one match exists
	•	does not match across different inquiry_source values sharing the
		same intake_external_ref value (the cross-channel collision guard,
		§5)
	•	does not match when intake_external_ref is None/empty on stored rows
	•	SQLite and in-memory implementations agree on all of the above (same
		shape as this project's existing dual-implementation test coverage
		elsewhere)

Receiver-level (tests/unit/test_website_intake_endpoint.py, extending its
existing live-socket pattern):

	•	a first POST with a given submission_id creates one Inquiry, 202
	•	an identical second POST with the same submission_id (and same
		inquiry_source, implicitly always "website_form" from this
		receiver) does not create a second Inquiry — repository count stays
		at exactly one
	•	the second POST still returns 202 with the same inquiry_id as the
		first response
	•	a POST with a different submission_id (or none at all) after an
		earlier one creates a genuinely new, second Inquiry — proving the
		mechanism doesn't over-match
	•	two POSTs with no submission_id at all both create separate
		Inquiries (today's existing, unchanged behavior for the no-dedup
		case)
	•	no Order/OrderVersion is created in any of the above — same
		structural assertion this test file already uses throughout
	•	log output for the duplicate case never contains the request's
		phone/email/message content — same "no sensitive echo" discipline
		this file already enforces for the non-duplicate path

⸻

11. Acceptance criteria for the future implementation step

	•	InquiryRepository protocol gains find_by_source_and_external_ref;
		both implementations satisfy it
	•	website_intake_endpoint.py checks it before calling the adapter,
		only when submission_id is a non-empty string
	•	a retried submission never creates a second Inquiry
	•	a retried submission's response is indistinguishable in shape from a
		fresh success (same 202, same {"accepted": true, "inquiry_id": …})
	•	full existing suite stays green; new tests follow §10
	•	no domain field added or changed
	•	no InquiryService method added or changed
	•	no website_form_adapter.py behavior change
	•	no worker.js change
	•	no Office Panel change (the resulting Inquiry, duplicate-prevented or
		not, renders through the existing, unmodified WEBSITE_FORM_INQUIRY_
		OFFICE_UX_PACK_V1 rendering — nothing new to display)

⸻

12. Exit

Complete when this document is reviewed and frozen as accepted design, with
zero code changes in this repo. Implementation (the repository method, both
its implementations, and the receiver's one new check) is a separate future
step, needing its own GO and diff review, per this project's standing
discipline. The configurator-side wiring question (§9) needs its own,
separate decision if the owner ever wants it.
