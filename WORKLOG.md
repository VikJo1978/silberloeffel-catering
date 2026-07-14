# Legacy chronological worklog

> **Status:** historical execution record. It is preserved for context but is
> no longer the current project status page. Use
> [`docs/current-status.md`](docs/current-status.md) for live facts,
> [`CHANGELOG.md`](CHANGELOG.md) for releases, and
> [`docs/README.md`](docs/README.md) for maintained documentation. New entries
> should be added here only when chronological implementation archaeology is
> genuinely useful.

WORKLOG.md

0. Purpose

This file is the chronological work log for Catering System MVP.

Its purpose is:
	•	to preserve execution history
	•	to record accepted architecture and execution milestones
	•	to track implementation progress without losing frozen boundaries
	•	to support continuation by a new chat, architect, or developer
	•	to separate accepted work from open work

This file is operational and chronological.
It is not a redesign document.

⸻

1. Logging rules

Each entry should record:
	•	date
	•	scope
	•	what was completed
	•	what was accepted
	•	what remains open
	•	what must not be changed

Entries must not:
	•	silently override frozen contracts
	•	hide redesign proposals inside status notes
	•	present unfinished work as accepted
	•	mix speculation with accepted implementation facts

⸻

2. Status vocabulary

Use the following wording consistently:
	•	accepted — reviewed and accepted against frozen contract/package
	•	prepared — documented and ready for execution, but not yet implemented
	•	in progress — implementation is currently active
	•	blocked — cannot proceed due to explicit blocker
	•	not started — no confirmed implementation work yet
	•	deferred — intentionally outside current slice/scope

⸻

3. Worklog entries

Entry 001

Date: architecture phase complete
Scope: Frozen architecture package baseline

Completed
	•	normalized state model completed
	•	normalized command/event contract completed
	•	normalized entity/field contract completed
	•	implementation slice plan completed
	•	print/document contract completed
	•	UI/screen contract completed
	•	error/attention handling contract completed
	•	test/acceptance matrix completed
	•	master architecture index completed
	•	folder/file handoff structure completed

Accepted
	•	STATE_MODEL_V2
	•	COMMANDS_AND_EVENTS_V1
	•	ENTITY_AND_FIELD_CONTRACTS_V1
	•	IMPLEMENTATION_SLICES_V1
	•	PRINT_AND_DOCUMENT_CONTRACTS_V1
	•	UI_AND_SCREEN_CONTRACTS_V1
	•	ERROR_AND_ATTENTION_HANDLING_V1
	•	TEST_AND_ACCEPTANCE_MATRIX_V1
	•	MASTER_ARCHITECTURE_INDEX_V1
	•	FOLDER_AND_FILE_HANDOFF_STRUCTURE_V1

Open
	•	real implementation not yet confirmed
	•	no slice implementation accepted yet

Must not be changed
	•	Core as single source of truth
	•	mandatory kitchen print as minimal acceptance gate
	•	effective-switch invariant
	•	READY_TO_SEND blocked release semantics
	•	derived-only role of Wochenübersicht
	•	read-only MVP role of kitchen kiosk

⸻

Entry 002

Date: execution-planning phase complete
Scope: Handoff and execution preparation baseline

Completed
	•	README_START_HERE.md completed
	•	CURRENT_STATUS.md completed
	•	NEXT_STEP.md completed

Accepted
	•	README_START_HERE.md
	•	CURRENT_STATUS.md
	•	NEXT_STEP.md

Open
	•	WORKLOG.md initialization
	•	real Slice A implementation not yet confirmed

Must not be changed
	•	recommended reading order
	•	Slice A as first execution target
	•	no redesign during normal implementation

⸻

Entry 003

Date: slice execution-pack baseline complete
Scope: Slice execution packs A–H

Completed
	•	Slice A execution pack completed
	•	Slice B execution pack completed
	•	Slice C execution pack completed
	•	Slice D execution pack completed
	•	Slice E execution pack completed
	•	Slice F execution pack completed
	•	Slice G execution pack completed
	•	Slice H execution pack completed

Accepted
	•	SLICE_A_EXECUTION_PACK_V1
	•	SLICE_B_EXECUTION_PACK_V1
	•	SLICE_C_EXECUTION_PACK_V1
	•	SLICE_D_EXECUTION_PACK_V1
	•	SLICE_E_EXECUTION_PACK_V1
	•	SLICE_F_EXECUTION_PACK_V1
	•	SLICE_G_EXECUTION_PACK_V1
	•	SLICE_H_EXECUTION_PACK_V1

Open
	•	no slice implementation confirmed yet
	•	no acceptance execution log confirmed yet

Must not be changed
	•	Slice order A → H
	•	slice boundaries
	•	no spillover between slices under “convenience” arguments

⸻

Entry 004

Date: current operational status snapshot
Scope: Immediate next execution step

Completed
	•	current status documented
	•	next step documented as Slice A implementation start

Accepted
	•	current recommended next step = Slice A

Open
	•	actual Slice A implementation
	•	actual acceptance validation against TEST_AND_ACCEPTANCE_MATRIX_V1
	•	actual codebase/file status reconciliation

Must not be changed
	•	Slice A remains intake-only baseline
	•	no hidden move into Slice B or later behavior

⸻

4. Current active position (updated 2026-07-05 night; see Entries 036–050)

Current phase
	•	Lenovo bring-up COMPLETE (Entries 048–050): live end-to-end loop verified, systemd autostart reboot-proven, backups active
	•	working internal operational MVP: Core + office panel + kiosk on the kitchen Lenovo over Tailscale
	•	accepted planning-only: PUBLIC_SITE (Entry 044)

Current next step
	•	1–2 days of real office use; frictions collected as plain notes, no code changes except real blockers (Entry 050)
	•	after the window: reconcile frictions into narrow accepted steps; then EspoCRM on the office server

Current main risk
	•	frictions of real use bypassing the pack discipline ("quick fix" temptation during the observation window)
	•	single office/kitchen dependence on one Lenovo disk — backups are the only safety net

⸻

5. Next log entry rule

The next entry should only be added when one of the following happens:
	•	bring-up starts, partially completes, or is accepted
	•	a PUBLIC_SITE implementation step starts (website source / notes_text as own accepted steps)
	•	a concrete blocker appears
	•	actual codebase state is reconciled against accepted documents

⸻

6. Minimal continuation rule

Any new person/session continuing from this log should:
	1.	read this WORKLOG.md top to bottom (sections 4 and 7 are the live position)
	2.	read SLICE_A_EXECUTION_PACK_V1.md and SLICE_A_CLOSEOUT.md for the intake layer
	3.	read OPERATIONAL_CORE_EXECUTION_PACK_V1.md for the current execution target
	4.	update this log only with explicit, truthful status changes

Note: README_START_HERE.md, CURRENT_STATUS.md, NEXT_STEP.md, and the ten
architecture documents named in Entries 001–003 (STATE_MODEL_V2 etc.) do not
exist in this repository or its git history. They are binding as labels only;
where their content is needed, repo evidence and accepted WORKLOG entries win
(see OPERATIONAL_CORE_EXECUTION_PACK_V1 §2 precedence rule).

⸻

7. Current summary (updated 2026-07-05 night)

Slice A (intake): accepted and closed
Slice B read-side (B1–B27): accepted (B16/B17 removed, Entry 039)
Operational core incl. Storno: implemented, tested, live on the Lenovo
Persistence: SQLite behind the repository Protocols; daily backups with cleanup
UI: kitchen kiosk (read-only, :8082) + office panel (write, :8081) — systemd, reboot-proven
Integration: HubSpot client (unwired artifact; EspoCRM decided), worker code ready, deploy notes
Public site: pack accepted planning-only (Entry 044)
Status: working internal operational MVP (Entry 050)
Next: observation window (1–2 days real use, friction notes), then EspoCRM / worker / site
Main discipline: no redesign, no scope drift, no weakening of frozen rules

Entry 005

Date: Slice A / A1 acceptance snapshot
Scope: Slice A / A1 internal scaffold
Status: accepted

Completed
	•	Inquiry domain model
	•	Inquiry repository protocol
	•	in-memory inquiry repository
	•	Inquiry service with create_inquiry / update_inquiry
	•	unit tests for A1 baseline

Accepted
	•	A1 internal scaffold accepted in substance
	•	acceptance based on reviewed code fragments and passing pytest output
	•	substantive A1 boundary and contract requirements satisfied

Open
	•	remaining Slice A scope beyond A1
	•	A2 intake adapters not yet implemented at this point
	•	broader package-level acceptance validation not yet logged at this point

Must not be changed
	•	no second status axis
	•	no order-side leakage
	•	no kitchen/release leakage
	•	frozen crm_stage / planning_mode / call_verification_status alignment must remain preserved

⸻

Entry 006

Date: Slice A / A2 acceptance snapshot
Scope: Slice A / A2 intake adapters
Status: accepted

Completed
	•	narrow channel adapters for wix_form, email, phone, manual
	•	normalization into the shared InquiryService.create_inquiry(...) path for all channels
	•	unit tests for intake adapters (tests/unit/test_intake_adapters.py)
	•	empty intake/__init__.py package marker with no business logic

Accepted
	•	A2 intake adapters as the only Slice A intake surface for the four channels
	•	contract-safe per-channel defaults without inventing new frozen domain semantics
	•	reviewed adapter code and passing pytest for A1 + A2 unit tests

Open
	•	remaining Slice A scope beyond A1/A2 per SLICE_A_EXECUTION_PACK_V1
	•	broader acceptance validation against TEST_AND_ACCEPTANCE_MATRIX_V1 not yet logged here
	•	next documented Slice A execution steps after A2

Must not be changed
	•	A2 adapter implementation as accepted, with no drive-by edits
	•	all adapters must keep normalizing only into InquiryService.create_inquiry(...)
	•	no order-side leakage
	•	no kitchen / release / READY_TO_SEND / kiosk / Wochenübersicht behavior
	•	no second status axis
	•	A1 Inquiry domain contracts preserved (crm_stage pipeline, planning_mode, call_verification_status, customer_linkage rules)

⸻

Entry 007

Date: Slice A / A1-A2 hardening acceptance snapshot
Scope: Slice A / A1-A2 hardening pack
Status: accepted

Completed
	•	expanded A1 validation and repository tests
	•	expanded A2 adapter tests
	•	narrow technical logging added for inquiry service and intake adapters
	•	A1/A2 boundaries preserved during hardening

Accepted
	•	broader A1 test coverage
	•	broader A2 adapter coverage
	•	minimal Slice-A-safe logging baseline
	•	passing pytest for A1 + A2 hardening suite

Open
	•	remaining Slice A scope beyond A1/A2/hardening
	•	broader package-level acceptance logging not yet finalized
	•	next Slice A execution step after A2 hardening

Must not be changed
	•	no second status axis
	•	no order-side leakage
	•	no kitchen/release/kiosk/Wochenübersicht behavior
	•	all intake channels must keep normalizing only into InquiryService.create_inquiry(...)
	•	frozen inquiry-domain truth must remain preserved

⸻

Entry 008

Date: Slice A execution-pack reconciliation snapshot
Scope: Formal Slice A closeout check
Status: prepared

Completed
	•	formal reconciliation attempt against SLICE_A_EXECUTION_PACK_V1 initiated
	•	accepted A1 / A2 / A1-A2 hardening implementation line reviewed against visible code, tests, and existing WORKLOG entries
	•	narrow reconciliation result recorded without redesign or scope expansion

Accepted
	•	reconciliation output confirming that A1, A2, and hardening are materially implemented on the accepted code line
	•	recommendation that formal Slice A closure still requires access to the canonical SLICE_A_EXECUTION_PACK_V1 text

Open
	•	canonical point-by-point comparison against SLICE_A_EXECUTION_PACK_V1
	•	formal Slice A closeout verdict after execution-pack reconciliation
	•	identification of any remaining Slice A items, if any, once the canonical pack is available

Must not be changed
	•	no retroactive redesign of accepted A1 / A2 / hardening scope
	•	no move into Slice B before formal Slice A reconciliation is completed
	•	no weakening of frozen Slice A boundaries
	•	no invention of missing execution-pack requirements without the canonical artifact

⸻

Entry 009

Date: Slice A final closeout package
Scope: External Secure Intake Layer baseline, HubSpot office-facing baseline, Slice A acceptance evidence, minimal events / verify-by-call
Status: accepted

Completed
	•	`intake/external_secure_intake_layer.py` — explicit §8 boundary + `normalize_public_wix_inquiry_payload`; wired into `wix_form_adapter`
	•	`integration/hubspot_office_intake.py` — office-facing HubSpot port, env-only credential accessor, noop stub
	•	`domain/slice_a_events.py` + optional `event_sink` on `InquiryService`; `verify_customer_by_call` for §6.1
	•	`SLICE_A_CLOSEOUT.md` — evidence mapping for §8, §11, §15, §17 and CRM office-facing note

Accepted
	•	narrow Slice A package only; A1/A2/hardening behavior preserved except additive event emission and wix normalization hook
	•	no Order / OrderVersion / kitchen / READY_TO_SEND / Wochenübersicht / kiosk

Open
	•	deploy-time wiring (Cloudflare Worker, real HubSpot HTTP) outside this repository as needed
	•	Slice B remains next execution target after process sign-off if required

Must not be changed
	•	frozen CRM pipeline, planning_mode set, call_verification_status set, customer_linkage rules
	•	Inquiry / CRM axis as office-facing process truth only

⸻

Entry 010

Date: Slice B / B1 acceptance snapshot
Scope: Slice B / B1 minimal Core domain scaffold
Status: accepted

Completed
	•	minimal Core-owned Order model introduced
	•	minimal Core-owned OrderVersion model introduced
	•	OrderRepository and in-memory baseline introduced
	•	controlled convert_inquiry_to_order(...) path implemented
	•	unit tests for B1 baseline added

Accepted
	•	first Core-owned operational truth baseline established
	•	inquiry-to-order conversion under Core ownership established
	•	initial OrderVersion created in the same controlled path
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B1
	•	no kitchen acceptance mechanics yet
	•	no effective operational switching yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no kitchen print logic in B1
	•	no READY_TO_SEND semantics in B1
	•	no effective switching in B1
	•	Slice A boundaries must remain intact

⸻

Entry 011

Date: Slice B / B2 acceptance snapshot
Scope: Slice B / B2 controlled order-version history
Status: accepted

Completed
	•	repository support for listing order versions added
	•	controlled creation of follow-up OrderVersion implemented
	•	immutable order-version history preserved
	•	unit tests for B2 version-history behavior added

Accepted
	•	second and later OrderVersion records can be created under Core ownership
	•	version_number increments correctly
	•	prior versions remain preserved
	•	no effective-switch / kitchen / release / READY_TO_SEND / Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B2
	•	no active/effective version mechanics yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B2
	•	no kitchen print logic in B2
	•	no READY_TO_SEND semantics in B2
	•	Slice A boundaries must remain intact

⸻

Entry 012

Date: Slice B / B3 acceptance snapshot
Scope: Slice B / B3 controlled version-history read path
Status: accepted

Completed
	•	explicit Core read path for full order-version history confirmed
	•	explicit Core read path for latest historical OrderVersion confirmed
	•	guardrails added to prevent premature active/effective semantics
	•	B3 tests added and passing

Accepted
	•	latest historical version can be read explicitly by version_number
	•	full immutable version history remains available
	•	latest-in-history is not treated as effective/active operational version
	•	no kitchen/release/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B3
	•	no effective-switch mechanics yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no active/effective semantics in B3
	•	no kitchen print logic in B3
	•	no READY_TO_SEND semantics in B3
	•	Slice A boundaries must remain intact

⸻

Entry 013

Date: Slice B / B4 acceptance snapshot
Scope: Slice B / B4 customer linkage and call verification gate
Status: accepted

Completed
	•	narrow customer verification domain/value layer introduced
	•	customer verification service introduced
	•	controlled classification of client state as known / new / suspicious implemented
	•	inquiry-side call verification decision application implemented
	•	unit tests for B4 scenarios added

Accepted
	•	customer linkage / contact-match decision logic established in a narrow Core/office-side layer
	•	new and suspicious clients require office call verification
	•	known clients are distinguished from new/suspicious without introducing broader CRM operational truth
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B4
	•	no kitchen acceptance mechanics yet
	•	no effective operational switching yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no kitchen print logic in B4
	•	no READY_TO_SEND semantics in B4
	•	no effective switching in B4
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 014

Date: Slice B / B5 acceptance snapshot
Scope: Slice B / B5 inquiry-to-order verification gate
Status: accepted

Completed
	•	narrow inquiry-to-order conversion gate introduced
	•	conversion now depends on inquiry-side verification state
	•	unit tests for allowed and blocked conversion paths added

Accepted
	•	inquiry-to-order conversion is allowed when verification is not required
	•	inquiry-to-order conversion is allowed when verification is required and verified
	•	inquiry-to-order conversion is blocked when verification is required and not verified
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B5
	•	no kitchen acceptance mechanics yet
	•	no effective operational switching yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no kitchen print logic in B5
	•	no READY_TO_SEND semantics in B5
	•	no effective switching in B5
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 015

Date: Slice B / B6 acceptance snapshot
Scope: Slice B / B6 office/Core-side candidate order version
Status: accepted

Completed
	•	narrow candidate order-version marker introduced
	•	service path to set and read candidate order version implemented
	•	candidate validation against order/version ownership implemented
	•	unit tests for candidate-version behavior added

Accepted
	•	office/Core-side candidate version can be set explicitly
	•	candidate version remains distinct from latest historical version
	•	candidate version does not imply effective/active operational truth
	•	full immutable version history remains preserved
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B6
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B6
	•	no kitchen print logic in B6
	•	no READY_TO_SEND semantics in B6
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 016

Date: Slice B / B7 acceptance snapshot
Scope: Slice B / B7 derived progression blocked-state evaluation
Status: accepted

Completed
	•	narrow progression blocked-state evaluation introduced
	•	inquiry-to-order blocked evaluation made explicit
	•	candidate-version progression blocked evaluation made explicit
	•	unit tests for B7 progression scenarios added

Accepted
	•	blocked-state is derived from existing facts and rules, not stored as a new truth axis
	•	inquiry-to-order progression is explicitly blocked when inquiry verification gate is unsatisfied
	•	candidate-based progression is explicitly blocked when candidate version is missing or not resolvable
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B7
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B7
	•	no kitchen print logic in B7
	•	no READY_TO_SEND semantics in B7
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 017

Date: Slice B / B8 acceptance snapshot
Scope: Slice B / B8 composed order progression view
Status: accepted

Completed
	•	narrow composed read model for order progression introduced
	•	progression view now combines latest historical version, candidate version, and derived blocked-state
	•	unit tests for progression-view composition added

Accepted
	•	progression visibility is available through one explicit composed read model
	•	latest historical version remains distinct from candidate version
	•	blocked/reasons remain derived from existing rules only
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B8
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B8
	•	no kitchen print logic in B8
	•	no READY_TO_SEND semantics in B8
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 018

Date: Slice B / B9 acceptance snapshot
Scope: Slice B / B9 derived progression decision
Status: accepted

Completed
	•	narrow derived progression decision model introduced
	•	explicit office/Core-side progression decision evaluation implemented
	•	unit tests for progression decision scenarios added

Accepted
	•	progression eligibility is derived from existing blocked-state and candidate facts only
	•	no new persisted progression truth axis introduced
	•	progression decision remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B9
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B9
	•	no kitchen print logic in B9
	•	no READY_TO_SEND semantics in B9
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 019

Date: Slice B / B10 acceptance snapshot
Scope: Slice B / B10 derived progression checkpoint snapshot
Status: accepted

Completed
	•	narrow derived progression checkpoint model introduced
	•	checkpoint now composes progression view and progression decision into one read-only snapshot
	•	unit tests for checkpoint composition added

Accepted
	•	current office/Core-side progression state can be read through one explicit derived checkpoint snapshot
	•	checkpoint remains read-only and derived from existing facts only
	•	no new persisted progression truth axis introduced
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B10
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B10
	•	no kitchen print logic in B10
	•	no READY_TO_SEND semantics in B10
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 020

Date: Slice B / B11 acceptance snapshot
Scope: Slice B / B11 derived progression review summary
Status: accepted

Completed
	•	narrow derived progression review summary model introduced
	•	review summary now composes existing checkpoint facts into one compact read-only summary
	•	unit tests for review summary scenarios added

Accepted
	•	office/Core-side progression review visibility is available through one compact derived summary
	•	summary remains fully derived from existing facts only
	•	no new persisted progression truth axis introduced
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B11
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B11
	•	no kitchen print logic in B11
	•	no READY_TO_SEND semantics in B11
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 021

Date: Slice B / B12 acceptance snapshot
Scope: Slice B / B12 derived progression consistency check
Status: accepted

Completed
	•	narrow derived progression consistency-check model introduced
	•	consistency evaluation across existing progression read layers implemented
	•	unit tests for consistency scenarios added

Accepted
	•	consistency is evaluated only from existing derived progression layers
	•	no new persisted progression truth axis introduced
	•	consistency check remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B12
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B12
	•	no kitchen print logic in B12
	•	no READY_TO_SEND semantics in B12
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 022

Date: Slice B / B13 acceptance snapshot
Scope: Slice B / B13 derived progression bundle
Status: accepted

Completed
	•	narrow derived progression bundle model introduced
	•	bundle now groups existing progression view, decision, checkpoint, review summary, and consistency check
	•	unit tests for bundle scenarios added

Accepted
	•	progression bundle is composed only from existing derived progression artifacts
	•	no new persisted progression truth axis introduced
	•	bundle remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B13
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B13
	•	no kitchen print logic in B13
	•	no READY_TO_SEND semantics in B13
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 023

Date: Slice B / B14 acceptance snapshot
Scope: Slice B / B14 derived progression export DTO
Status: accepted

Completed
	•	narrow derived progression export model introduced
	•	export now flattens the existing progression bundle into a simple serializable shape
	•	unit tests for export scenarios added

Accepted
	•	export is derived only from existing progression artifacts
	•	no new persisted progression truth axis introduced
	•	export remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B14
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B14
	•	no kitchen print logic in B14
	•	no READY_TO_SEND semantics in B14
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 024

Date: Slice B / B15 acceptance snapshot
Scope: Slice B / B15 derived progression text summary
Status: accepted

Completed
	•	narrow derived progression text-summary formatter introduced
	•	text summary now converts the existing progression export DTO into a deterministic human-readable string
	•	unit tests for text summary scenarios added

Accepted
	•	text summary is derived only from the existing flat progression export DTO
	•	no new persisted progression truth axis introduced
	•	text summary remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B15
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B15
	•	no kitchen print logic in B15
	•	no READY_TO_SEND semantics in B15
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 025

Date: Slice B / B16 acceptance snapshot
Scope: Slice B / B16 derived progression debug dict
Status: accepted

Completed
	•	narrow derived progression debug-dict mapper introduced
	•	debug dict now converts the existing progression export DTO into a plain built-in mapping shape
	•	unit tests for debug-dict scenarios added

Accepted
	•	debug dict is derived only from the existing flat progression export DTO
	•	no new persisted progression truth axis introduced
	•	debug dict remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B16
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B16
	•	no kitchen print logic in B16
	•	no READY_TO_SEND semantics in B16
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 026

Date: Slice B / B17 acceptance snapshot
Scope: Slice B / B17 derived progression JSON debug
Status: accepted

Completed
	•	narrow derived progression JSON-debug helper introduced
	•	JSON debug now converts the existing progression debug dict into a deterministic JSON string
	•	unit tests for JSON-debug scenarios added

Accepted
	•	JSON debug is derived only from the existing B16 debug dict
	•	no new persisted progression truth axis introduced
	•	JSON debug remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B17
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B17
	•	no kitchen print logic in B17
	•	no READY_TO_SEND semantics in B17
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 027

Date: Slice B / B18 acceptance snapshot
Scope: Slice B / B18 derived progression reason codes
Status: accepted

Completed
	•	narrow derived progression reason-codes projection introduced
	•	reason-codes view now extracts only order_id, reason_count, and reasons from the existing progression export DTO
	•	unit tests for reason-codes scenarios added

Accepted
	•	reason-codes projection is derived only from the existing B14 export DTO
	•	no new persisted progression truth axis introduced
	•	reason-codes projection remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B18
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B18
	•	no kitchen print logic in B18
	•	no READY_TO_SEND semantics in B18
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 028

Date: Slice B / B19 acceptance snapshot
Scope: Slice B / B19 derived progression status label
Status: accepted

Completed
	•	narrow derived progression status-label projection introduced
	•	status label now derives a single deterministic human-readable label from the existing progression export DTO
	•	unit tests for status-label scenarios added

Accepted
	•	status-label projection is derived only from the existing B14 export DTO
	•	no new persisted progression truth axis introduced
	•	status-label projection remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B19
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B19
	•	no kitchen print logic in B19
	•	no READY_TO_SEND semantics in B19
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 029

Date: Slice B / B20 acceptance snapshot
Scope: Slice B / B20 derived progression badges
Status: accepted

Completed
	•	narrow derived progression badges projection introduced
	•	badges now derive a deterministic minimal badge tuple from the existing progression export DTO
	•	unit tests for badges scenarios added

Accepted
	•	badges projection is derived only from the existing B14 export DTO
	•	no new persisted progression truth axis introduced
	•	badges projection remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B20
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B20
	•	no kitchen print logic in B20
	•	no READY_TO_SEND semantics in B20
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 030

Date: Slice B / B21 acceptance snapshot
Scope: Slice B / B21 derived progression severity
Status: accepted

Completed
	•	narrow derived progression severity projection introduced
	•	severity now derives a deterministic minimal severity level from the existing progression export DTO
	•	unit tests for severity scenarios added

Accepted
	•	severity projection is derived only from the existing B14 export DTO
	•	no new persisted progression truth axis introduced
	•	severity projection remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B21
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B21
	•	no kitchen print logic in B21
	•	no READY_TO_SEND semantics in B21
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 031

Date: Slice B / B22 acceptance snapshot
Scope: Slice B / B22 derived progression state signature
Status: accepted

Completed
	•	narrow derived progression state-signature projection introduced
	•	state signature now derives one deterministic compact signature string from the existing progression export DTO
	•	unit tests for signature scenarios added

Accepted
	•	state signature projection is derived only from the existing B14 export DTO
	•	no new persisted progression truth axis introduced
	•	state signature remains distinct from release/effective/kitchen semantics
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht behavior introduced

Open
	•	remaining Slice B scope beyond B22
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	no hidden move into later Slice B packages
	•	no effective switching in B22
	•	no kitchen print logic in B22
	•	no READY_TO_SEND semantics in B22
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 032

Date: Slice B / B23 acceptance snapshot
Scope: Slice B / B23 derived progression facts projection
Status: accepted

Completed
	•	narrow derived progression facts projection from B14 export only
	•	introduced OrderProgressionFacts as a minimal read-only projection with derivation from OrderProgressionExport only
	•	added ProgressionService.get_order_progression_facts(order_id)
	•	unit coverage for unknown order → None, eligible case, blocked candidate-missing case, synthetic from-export case, module boundary guard

Accepted
	•	B23 provides one compact boolean-facts summary for filtering/debugging/sorting
	•	projection remains derived only and introduces no new operational truth
	•	no kitchen/release/effective/READY_TO_SEND/Wochenübersicht semantics introduced

Open
	•	remaining Slice B scope beyond B23
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	facts projection must remain derived from B14 export only
	•	facts projection must remain read-only
	•	facts projection must not become a release or workflow decision source
	•	no hidden move into later Slice B packages
	•	no effective switching in B23
	•	no kitchen print logic in B23
	•	no READY_TO_SEND semantics in B23
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 033

Date: 2026-04-01 — Slice B / B24–B25 acceptance snapshot
Scope: Slice B / B24 derived progression reason fingerprint; Slice B / B25 derived progression readiness flags
Status: accepted

Completed
	•	added derived progression reason fingerprint projection from B14 export only
	•	added derived progression readiness flags projection from B14 export only
	•	introduced read-only derived artifacts for progression reason fingerprint and readiness flags
	•	added service getters deriving from B14 export only
	•	extended unit coverage for unknown order behavior, eligible cases, blocked candidate-missing cases, and synthetic derivation shapes
	•	full unit suite passes

Accepted
	•	B24 and B25 remain derived-only and read-only
	•	both projections derive strictly from B14 export only
	•	unknown order returns None
	•	no kitchen, release, READY_TO_SEND, Wochenübersicht, or operational-side semantics introduced

Open
	•	remaining Slice B scope beyond B25
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	B14 export remains the only source for both projections
	•	no persistence, release logic, or new operational truth may be introduced through these artifacts
	•	no hidden move into later Slice B packages
	•	no effective switching in B24 or B25
	•	no kitchen print logic in B24 or B25
	•	no READY_TO_SEND semantics in B24 or B25
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 034

Date: 2026-04-01 — Slice B / B26 acceptance snapshot
Scope: Slice B / B26 derived progression reason presence
Status: accepted

Completed
	•	implemented src/catering_system/domain/order_progression_reason_presence.py
	•	added derived-only projection OrderProgressionReasonPresence (order_id, has_reasons) from OrderProgressionExport only via from_export(...)
	•	added ProgressionService.get_order_progression_reason_presence(order_id) -> OrderProgressionReasonPresence | None
	•	extended tests/unit/test_progression_service.py: unknown order returns None; eligible with candidate has has_reasons False; blocked candidate-missing has has_reasons True; synthetic from_export coverage; module-surface guard includes new module
	•	verified full unit suite passes (135 passed; command: PYTHONPATH=src pytest tests/unit/ -v)

Accepted
	•	B26 remains strictly derived and read-only
	•	B26 derives only from OrderProgressionExport (B14)
	•	no new operational truth introduced
	•	no persistence added
	•	no kitchen/release/READY_TO_SEND/kiosk/Wochenübersicht logic introduced

Open
	•	remaining Slice B scope beyond B26
	•	no effective operational switching yet
	•	no kitchen acceptance mechanics yet

Must not be changed
	•	OrderProgressionExport remains the single source of truth for this projection
	•	projection must remain a narrow boolean read model only
	•	no branching into workflow semantics beyond export-derived fact exposure
	•	no hidden move into later Slice B packages
	•	no effective switching in B26
	•	no kitchen print logic in B26
	•	no READY_TO_SEND semantics in B26
	•	Slice A boundaries and earlier Slice B boundaries must remain intact

⸻

Entry 035

Date: 2026-04-01 — Slice B / B27 narrow composed derived review summary
Status: completed (narrow)

Scope
	•	add one narrow read-only composed derived review summary on top of already accepted progression-derived outputs
	•	keep existing B11 review summary semantics unchanged
	•	avoid naming collision by introducing a separate composed derived review summary object and getter

Completed
	•	added a new narrow read-only composed derived review summary DTO in the accepted progression read-model placement
	•	added a dedicated progression service getter that composes:
		◦	checkpoint-derived order_id
		◦	checkpoint-derived latest_order_version_id
		◦	checkpoint-derived candidate_order_version_id
		◦	checkpoint-derived blocked
		◦	B21 derived severity
		◦	B24 derived reason fingerprint
		◦	B25 derived readiness flags
		◦	B23-derived facts_count
	•	added a narrow dedicated unit test file for the composed derived review summary
	•	verified narrow test coverage for:
		◦	version references match checkpoint
		◦	blocked matches checkpoint
		◦	severity matches accepted derived severity
		◦	reason_fingerprint matches accepted derived reason fingerprint
		◦	readiness_flags match accepted derived readiness flags
		◦	facts_count is derived strictly from the accepted B23 facts representation
		◦	no mutation / no side effects
	•	full unit suite passed after the change

Accepted constraints preserved
	•	read-side only
	•	no new command semantics
	•	no write behavior
	•	no kitchen logic
	•	no release logic
	•	no new truth path
	•	no progression semantic changes
	•	no effect on effective switching
	•	no effect on mandatory kitchen print
	•	no effect on READY_TO_SEND

Notes
	•	existing B11 review summary was not broadened or repurposed
	•	the composed derived review summary is a separate narrow aggregation step
	•	facts_count is derived strictly from the already accepted B23 facts representation and must not be reinterpreted later
	•	implemented counting rule (matches code): `facts_count` = number of `True` values among the four B23 boolean fields only — `has_reasons`, `is_blocked`, `is_consistent`, `is_eligible`

Open
	•	final acceptance depends on code review against the exact changed files and confirmation that the worklog wording matches the implemented counting rule exactly

Must not be changed
	•	B26 remains the accepted step for derived progression reason presence
	•	this step must remain a narrow aggregation layer only
	•	no hidden fallback logic or new business truth may be introduced into this summary
⸻

Entry 036

Date: 2026-07-05 — repository reconciliation and audit closeout
Scope: audit findings, history correction, tooling baseline, OPERATIONAL_CORE_EXECUTION_PACK_V1 acceptance
Status: accepted

Completed
	•	full code audit of Slice A + B1–B27 line (all 140 unit tests passing)
	•	B27 accepted after review: composed derived review summary committed with an honest message
	•	history correction recorded: commit f6bcab4 is titled "Slice B27 accepted: derived progression eligibility label" but actually contains B26 (reason presence); the real B27 was committed separately after this reconciliation. History is not rewritten (already pushed); this entry is the durable correction.
	•	documentation reconciliation: README_START_HERE.md, CURRENT_STATUS.md, NEXT_STEP.md, and the ten architecture documents named in Entries 001–003 confirmed absent from the repository and its entire git history; continuation rule (section 6) updated accordingly
	•	living sections 4/5/7 updated from stale "Slice A not started" state to actual position
	•	Order and OrderVersion made frozen dataclasses — "immutable version history" (B2/B3) is now enforced by code, not convention; no behavior or test changes required
	•	pyproject.toml added (pytest config, pythonpath=src); per-test sys.path hack removed
	•	OPERATIONAL_CORE_EXECUTION_PACK_V1.md written, reviewed in two external review rounds, and accepted as the next execution target (its §2 precedence rule: repo evidence + accepted WORKLOG entries win over never-seen canonical documents)

Accepted
	•	B27 composed derived review summary (closes the "Open" item of Entry 035)
	•	frozen Order/OrderVersion as enforcement of the already-accepted immutability rule
	•	OPERATIONAL_CORE_EXECUTION_PACK_V1 as freeze-candidate execution target, with its two open [ASSUMPTION] items (§1 slice naming, §8.2 print-as-domain-fact) resolved by proceeding as written

Open
	•	OPERATIONAL_CORE_EXECUTION_PACK_V1 §14 implementation
	•	SQLite persistence behind the existing repository Protocols
	•	removal of leaf debug formatters B16/B17 (accepted as low-value; B12 consistency check stays for now — it is load-bearing: its output feeds B13 bundle → B14 export → B23 facts.is_consistent → B27 facts_count, so removing it would change accepted contracts and needs its own narrow step)

Must not be changed
	•	no rewriting of pushed git history to fix the f6bcab4 mislabel
	•	frozen Order/OrderVersion must not be reverted to mutable
	•	B7–B27 read-side contracts remain intact per OPERATIONAL_CORE_EXECUTION_PACK_V1 §13

⸻

Entry 037

Date: 2026-07-05 — operational core implementation
Scope: OPERATIONAL_CORE_EXECUTION_PACK_V1 §14 steps 1–5
Status: accepted

Completed
	•	OrderVersion.kitchen_print_confirmed_at and Order.effective_order_version_id added (exactly the two §7 fields, no others)
	•	OperationalCoreService: confirm_kitchen_print (idempotent, ownership-checked, not revocable per §8.4), make_order_version_effective (gated on confirmed print per §9), evaluate_ready_to_send (pure read), request_ready_to_send (event-only command per §6.1)
	•	domain/ready_to_send.py: gate rule owned directly by this layer with its own reason vocabulary (ready_to_send_order_not_found, no_effective_version, effective_version_not_resolvable, kitchen_print_not_confirmed) — independent of the B7–B27 progression vocabulary per §10
	•	domain/operational_core_events.py: KitchenPrintConfirmed, OrderVersionMadeEffective, OrderReadyToSend, OrderReadyToSendBlocked
	•	B3-era guard test in test_order_service.py amended to the §7 boundary: it now asserts the exact field sets of Order/OrderVersion (stricter than before) instead of forbidding the word "kitchen" outright
	•	17 new unit tests covering all §15 required scenarios; full suite passes (157)

Accepted
	•	kitchen print gate cannot be bypassed: effective switch raises without prior confirmation
	•	exactly one effective version per order; switch never touches candidate or history
	•	make_order_version_effective may target any owned, print-confirmed version, not only the candidate (§9)
	•	READY_TO_SEND stays derived, never stored; RequestReadyToSend changes no order truth in either branch
	•	no dependency of the gate on B7–B27 (§12 respected)

Open
	•	SQLite persistence behind the existing repository Protocols (in-memory confirmations do not survive restart)
	•	B16/B17 removal
	•	§8.2 assumption stands: print confirmation is a domain fact; physical printer pipeline, if required, needs its own pack

Must not be changed
	•	the two §7 fields remain the only operational fields; no further status axis
	•	gate rule and reason vocabulary stay owned by the operational layer
	•	confirmation stays idempotent and non-revocable within this layer

⸻

Entry 038

Date: 2026-07-05 — SQLite persistence adapters
Scope: persistence behind the existing repository Protocols
Status: accepted

Completed
	•	SQLiteOrderRepository and SQLiteInquiryRepository implementing the existing Protocols unchanged
	•	schema mirrors the frozen field sets (incl. the two OPERATIONAL_CORE §7 fields); values re-validated through frozen domain validators on load
	•	tests: full-field roundtrips, version ordering, KeyError-on-missing-update parity with in-memory, operational-core flow surviving a simulated restart, B7–B27 progression chain running unchanged over SQLite
	•	full suite passes (164)

Accepted
	•	persistence is an adapter only: no business rules, no new truth axis, no schema fields beyond the frozen domain
	•	in-memory repositories remain the default for unit tests

Open
	•	wiring a concrete db path for real deployment (belongs to the deployment pack, §18 of the operational pack)

Must not be changed
	•	repository Protocols stay the single seam; services never see SQL

⸻

Entry 039

Date: 2026-07-05 — removal of B16/B17 leaf formatters
Scope: derived-read cleanup per audit
Status: accepted

Completed
	•	removed B16 (order_progression_debug_dict) and B17 (order_progression_json_debug) with their service getters and tests
	•	both were pure serializations of the B14 export with no consumer; removing them changes no other contract
	•	full suite passes (159)

Accepted
	•	B16/B17 are no longer part of the accepted surface; Entry 025/026 remain as history
	•	B12 consistency check deliberately kept: it is load-bearing (B13 bundle → B14 export → B23 facts.is_consistent → B27 facts_count); its removal would change accepted contracts and needs its own narrow step if ever desired

Open
	•	none for this step

Must not be changed
	•	no re-introduction of leaf formatter slices without a consumer and an accepted pack

⸻

Entry 040

Date: 2026-07-05 — Wochenübersicht derived weekly overview
Scope: WOCHENUEBERSICHT_EXECUTION_PACK_V1
Status: accepted

Completed
	•	pack written and accepted (derived-only role per Entry 001 preserved)
	•	domain/wochenuebersicht.py: frozen WochenuebersichtEntry + Wochenuebersicht, ISO-week helper
	•	WochenuebersichtService.get_week_overview(iso_year, iso_week) — pure read from orders + effective versions only
	•	additive OrderRepository.list_orders() on Protocol, in-memory, and SQLite adapters
	•	tests: empty week, no-effective exclusion, out-of-week exclusion, effective-not-latest (newer history row does not leak in), deterministic ordering, purity; suite 166 passed

Accepted
	•	overview is derived on demand, never persisted; no WochenübersichtVersion snapshots
	•	effective versions are the only source; every listed entry is print-confirmed by construction (operational gate)

Open
	•	kitchen kiosk read-only UI consuming this read model (own pack)

Must not be changed
	•	derived-only role of Wochenübersicht
	•	no candidate/latest-historical leakage into the overview

⸻

Entry 041

Date: 2026-07-05 — kitchen kiosk read-only UI
Scope: KIOSK_EXECUTION_PACK_V1
Status: accepted

Completed
	•	pack written and accepted (read-only MVP role per Entry 001 preserved)
	•	ui/kiosk_server.py: stdlib-only HTTP server; GET-only (405 for POST/PUT/DELETE/PATCH, 404 for unknown paths); renders Wochenübersicht for current ISO week, ?year=&week= selects another; auto-refresh every 60s; order-originating text HTML-escaped
	•	pure render function separated from the handler (testable without sockets)
	•	runnable entrypoint: python -m catering_system.ui.kiosk_server --db <sqlite> --port <p>
	•	tests: render content, empty week, HTML-injection escaping, live-socket GET/405/404, malformed params fallback, no-write-surface guard; suite 174 passed

Accepted
	•	first UI surface in the project; consumes WochenuebersichtService only
	•	kiosk writes nothing, ever — enforced by handler shape and guard test

Open
	•	HubSpot wiring / secure intake worker / deployment (next pack)

Must not be changed
	•	kiosk stays read-only; no mutating endpoint may be added to it
	•	no frontend build tooling / JS frameworks in the kiosk MVP

⸻

Entry 042

Date: 2026-07-05 — integration and deployment layer (code side)
Scope: INTEGRATION_DEPLOYMENT_EXECUTION_PACK_V1
Status: accepted (code side); external deploys remain manual user steps

Completed
	•	pack written and accepted
	•	HubSpotOfficeInquiryHttp behind the existing HubSpotOfficeInquiryPort: stdlib urllib, injectable transport (tests never touch the network), token strictly from HUBSPOT_PRIVATE_APP_TOKEN env, missing token raises loudly before any request; explicit flat inquiry→properties mapping (crm_stage travels as plain text — stage-id mapping is portal configuration, not domain logic)
	•	infra/cloudflare_worker/worker.js — §8 External Secure Intake Layer: POST-only, 16KB cap, field whitelist, text trim/limit, ISO event_date required, server-side bearer forward, upstream responses never relayed to the public caller
	•	DEPLOYMENT.md — manual bring-up steps: kiosk on kitchen Lenovo (SQLite on local disk per Core-on-Lenovo rule), HubSpot Private App + custom properties, wrangler deploy, recommended bring-up order
	•	tests: documented request shape (URL/auth/body), Protocol conformance, mapping correctness incl. None guest count, token-not-in-body, missing-token failure; suite 179 passed

Accepted
	•	integration layer is transport only; no change to Core truth semantics
	•	no secrets in code, tests, or browser-served content
	•	Noop stub remains the explicit no-op choice; HTTP client never silently no-ops

Open
	•	performing the external deploys (HubSpot account, Cloudflare account, physical Lenovo) — owner's manual steps per DEPLOYMENT.md
	•	office-side wiring that calls sync_inquiry_from_core on inquiry create/update (belongs to office automation, not Core)

Must not be changed
	•	HubSpot token stays env-only and server-side
	•	worker holds no business logic and is not operational truth (§8.3)

⸻

Entry 043

Date: 2026-07-05 — post-review corrections to Entry 041/042 deliverables
Scope: DEPLOYMENT.md kiosk launch command; worker guest_count coercion
Status: accepted

Completed
	•	DEPLOYMENT.md kiosk command corrected: src/ layout requires PYTHONPATH=src (verified by running both forms: plain form fails with ModuleNotFoundError, PYTHONPATH=src form works); pip install -e . documented as network-dependent alternative
	•	worker.js: digit-only string guest_count_estimate is now coerced to integer (minimal normalization per Slice A §8.2 — Wix form fields often arrive as strings); non-integer input still rejected with 422
	•	status clarification recorded: HubSpot integration is transport/client layer only; office-side wiring that calls sync_inquiry_from_core remains open (Entry 042) — it must not be presented as a completed integration

Must not be changed
	•	worker coercion stays limited to digit-only strings; no broader payload rewriting

⸻

Entry 044

Date: 2026-07-05 — public site execution pack accepted
Scope: PUBLIC_SITE_EXECUTION_PACK_V1
Status: accepted, planning-only

Meaning
	•	public site boundaries accepted; implementation deferred
	•	now-phase contains no code changes (see pack §7)

Completed
	•	PUBLIC_SITE_EXECUTION_PACK_V1 written, reviewed in external review rounds, and accepted
	•	full contents live in the pack file only — not duplicated here

Must not be changed
	•	site stays presentation + intake only
	•	worker remains the only public entry
	•	no direct Core access from the site
	•	no email-parser bridge from the AI assistant
	•	Stage 1 assistant remains email-to-office only
	•	"website" inquiry_source and notes_text enter the code only when actual site work starts, each as its own accepted implementation step

⸻

Entry 045

Date: 2026-07-05 — office panel execution pack accepted
Scope: OFFICE_PANEL_EXECUTION_PACK_V1
Status: accepted, planning-only

Meaning
	•	office panel boundaries accepted; implementation deferred
	•	this step is planning-only and contains no code changes

Fixed
	•	office panel = primary office write surface (7 of 9 daily office actions are Core actions)
	•	EspoCRM (self-hosted, office server) = secondary CRM / communication layer; own CRM permanently out of scope
	•	no CRM→Core bridge in any form
	•	panel writes only into Core on the kitchen Lenovo
	•	kitchen operations must not depend on office-server availability
	•	progression reasons (B7 vocabulary) and operational gate reasons (READY_TO_SEND vocabulary) remain separate vocabularies, never merged (per OPERATIONAL_CORE §10)
	•	Espo sync, if added later, stays optional and non-authoritative (Core→CRM push only)

Completed
	•	OFFICE_PANEL_EXECUTION_PACK_V1 written, reviewed in external review rounds, and accepted
	•	full contents live in the pack file only — not duplicated here

Must not be changed
	•	panel adds no new domain semantics; every action maps onto an existing accepted service call
	•	panel is LAN-only, never public, never anonymous
	•	no panel-side storage beyond Core (no store-and-forward, no second truth)
	•	implementation begins only as its own accepted step per pack §9

⸻

Entry 046

Date: 2026-07-05 — order cancellation (Storno)
Scope: STORNO_EXECUTION_PACK_V1
Status: accepted

Completed
	•	Order.cancelled_at added (third and last operational field per amended §7 boundary)
	•	cancel_order command: idempotent, not revocable, allowed at any stage; OrderCancelled event
	•	guards: operational commands and order-side mutations refused on cancelled orders
	•	READY_TO_SEND blocked with new operational-vocabulary reason order_cancelled
	•	cancelled orders excluded from Wochenübersicht (kiosk inherits)
	•	SQLite column + defensive in-place migration for pre-Storno databases
	•	suite 188 passed

Must not be changed
	•	cancellation stays a timestamp fact, never a status enum
	•	history/candidate/effective references stay untouched on cancel
	•	no uncancel without its own pack
	•	B7–B27 progression vocabulary not amended

⸻

Entry 047

Date: 2026-07-05 — office panel implemented
Scope: OFFICE_PANEL_EXECUTION_PACK_V1 §9 steps 1–4
Status: accepted

Completed
	•	ui/office_panel.py: working queue, inquiry create/update/verify, convert (gate-checked), order versions, kitchen print sheet (Küchenzettel), confirm print, make effective, request READY_TO_SEND, Storno button
	•	basic auth mandatory (panel refuses to start without a password); GET/POST only; unknown paths 404
	•	§5 respected: progression (B7) reasons rendered only on inquiry views, operational gate reasons only on order views — tested that vocabularies do not co-appear
	•	additive InquiryRepository.list_all() on Protocol, in-memory, and SQLite adapters
	•	presentation-only affordance: convert button hidden when the inquiry already has an order (service behavior unchanged); cancelled orders hide action buttons while the server-side gates still refuse (tested)
	•	DEPLOYMENT.md: panel launch section (§1a) and daily SQLite backup cron (§1b)
	•	18 new live-socket tests; suite 206 passed

Must not be changed
	•	panel stays a thin skin: no domain logic in the UI layer
	•	auth stays mandatory; LAN-only rule stays
	•	the two reason vocabularies stay separate in all views

⸻

Entry 048

Date: 2026-07-05 — bring-up bug fix: SQLite cross-thread crash in UI servers
Scope: kiosk_server.py, office_panel.py (narrow implementation fix)
Status: accepted

Completed
	•	first live bring-up on the kitchen Lenovo surfaced a real defect: kiosk crashed on first GET with sqlite3.ProgrammingError (connection created in main thread, request handled in a ThreadingHTTPServer worker thread)
	•	the office panel had the identical pattern and was fixed in the same step (strictly required: it would crash the same way on first request)
	•	fix: ThreadingHTTPServer replaced with single-threaded HTTPServer in both UI servers — smallest safe fix; kiosk is a one-client read-only display, and single-threading additionally serializes panel writes on SQLite
	•	regression tests added for both servers that mirror the Lenovo setup (sqlite repos + server built in the serving thread, requests over live HTTP); the kiosk test reproduced the exact production traceback before the fix
	•	test-gap cause recorded: existing live-socket tests used in-memory repositories only, so SQLite never crossed a thread boundary in CI
	•	suite 210 passed

Must not be changed
	•	UI servers stay single-threaded until an accepted step introduces per-request/thread-local connections
	•	no other behavior touched

⸻

Entry 049

Date: 2026-07-05 — Lenovo bring-up smoke test passed; autostart artifacts
Scope: bring-up progress (DEPLOYMENT.md §1–1b), systemd units
Status: bring-up partially complete

Completed
	•	first live end-to-end smoke test on the kitchen Lenovo passed: office panel and kiosk reachable over Tailscale; inquiry created → converted → kitchen print confirmed → version wirksam → READY_TO_SEND bereit → effective order visible in the Wochenübersicht in the correct ISO week
	•	systemd unit templates added (infra/systemd/): kiosk and office panel, restart-on-failure, boot autostart; panel password moved to /etc/catering/office-panel.env (chmod 600), never in the unit file
	•	DEPLOYMENT.md §1b: install steps for autostart and password rotation

Open (owner's manual steps on the Lenovo)
	•	replace the bring-up test password with a real one (env file per §1b)
	•	install and enable both systemd units
	•	set up the §1c backup cron
	•	later: EspoCRM on the office server, worker deploy, public site

Must not be changed
	•	panel password lives only in the root-owned env file
	•	single-threaded UI servers (Entry 048) remain until an accepted step says otherwise

⸻

Entry 050

Date: 2026-07-05 — Lenovo bring-up completed (owner-reported, verified live)
Scope: closure of Entry 049 open items on the kitchen Lenovo
Status: Lenovo part of bring-up complete; observation period next

Completed (on the machine, per owner's live verification)
	•	real panel password set via /etc/catering/office-panel.env (bring-up test password replaced)
	•	both systemd units installed and enabled; services autostart and survive a reboot (verified by actual reboot)
	•	core.db backup verified by hand; daily cron backup active; old-backup cleanup configured
	•	full operational loop re-confirmed live: inquiry → order → print confirmed → wirksam → bereit → kiosk shows the order in the correct ISO week
	•	current honest product status: working internal operational MVP for own catering — not a demo, not a SaaS

Open
	•	1–2 days of real working use; frictions recorded as plain notes, reconciled into packs afterwards
	•	EspoCRM on the office server; worker in real operation; public site; UX polishing

Must not be changed
	•	no code changes during the observation window except real blockers — frictions are collected first, then turned into narrow accepted steps
	•	all prior freeze boundaries remain

⸻

Entry 051

Date: 2026-07-05 — configurator role accepted
Scope: CONFIGURATOR_EXECUTION_PACK_V1
Status: accepted, planning-only

Meaning
	•	fingerfood-app (separate repository) fixed as the office's Angebot-phase editing surface; implementation of any seam deferred
	•	this step contains no code changes in this repository

Fixed
	•	configurator never writes into Core; office panel remains the only write surface
	•	configurator drafts/exports are never operational truth
	•	catalog and prices never land in Core
	•	no third inquiry intake path via the configurator
	•	known gap recorded: OrderVersion carries no dish composition; direction fixed (composition must eventually reach the Küchenzettel), mechanism deferred to its own accepted step after the observation window
	•	full contents live in the pack file only — not duplicated here

Must not be changed
	•	no configurator→Core bridge without an accepted pack
	•	the §3 mechanism must not be implemented during the observation window

⸻

Entry 052

Date: 2026-07-07 — office panel visual facelift (presentation-only)
Scope: src/catering_system/ui/office_panel.py — `_STYLE`, `_page()`
Status: accepted, no domain changes

Meaning
	•	owner asked for the office panel to visually match the fingerfood-app
	  configurator's Angebot-Formular styling (same brand facelift already
	  applied there: sage accent #5c6f63 pulled from the logo, Playfair
	  Display for headings, logo in a white top band)
	•	pure CSS/markup change: new `_STYLE` block, logo embedded as a base64
	  data URI constant (`_LOGO_DATA_URI`) so no static-file route or
	  filesystem dependency was added; `_page()` wraps body in a `.brandbar`
	  + `.content` shell
	•	no class names or text strings that `tests/unit/test_office_panel.py`
	  asserts on were touched (verified: all 40 assertions in that file check
	  substrings like "STORNIERT", "READY_TO_SEND blockiert", vocabulary
	  codes — none check CSS/markup structure)
	•	kiosk_server.py has its own separate styling and was intentionally not
	  touched — owner asked specifically about the office panel

Completed
	•	full suite: 210 passed (unchanged count — no test added or removed,
	  this is presentation-only)
	•	verified live: logged into the running office panel (Basic Auth,
	  local dev password), confirmed the brand band/logo, Playfair headings,
	  sage-styled tables and buttons render correctly on both the Büro-
	  Übersicht list view and an individual Auftrag detail view (incl. a
	  STORNIERT order, confirming status coloring survived unchanged)

Open
	•	kiosk_server.py not restyled (out of scope for this ask)
	•	push held pending owner/reviewer verdict per project workflow

Must not be changed
	•	office_panel.py still adds no domain semantics (pack §1) — this step
	  stayed purely visual, no route/behavior changes
	•	render_print_sheet() (Küchenzettel) intentionally untouched — separate
	  large-font kitchen printout, not part of this ask

⸻

Entry 053

Date: 2026-07-07 — Rückrufe: read-only pull from auerswald-sync (separate service)
Scope: src/catering_system/ui/office_panel.py — new fetch_missed_board(),
resolve_missed_call(), render_rueckruf(), GET /rueckruf, POST /rueckruf/resolve
Status: accepted

Meaning
	•	owner has a separate, already-running service (own repo, ~/projects/
	  auerswald-sync, not this repo, not Core, not EspoCRM) that syncs call
	  logs from an Auerswald PBX and computes a missed-call/callback board
	  (auerswald-sync's own build_missed_board_items()); office panel now
	  reads that board read-only, no bridge into Core in either direction
	•	this is the first time office_panel.py makes an outbound HTTP call to
	  a non-Core system — a new kind of capability compared to the existing
	  EspoCRM pattern ("no CRM→Core bridge... EspoCRM needs no network
	  route"), so flagging it explicitly rather than treating it as routine:
	  it is still read-only + one narrow write (the resolve toggle, which
	  lands in auerswald-sync's own state, never Core's)
	•	auerswald-sync itself gained one additive route, GET /missed-board.json
	  (same data as its existing HTML /missed-board), so office panel doesn't
	  scrape HTML; verified live against the real call log
	•	no Inquiry is ever created automatically from a missed call; converting
	  a callback into a real Inquiry remains an explicit office action via
	  the existing "+ Neue Anfrage erfassen" flow — this step adds visibility
	  only

Completed
	•	`fetch_missed_board()` / `resolve_missed_call()`: plain urllib, Basic
	  Auth, 5s timeout, all failure modes (unset URL, unreachable host, bad
	  auth, timeout) caught and rendered as a plain error message — never a
	  crash
	•	found and fixed a real robustness bug during testing: auerswald-sync's
	  /missed/resolve replies 303 to its own HTML /missed-board; the naive
	  urlopen() followed that redirect and could raise if the target wasn't
	  reachable/implemented. Fixed with a custom opener that does not follow
	  redirects — the resolve action only needs to know the POST landed
	•	CLI/env config: --auerswald-url/--auerswald-user/--auerswald-password
	  (or AUERSWALD_SYNC_URL/_USER/_PASSWORD), all optional — panel works
	  exactly as before if unset (shows "nicht konfiguriert" on /rueckruf)
	•	tests: 3 new (not configured → graceful message; unreachable host →
	  graceful message; stubbed auerswald-sync → items render + resolve
	  round-trips). Full suite: 213 passed (was 210)
	•	verified live end-to-end against the real call log: real missed-call
	  rows rendered in the office panel's brand-facelifted style; clicking
	  "Erledigt" correctly called through to auerswald-sync's real
	  /missed/resolve and the row disappeared on next load
	•	incident during that live verification, self-caught and disclosed:
	  the smoketest pointed at auerswald-sync's real data/ directory (needed
	  for realistic read data) and the "Erledigt" click wrote a real
	  call_id into the real resolved_missed_calls.json. Confirmed with the
	  owner and reverted that file to its pre-test state
	  ({"resolved_call_ids": []}); nothing here is git-tracked so no commit
	  was affected

Open
	•	real production AUERSWALD_SYNC_URL/credentials for the Lenovo/VPS
	  deployment not yet set (DEPLOYMENT.md not updated in this step —
	  narrow code step only)
	•	push held pending owner/reviewer verdict per project workflow

Must not be changed
	•	Rückrufe stays read-only + the one resolve toggle; no automatic
	  Inquiry creation from a missed call, no write into Core from this path
	•	auerswald-sync remains its own repo/service; this repo must not grow
	  a second copy of its call-parsing logic

⸻

Entry 054

Date: 2026-07-07 — Büro-Übersicht: Heute-Aufmerksamkeit, Blocker column, Diese Woche, Suche
Scope: src/catering_system/ui/office_panel.py — render_queue() rewrite
Status: accepted

Meaning
	•	owner relayed an external reviewer's dashboard proposal for the office
	  panel (raw tables → "what needs attention today" overview). Reviewed it
	  first: two of the proposed blocks (Verpasste Anrufe / Rückruf-Status)
	  required a data source that doesn't exist in this repo — that became
	  Entry 053 (separate, already-running auerswald-sync service). The rest
	  of the proposal needed no new domain concepts, only reorganizing data
	  the office panel already computes — narrow, no-domain-semantics step
	  (pack §1), same class of change as Entry 052's facelift
	•	added to the existing "/" queue view, in order:
	  1. "Heute" attention bar — five counts (Neue Anfragen ohne Auftrag,
	     Aufträge ohne Druckbestätigung, nicht wirksam, READY_TO_SEND
	     blockiert, storniert), each derived from data the page already
	     loads; no new repository/service calls beyond one already-used
	     evaluate_ready_to_send() per order (same call the Aufträge table
	     already made)
	  2. Aufträge table gained a "Blocker" column: first reason from the
	     already-existing evaluate_ready_to_send().reasons, previously only
	     shown on the individual order page
	  3. "Diese Woche" mini-view: reuses WochenuebersichtService (existing,
	     kiosk-only until now) read-only inside the office panel — same
	     derived-only guarantee (effective versions only, cancelled excluded)
	  4. Schnellsuche: plain `?q=` GET param, substring match server-side
	     across inquiry_id/location/date/crm_stage and order_id/inquiry_id;
	     no JS, no new endpoint — same "/" route, same render
	•	explicitly NOT built (deferred, not decided): a dedicated Wochen-page
	  inside the office panel (kiosk remains the only full week view);
	  cross-linking to the kiosk's own URL (would need a new config value,
	  same shape as auerswald_url — not done without being asked)

Completed
	•	tests: 6 new — empty-state attention bar, counts reacting to a real
	  convert (neue_anfragen drops, three others rise), blocker reason
	  string visible in the row, full release flow clearing all counts back
	  to 0, Diese-Woche showing only the current-ISO-week effective order
	  and excluding a different-week one, search filtering both tables by
	  substring. Full suite: 219 passed (was 213)
	•	verified live: real attention counts (0/0/0/0, 1 storniert from the
	  existing test STORNIERT order) rendered correctly in the brand-
	  facelifted style; search for "Test" correctly narrowed Anfragen to
	  the matching row and Aufträge to "keine" (no ID match)
	•	found and killed one stale office-panel process left running from
	  earlier in the session (pre-facelift code, blocking port 8081) before
	  this verification — noted so it isn't mistaken for a real bring-up
	  issue later

Open
	•	push held pending owner/reviewer verdict per project workflow
	•	no Wochen-page / kiosk cross-link in the office panel (see above)

Must not be changed
	•	attention counts and Blocker column are read-only summaries of
	  existing accepted concepts (progression B7 / operational gate) — must
	  not become a third vocabulary; still just B7 progression on inquiry
	  views and the operational gate's own reasons on order views (§5)
	•	Diese Woche in the office panel stays derived-only, same guarantee as
	  the kiosk (effective versions only, cancelled excluded) — do not let
	  it show candidate/latest-historical versions

⸻

Entry 055

Date: 2026-07-07 — Persistent left sidebar nav (Start/Anfragen/Aufträge/Diese Woche/Rückrufe)
Scope: src/catering_system/ui/office_panel.py — _page() layout
Status: accepted

Meaning
	•	owner feedback: the single stacked page (attention bar, search, two
	  tables, mini-week) read as clutter ("сплошное нагромождение"). Chose
	  the narrower of two options offered: persistent sidebar with anchor
	  links on the existing single page, not a split into separate
	  Anfragen/Aufträge/Woche routes — smaller change, same content
	•	_page() (used by every page, not just "/") now wraps body in a
	  .sidebar + .content flex layout; sidebar targets are absolute
	  (/#anfragen, /#auftraege, /#diese-woche, /rueckruf) so it works
	  identically from any page, not just the queue
	•	dropped the old standalone "← Übersicht" link and the inline
	  "Rückrufe" link next to "+ Neue Anfrage erfassen" — both superseded by
	  the sidebar, would have been duplicate navigation

Completed
	•	full suite: 219 passed. One existing test
	  (test_diese_woche_shows_only_effective_orders_in_current_iso_week) had
	  to split on the id="diese-woche" attribute instead of the text
	  "Diese Woche" — that text now also appears in the sidebar link, which
	  precedes the real content in HTML source order and was breaking the
	  test's naive string-split isolation
	•	verified live: sidebar renders on the queue page in the brand style;
	  direct navigation to /rueckruf and to /#anfragen (anchor exists)
	  confirmed working

Must not be changed
	•	sidebar targets must stay absolute paths/anchors, not bare #fragments
	  — a bare "#anfragen" would only work from "/" itself, not from order/
	  inquiry/Rückrufe pages

⸻

Entry 056a

Date: 2026-07-07 — Sidebar Rückruf-Badge (task indicator, not a stat)
Scope: src/catering_system/ui/office_panel.py — _page(), fetch_rueckruf_count(), do_GET
Status: accepted

Meaning
	•	owner wants to see at a glance, from anywhere in the panel, whether
	  there are unhandled callbacks — without opening the Rückrufliste
	•	explicit framing: this is a task-count ("how many still need
	  handling"), not a statistics widget — zero open callbacks shows no
	  badge at all, same as "unconfigured"/"unreachable" (nothing to flag
	  either way, no need to distinguish those states visually)
	•	same data source as the Rückrufliste page itself
	  (fetch_missed_board/build_missed_board_items on auerswald-sync) — no
	  new business rule, fetch_rueckruf_count() is a one-line wrapper that
	  only takes the length
	•	still read-only: the badge never writes anything; POST /rueckruf/
	  resolve is unchanged

Completed
	•	no second request: /rueckruf reuses its own already-fetched items list
	  for the badge (no extra fetch); other pages fetch once via
	  fetch_rueckruf_count() to populate the badge, so every page render
	  makes at most one auerswald-sync request, not two
	•	the count is stored in a per-request module global
	  (_sidebar_rueckruf_count), set once in do_GET (or _error_page for the
	  do_POST error path) before any _page()-rendering call — safe only
	  because the server is single-threaded (Entry 048's own invariant);
	  chose this over threading every render method's signature to keep the
	  change narrow (owner: "не создавать отдельную бизнес-логику")
	•	graceful when auerswald-sync is unset/unreachable: badge simply does
	  not render (no warning icon chosen — quieter, matches the panel's
	  existing minimal style; a page-load error there was already handled
	  gracefully since Entry 053)
	•	tests: 3 new — no badge when unconfigured, badge count matches
	  Rückrufliste's own count and is visible from the Start page too (with
	  an explicit fetch-count assertion proving no second request), badge
	  disappears immediately after resolving the only open call. Full suite:
	  222 passed (was 219)
	•	verified live with a disposable synthetic stub (not the owner's real
	  auerswald-sync data, learning from the earlier incident): badge showed
	  "3" on both Start and Rückrufliste pages, dropped to "2" immediately
	  after clicking "Erledigt" on one row

Must not be changed
	•	_sidebar_rueckruf_count must only ever be set right before a
	  _page()-rendering call, never left stale across requests — relies on
	  the single-threaded, one-request-at-a-time server invariant (Entry 048)
	•	badge stays a task-count semantic (open work), not a general call
	  statistic — do not add total/answered/all-time counts to it later
	  without a fresh decision

⸻

Entry 056b

Date: 2026-07-07 — Office panel: safe UX labels + attention grouping
Scope: src/catering_system/ui/office_panel.py — display-only label mapping,
tests/unit/test_office_panel.py — assertions updated to match
Status: accepted (OFFICE_PANEL_SAFE_UX_LABELS_AND_GROUPING_V1, narrowed from
a larger reviewer proposal after explicit scoping — see below)

Meaning
	•	owner relayed an external reviewer's proposal to rebuild the office
	  panel as a task-queue ("Büro-Zentrale") with Angebot/PDF/Senden/
	  Ablehnen actions. Correctly flagged by the owner as partially crossing
	  frozen architecture boundaries before any code was written: Core has
	  no price/Angebot/PDF concept (that lives in the separate fingerfood-app,
	  no accepted bridge exists), no Inquiry "rejected" state exists, and
	  merging Anfragen/Aufträge into one list would blur the frozen
	  Inquiry(process truth)/Order(operational truth) vocabulary separation
	  (§5, "vocabularies not merged")
	•	narrowed, by explicit agreement, to a UI-only display-label pass: no
	  Core/domain/service/repository/schema changes, no new actions, no new
	  states, sections (Anfragen/Aufträge/Rückrufe) stay separate
	•	three separate label dicts, deliberately not merged, mirroring the
	  three vocabularies that must stay apart per §5:
	  - CALL_VERIFICATION_STATUS_LABELS (simple status, both Anfragen table
	    and Anfrage detail)
	  - READY_TO_SEND_BLOCKER_LABELS (operational gate, order views only —
	    Aufträge table's Blocker column and the order detail page)
	  - PROGRESSION_BLOCKER_LABELS (B7 progression, inquiry views only — the
	    "Konvertierung blockiert" list on the Anfrage detail page)
	  fallback for the two blocker dicts is `f"technischer Blocker: {code}"` /
	  `f"technischer Fortschritts-Blocker: {code}"` (owner's explicit
	  correction over a silent passthrough) — never crashes on an unmapped
	  code, and still tells the office it's looking at a real, if
	  untranslated, technical reason rather than hiding it entirely
	•	Anfragen table's "Auftrag" column: "ja" → a real "Auftrag öffnen" link
	  to the existing `/order/{id}` route (first linked order) when one
	  exists; unchanged "–" when none — pure navigation, not a new concept,
	  Inquiry and Order stay distinct rows in distinct tables
	•	added "Was braucht Aufmerksamkeit?" heading above the attention bar,
	  and a "N Rückrufe offen" card as its first entry — reuses
	  `_sidebar_rueckruf_count`, already fetched once per request for the
	  sidebar badge (Entry 055) before `render_queue()` runs; no second
	  auerswald-sync request. Card omitted when the count is None
	  (unconfigured/unreachable, same as the badge); unlike the other
	  attention cards, 0 is a real confirmed value here since it comes from
	  an external fetch rather than Core's own always-available data

Completed
	•	full suite: 222 passed (unchanged count — no test added or removed,
	  8 existing tests' assertions updated from raw codes to the new human
	  labels, per the agreed plan)
	•	verified live: Anfragen row shows "keine Rückrufprüfung nötig" and a
	  working "Auftrag öffnen" link to the real order route; a STORNIERT
	  order's Freigabe section shows "Versandfreigabe blockiert:" /
	  "Auftrag storniert" — no raw codes anywhere checked

Open
	•	push held pending owner/reviewer verdict per project workflow
	•	the larger reviewer proposal (Büro-Zentrale task queue, Angebot/PDF/
	  Senden, Wochenplanung day-view, Auftrag/Anfrage detail card) remains
	  out of scope; would need its own execution pack and, for the
	  Angebot/PDF/Senden parts specifically, a prior decision on a
	  configurator→Core bridge that does not exist today

Must not be changed
	•	CALL_VERIFICATION_STATUS_LABELS / READY_TO_SEND_BLOCKER_LABELS /
	  PROGRESSION_BLOCKER_LABELS must stay three separate dicts — never
	  merge them into one lookup, that would blur §5's vocabulary separation
	  even though this step is UI-only
	•	no Angebot/PDF/Senden/Ablehnen actions, no price display, no
	  configurator→Core bridge, no Core schema/domain changes, no merging
	  of Inquiry and Order into one entity — all explicitly out of scope for
	  this step per the owner's agreed framing

⸻

Entry 057

Date: 2026-07-08 — Office panel: Arbeitszentrale layout (§6a)
Scope: src/catering_system/ui/office_panel.py — render_queue() layout only,
tests/unit/test_office_panel.py — assertions updated, 2 tests added
Status: accepted (OFFICE_PANEL_NAVIGATION_RETHINK_PACK_V1, option (a): one
page, no new routes)

Meaning
	•	owner's live feedback on Entry 056: labels were clearer but the panel
	  still read as a tabular admin/DB view, not an office work surface.
	  Planning-only pack (OFFICE_PANEL_NAVIGATION_RETHINK_PACK_V1.md, repo
	  root) written first per explicit "не кодить" instruction, reviewed,
	  and confirmed (§6 option a) before any code
	•	attention cards reworded from state counters to actions: "Neue
	  Anfragen" → "Neue Anfragen prüfen", "ohne Druckbestätigung" →
	  "Druckbestätigung fehlt", "noch nicht operativ wirksam" → "Aufträge
	  noch nicht wirksam". "Versandfreigabe blockiert" unchanged (already
	  action-shaped). "storniert" card now conditional (only rendered when
	  count > 0) and reworded to "Stornierte Aufträge prüfen" — a zero-count
	  card is not an action item
	•	"Diese Woche" table moved directly under the attention bar (was at the
	  page bottom) — same query (WochenuebersichtService.get_week_overview),
	  only position changed
	•	new "Wo gibt es Blocker?" short list, reusing the already-computed
	  `blockiert` orders (kitchen_print_not_confirmed is already one of
	  evaluate_ready_to_send's reasons, so `ohne_druck` is already a subset
	  of `blockiert` — no union needed, no new query)
	•	Anfragen/Aufträge table columns reordered, ID demoted to a trailing
	  link column: Anfragen is now Datum/Ort/CRM-Stufe/Verifizierung/
	  Auftrag/ID; Aufträge is now Freigabe/Blocker/Anfrage/Bestätigt/ID
	•	"Wirksam" header/values renamed to "Bestätigt" / "bestätigt" /
	  "noch nicht bestätigt" — display text only, the underlying boolean
	  (`o.effective_order_version_id is not None`) is untouched
	•	explicitly NOT done, per the pack's §5 ("looks small, is not in
	  scope"): no "Kunde" column — no customer display-name field exists on
	  Inquiry/Order, only the opaque, never-rendered customer_linkage dict;
	  adding one needs its own domain decision or a CRM bridge, neither of
	  which this step touches
	•	full tables (Anfragen/Aufträge) stay on the same page at the bottom,
	  same `id="anfragen"`/`id="auftraege"` anchors — sidebar nav unchanged,
	  no new routes (§6 option a, not b)

Completed
	•	full suite: 224 passed (222 + 2 new: Blocker-list-empty-then-populated
	  coverage folded into existing attention tests; new tests for the
	  conditional storniert card and for ID-last column order)
	•	verified live: attention cards read as actions, Diese Woche sits above
	  the full tables, "Wo gibt es Blocker?" renders "keine Blocker." when
	  empty, both tables show ID as the last column, Aufträge shows
	  "bestätigt"/"noch nicht bestätigt" instead of "ja"/"–"

Open
	•	push held pending owner/reviewer verdict per project workflow
	•	§6 option (b) — separate `/anfragen` and `/auftraege` routes instead
	  of one page — deferred; only worth it if option (a) still doesn't feel
	  like enough once seen live over time
	•	customer display-name column: needs its own Core domain decision
	  (add a field to Inquiry) or a CRM-bridge decision — neither exists;
	  not started

Must not be changed
	•	no Angebot/PDF/Senden/Ablehnen actions, no price display, no
	  configurator→Core bridge, no Core schema/domain/service/repository
	  changes — this step is office_panel.py HTML/layout and label text only
	•	Anfragen and Aufträge stay visually and structurally separate — no
	  row, card, or table mixes Inquiry and Order (§5, "vocabularies not
	  merged")
	•	no customer-name field invented client-side — customer_linkage stays
	  opaque and unrendered until a real decision is made

⸻

Entry 058

Date: 2026-07-08 — Office panel: Action Dashboard (§11 addendum)
Scope: src/catering_system/ui/office_panel.py — new routes, queue rendering,
version-target resolution; tests/unit/test_office_panel.py — migrated +
14 new tests
Status: accepted (OFFICE_PANEL_NAVIGATION_RETHINK_PACK_V1 §11–§16, narrow
diff plan reviewed before code)

Meaning
	•	Startseite (`GET /`) no longer shows full Anfragen/Aufträge tables or
	  a search box. It shows three action queues, top 5 rows each with an
	  "Alle anzeigen" link to the full list: Rückruf nötig, Neue Anfragen,
	  Aufträge mit nächstem Schritt. §6a's "Wo gibt es Blocker?" block is
	  removed, replaced (not duplicated) by the richer "Aufträge mit
	  nächstem Schritt" queue — same underlying `blockiert` list, one
	  primary action per row instead of just a static reason
	•	two new routes carry the full lists moved out of the Startseite,
	  verbatim (same columns/order as §6a): `GET /anfragen`, `GET
	  /auftraege`, each with its own search box (search no longer lives on
	  the dashboard — a top-5 action queue isn't something you text-search,
	  a full list is). Sidebar nav updated from `#anfragen`/`#auftraege`
	  anchors to the real routes
	•	`/` now fetches the full `fetch_missed_board(...)` result (not just
	  the lightweight count) — one request still, reused for both the
	  sidebar badge and the queue's top-5 rows. `items is None`
	  (unconfigured/unreachable) omits the whole "Rückruf nötig" block, same
	  graceful-degrade convention as the badge — the rest of the Startseite
	  keeps rendering, not an error page
	•	`GET /inquiry/new?phone=...` shows the number as read-only page
	  context ("Anruf von: ...") above the form, used by the Rückruf
	  queue's "Anfrage erfassen" link. Never written anywhere: Inquiry
	  (domain/inquiry.py) has no phone/contact field at all, so there was
	  nowhere to prefill it into even if we wanted to. No auto-create —
	  the office worker still fills in and submits the form themselves
	•	`_next_step_action()`: resolves one primary button per "Aufträge mit
	  nächstem Schritt" row. Caught during implementation, not before: an
	  earlier version of this logic (still in an earlier draft of the pack)
	  picked the action from `evaluate_ready_to_send(...).reasons[0]`
	  directly — wrong, because `operational_core_service.
	  make_order_version_effective()` itself refuses a version whose
	  kitchen print isn't confirmed (raises ValueError), while a freshly-
	  converted order's first READY_TO_SEND reason is `no_effective_version`,
	  not `kitchen_print_not_confirmed` (the facts check runs in that
	  order). Following reasons[0] literally would have shown "Wirksam
	  machen" before the version was even printed — a button that fails the
	  instant it's clicked. Fixed to resolve straight from the target
	  OrderVersion's own fields (kitchen_print_confirmed_at, then
	  effective_order_version_id) instead — pack §14 corrected to match.
	  Target version = `candidate_order_version_id` if it names a real
	  version of this order, else the highest `version_number` (display
	  fallback, not new truth — the field itself is documented in
	  domain/order.py as "office-side progression hint"). Note:
	  candidate_order_version_id is currently never set through the office
	  panel UI (OrderService.set_candidate_order_version is service-layer
	  only, unwired) — so today the fallback path is the one actually
	  exercised; the candidate-preference branch is forward-compatible, not
	  dead weight
	•	kiosk deep link: single `--kiosk-url`/`KIOSK_URL` config (same
	  pattern as `--auerswald-url`), threaded through
	  make_office_panel_handler/create_office_panel_server/main(), stored
	  once on `OfficePanel.kiosk_url`. Empty by default → no link shown.
	  This is the only "full Woche" surface — no new office-panel route,
	  per OFFICE_PANEL_EXECUTION_PACK_V1 §6 (Wochenübersicht stays
	  kiosk-owned, panel may at most link to it)

Completed
	•	full suite: 236 passed (222 baseline + 2 from §6a + net-new additions
	  this step: migrated 3 tests to the new routes, added 14 new tests —
	  Rückruf-queue-from-stub, degraded-source-survives, kiosk-link
	  present/absent, phone-hint-writes-nothing, top-5-cap-with-Alle-
	  anzeigen, and five direct `_next_step_action()` tests covering
	  candidate-preferred / latest-fallback / foreign-candidate-fallback /
	  print-before-effective-ordering / no-versions-empty-string)
	•	verified live: Startseite shows the three queues (no "Wo gibt es
	  Blocker?"), `/anfragen` and `/auftraege` render the full tables with
	  working search, sidebar links point at the real routes

Open
	•	push held pending owner/reviewer verdict per project workflow
	•	kiosk cross-service link mechanics for the real Lenovo deployment
	  (base URL value) — local dev only exercised via an explicit
	  `--kiosk-url` test value; no real port/URL committed anywhere
	•	row-count cap (5) and search relocation were both explicit owner
	  decisions this step, not left implicit — see
	  OFFICE_PANEL_NAVIGATION_RETHINK_PACK_V1 §11–§16 for the full reasoning
	  trail

Must not be changed
	•	no Angebot/PDF/Senden/Ablehnen/Preise, no Core schema/domain/service/
	  repository change, no configurator→Core bridge
	•	Rückruf/Neue-Anfragen/Aufträge queues stay three visually distinct
	  blocks — never merged into one list (§5)
	•	no automatic Inquiry creation from a missed call; no phone/contact
	  field added to Inquiry
	•	`_next_step_action()` must keep resolving from the target
	  OrderVersion's own fields (print-confirmed, then effective), never
	  from `evaluate_ready_to_send(...).reasons[0]` directly — that
	  ordering mismatch is exactly the bug this entry fixed


Entry 059

Date: 2026-07-14 — Core Office API, Phase 1 (dormant)
Scope: PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 Phase 1 only —
src/catering_system/repositories/core_transaction.py,
src/catering_system/repositories/office_api_ledger.py,
src/catering_system/ui/office_api.py + office_api_views.py, migration edits to
sqlite_order_repository.py (orders migration 6) and sqlite_inquiry_repository.py;
infra/systemd/catering-office-api.service, .env.example, docs/api/core-office-api.md,
CHANGELOG, docs/decisions ADR-011. Tests: tests/unit/test_office_api.py,
test_office_api_views.py, test_core_transaction.py (44 new). No deployment,
no push.
Status: code accepted by local quality gate; external Phase-1 review verdict
still pending (push held per project workflow)

Meaning
	•	the office panel's in-process Core access is replaced going forward by
	  a bearer-gated, Tailscale-only Core Office API on the Lenovo address
	  `100.109.6.74:8084` (stdlib `http.server`, single-threaded per
	  Entry 048 sqlite3 affinity). Phase 1 ships it dormant: the panel is
	  unchanged and nothing consumes the API yet (that is Phase 2's
	  `RemoteCoreClient`, not this step). Boundary supersession recorded as
	  ADR-011
	•	transaction coordinator (core_transaction.py): one owned SQLite
	  connection shared by inquiry repo, order repo and the command ledger.
	  `CoreCommandExecutor.run` owns `BEGIN IMMEDIATE`/`COMMIT`/`ROLLBACK`
	  so a precondition read, the business write and the ledger insert are
	  one atomic unit — all durable or nothing. Repositories keep their
	  autocommit behaviour when used standalone (tested); only the
	  externally-owned mode suppresses it
	•	deferred events: services `_emit` into a `DeferredEventSink` buffer
	  during the transaction; the buffer flushes only after a successful
	  COMMIT and is discarded on rollback — an event escaping a rolled-back
	  transaction would announce a change that never happened (pack §6.1,
	  round-3). The fixed `command committed` log line is likewise emitted
	  only post-COMMIT and carries only opaque ids (permitted per §5); no
	  contact/address/payload/token ever leaves the process
	•	idempotency ledger `office_api_commands` lives in `core.db`
	  (component `office_api`, migration 1, same fail-closed runner as every
	  Core component). Canonical fingerprint = SHA-256 over
	  {route_template, path_ids, args, expect, client_id}. Same command_id +
	  same fingerprint → the recorded minimal §4.4 body verbatim, no
	  re-evaluation; same command_id + different fingerprint →
	  `409 command_id_conflict`. Ledger stores IDs/timestamps only, no PII
	•	double-convert closure: orders migration 6 adds partial UNIQUE
	  `idx_orders_active_source_inquiry ON orders(source_inquiry_id) WHERE
	  cancelled_at IS NULL`, with a fail-closed pre-migration duplicate check
	  (aborts if any inquiry already has >1 active order — precedent:
	  inquiries migration 3). The convert command also checks for an active
	  order inside its transaction → `409 already_converted`; the index is
	  the backstop. Re-conversion after Storno keeps working
	•	SQLite contention: the API connection sets `busy_timeout` to 2 s
	  (deliberately below the panel's 5 s command timeout). A
	  locked/busy error surviving the timeout rolls back and maps to
	  `503 {"error":"core_busy"}` + `Retry-After: 1`; the panel retries with
	  the same command_id, safe by the ledger
	•	transport (§4.0) faithfully implemented: bearer checked first via
	  `hmac.compare_digest` on every method incl. explicit do_HEAD/do_OPTIONS
	  (missing and wrong token are the same constant `401` before any
	  routing/parsing); HEAD suppresses the body but keeps the exact
	  Content-Length; all responses (errors too) carry
	  `application/json; charset=utf-8`, correct Content-Length,
	  `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`; strict
	  envelope/query parsing (unknown/duplicate keys and params → 400, exact
	  types, no coercion), 415/413/405/404 per the error map; list orderings,
	  idempotent-repeat semantics, ready-on-unknown-order and next-action
	  resolution reproduce the current panel exactly (§3.10 parity)

Completed
	•	full quality gate green: ruff clean, mypy clean (64 files), pytest
	  550 passed, coverage 92.6% (fail_under 90). §9 acceptance items each
	  have a test: auth-first constant-401, HEAD/OPTIONS, transport/envelope
	  strictness, pagination + honest total_count, embedded-list caps +
	  truncation flags, QueueView + next-action + Europe/Berlin week +
	  search parity, idempotency replay/conflict, crash-window
	  business+ledger atomicity, double-convert index + migration
	  duplicate pre-check, stale_state preconditions, cancelled-order gates,
	  lock→503→safe-retry, no-PII logs, token-refusal startup
	•	packaging: systemd unit `catering-office-api.service` (User=viktor,
	  live Lenovo paths, root-owned EnvironmentFile mode 600 holding
	  OFFICE_API_TOKEN — never argv/Git/logs); `.env.example` gains
	  OFFICE_API_TOKEN; operator summary docs/api/core-office-api.md linked
	  from the docs index; CHANGELOG Unreleased entry; ADR-011

Open
	•	external Phase-1 review verdict not yet recorded; push held pending it
	  (project workflow: pack → review → freeze → code → verdict → push)
	•	Phase 2+ untouched by design: no `RemoteCoreClient`, no panel remote
	  mode, no dual-mode contract suite, no Proxmox provisioning, no VPS or
	  production deploy
	•	the API `main()` binds `100.109.6.74:8084` — a deploy-time Tailscale
	  address; it will only bind on the Lenovo. Nothing was deployed

Must not be changed
	•	Phase 1 stays dormant: the office panel keeps its direct-DB access
	  until Phase 2; both migrations are additive and harmless to direct mode
	•	the command ledger stays in `core.db` and is written in the same
	  transaction as the business change — never a second store, never a
	  separate commit
	•	events stay post-COMMIT only; `command committed` stays post-COMMIT
	  only; no contact/address/payload/token in any log
	•	no generic CRUD, no SQLite transfer or DB replication to Proxmox; the
	  configurator never calls Core; the API makes no outbound HTTP


Entry 060

Date: 2026-07-14 — Core Office API Phase 1: reviewer round-4 corrections
Scope: src/catering_system/ui/office_api.py (validation + response cap only),
tests/unit/test_office_api.py (+4 regression tests), docs/api/core-office-api.md,
CHANGELOG. No schema/service/migration change; no push.
Status: local quality gate green; external Phase-1 verdict still pending

Meaning — four contract gaps the green suite did not catch, found in review:
	•	response 512 KiB cap (pack §4.0) was declared but not enforced. A
	  legacy Core row with a long text (the API's input caps bound only new
	  writes) could form a read body over the cap. `_respond` now measures
	  the JSON before sending and, above 512 KiB, fails closed with
	  `500 internal` — checked pre-send so the caller's handler emits a clean
	  error, no partial/oversized body. Command responses are minimal and
	  cannot trip it
	•	uuid validation accepted any UUID; pack §4.3 requires uuid4 for
	  command_id, and every Core-minted id is uuid4, so `_v_uuid` now rejects
	  non-v4 (command_id, order_version_id args, print-data version) — no
	  real id is refused
	•	`expect` timestamps accepted naive/non-UTC values; pack §4.1 fixes
	  ISO-8601 UTC-with-offset. `_v_datetime` now rejects a missing or
	  non-zero offset (utcoffset() != 0) → `400`, before the stale-state
	  compare. Verified both compared domain timestamps (inquiry + order
	  updated_at) are tz-aware UTC, so the tighter check never crashes the
	  comparison
	•	update wiped intake fields when they were omitted (absent → "" →
	  overwrite). Reviewer rule adopted: on update an omitted intake field
	  keeps its stored value (passed through the service's existing _UNSET-
	  style partial update), an explicit "" clears, an explicit `null` is
	  `400` (exact types, no coercion). The null→"" coercion helper
	  (`_v_optional_str`) was removed; create keeps default "" for absent,
	  and now also rejects explicit `null`

Completed
	•	ruff clean, mypy clean (64 files), pytest 554 passed (550 + 4 new
	  regressions: over-cap read → 500; non-v4 uuid → 400 across command_id /
	  version param / order_version_id arg; naive & +02:00 expect → 400;
	  update intake preserve/clear/reject-null), coverage 92.7%
	  (office_api.py 91.4%)

Open
	•	external Phase-1 verdict still pending; push still held per the project
	  workflow (pack → review → freeze → code → verdict → push)

Must not be changed
	•	these are behaviour tightenings of the frozen contract, not new
	  surface: no route, shape, or service semantics changed; input-cap
	  numbers (1000/5000/2000/200, 64 KiB body, 100 list, 50/200/100 caps)
	  are untouched
	•	`_v_datetime` must keep rejecting naive/non-UTC `expect` values;
	  `_v_uuid` must keep requiring version 4; update must keep the
	  preserve/clear/reject-null intake merge — each is exactly a round-4
	  fix with its own regression test


Entry 061

Date: 2026-07-14 — Core Office API Phase 2: RemoteCoreClient + panel dual mode
Scope: PROXMOX_OFFICE_SERVER_CORE_API_PACK_V1 Phase 2 only —
src/catering_system/ui/remote_core_client.py (audited and fixed, was an
uncommitted Codex draft), src/catering_system/ui/office_panel.py (dual-mode
constructor, hidden idempotency fields on every mutating form, main() env
wiring), src/catering_system/ui/office_panel_http.py (remote passthrough,
begin_request() per request, RemoteCoreError degradation handling). Tests:
tests/unit/test_remote_core_client.py (new, 27), tests/unit/
test_office_panel_remote.py (new, 15), one-line fix in test_office_api_views.py
(OfficePanel.__new__ bypass needed `_remote = None`). Docs: .env.example,
docs/api/core-office-api.md, CHANGELOG. No deploy, no push, no Proxmox VM.
Status: local quality gate green; external Phase-2 review verdict pending

Meaning
	•	found src/catering_system/ui/remote_core_client.py uncommitted at
	  session start — a prior Codex session had started Phase 2 and run out
	  of budget. Audited it fully against the frozen contract rather than
	  trusting it; three real defects fixed before building on it:
	    1. `_write_forbidden(self) -> NoReturn` was bound directly as
	       `save`/`update`/`save_order_with_initial_version`/`update_order`/
	       `append_order_version`/`update_order_version` — calling any of
	       them with the Protocol's real arguments raised a bare arity
	       TypeError instead of the intended RuntimeError, and the
	       signature mismatch would have failed structural typing the
	       moment the client was assigned to an `InquiryRepository`/
	       `OrderRepository`-typed parameter. Replaced with six explicit
	       stub methods matching each Protocol signature exactly.
	    2. `get_order_version(order_version_id)` only ever searched
	       already-fetched order details — correct for ProgressionService's
	       call pattern (always preceded by get_order() on the same order in
	       the same call), silently wrong for
	       WochenuebersichtService.get_week_overview(), which loops every
	       order calling get_order_version(effective_id) without a prior
	       per-order fetch. In remote mode this always returned an empty
	       Wochenübersicht regardless of real data. Fixed with a bounded
	       fallback: after list_orders() records every known order_id, a
	       cache miss walks the remaining known orders (fetching each
	       detail at most once) until the version turns up.
	    3. The severe one, found only by exercising a full command-then-
	       reread cycle against a real Core Office API server (not by
	       isolated client tests with canned responses):
	       `create_relevant_order_change_version` and `confirm_kitchen_print`
	       resolved their result via
	       `next(generator, cast(T, _bad_response()))` — Python evaluates
	       every argument to `next()`, including the default, before
	       calling it, so the always-raising `_bad_response()` fired
	       unconditionally regardless of whether the generator had a match.
	       Both real routes were **permanently broken** — every version
	       creation and every print-confirm failed with `invalid_response`
	       (rendered by the panel as the generic degradation page) even
	       though the underlying Core command had already succeeded.
	       Rewritten as a plain loop that returns on match and calls
	       `_bad_response()` only when the loop is exhausted. Also removed
	       `queue_view()` — a `GET /office/v1/queue` wrapper the draft added
	       but `office_panel.py`'s `render_queue()` never calls (it
	       recomputes the dashboard itself from raw repo reads, exactly as
	       in direct mode) — dead, untested surface in a security-sensitive
	       file
	•	dual-mode wiring: `OfficePanel.__init__` gained a keyword-only
	  `remote: RemoteCoreClient | None` parameter. `remote=None` (default)
	  is untouched — same `InquiryService`/`OrderService`/
	  `OperationalCoreService` construction as before, byte-identical HTML
	  (proved by running the full pre-existing 109-test direct-mode suite
	  unchanged). `remote=<client>` swaps in the client's own command-backed
	  service facades for writes while reusing the SAME client for the
	  repo-shaped reads `render_queue`/`render_anfragen`/`render_auftraege`/
	  `render_inquiry`/`render_order` already call directly — no business
	  logic (ID minting, defaults, timestamps) ever runs against the remote
	  client. `ProgressionService`/`WochenuebersichtService` are safe to
	  keep constructing over the same client since they're pure reads
	•	idempotent forms: `OfficePanel._command_fields()` returns "" in
	  direct mode (empty in all existing HTML, proven by the same unchanged
	  109-test suite) and, in remote mode, mints a fresh `_command_id` per
	  render plus one `_expect_<field>` hidden input per precondition the
	  route needs (`updated_at`, `latest_version_number`,
	  `effective_version_id`). `OfficePanel.begin_request(form)` is a no-op
	  in direct mode; in remote mode it resets the client's per-request read
	  caches and stashes the submitted form so the command facades can read
	  back `_command_id`/`_expect_*`. `office_panel_http.py` calls it once
	  per request (empty form on GET, the parsed form on POST, right after
	  the CSRF check) — the only two touch points needed
	•	degradation: `office_panel_http.py` catches `RemoteCoreError`
	  ahead of the existing generic `ValueError` handler (it subclasses
	  ValueError, so order matters); `.unavailable` cases (unreachable,
	  timeout, redirect, malformed/oversized response) render the fixed
	  «Core nicht erreichbar — nichts wurde gespeichert» page at 503; a
	  genuine remote 4xx/409 business rejection falls through to the
	  existing generic error rendering, unchanged
	•	`main()`: `--core-office-api-url` is a CLI flag (URL isn't secret);
	  `CORE_OFFICE_API_TOKEN` is env-only, never argv, matching the API
	  server's own `OFFICE_API_TOKEN` convention. Exactly one of
	  URL/token set → `SystemExit` before anything else runs (no db open,
	  no bind). `--db` is no longer required — remote mode never touches
	  `SQLiteInquiryRepository`/`SQLiteOrderRepository` at all

Completed
	•	ruff clean, mypy clean (65 files), pytest 596 passed (554 baseline +
	  42 new: 27 in test_remote_core_client.py covering redirect-refusal +
	  bearer-never-leaked, timeout/unreachable, malformed/non-object/wrong-
	  content-type/oversized responses, uuid4 command_id, the write-tripwire
	  regression, and the two eager-evaluation regressions against a real
	  API server; 15 in test_office_panel_remote.py covering direct-vs-
	  remote read parity on one shared seeded core.db — dashboard, search,
	  order/inquiry detail, print-data, Rückruf-stays-local — a full create→
	  verify/update→convert→print-confirm→ready→effective→cancel write flow,
	  same-command-id-and-preconditions retry, the German degradation page,
	  remote mode never touching SQLite, and half-config startup rejection),
	  coverage 91.7% (remote_core_client.py 83.2%, up from 78.3% before
	  extending the write-flow test to also cover update/verify/ready)

Open
	•	external Phase-2 review verdict not yet recorded; push held pending
	  it, same as Phase 1 (pack → review → freeze → code → verdict → push)
	•	not deployed: no Proxmox VM (Phase 3), no isolated-Core rehearsal
	  (Phase 4), no live cutover (Phase 5) — this entry is code + tests only

Must not be changed
	•	direct mode (`remote=None`/no env vars) must stay byte-identical —
	  verified by running the pre-existing test_office_panel.py suite
	  unmodified; any future change here must keep that suite green as-is
	•	writes in remote mode must keep going only through the command
	  facades (`_RemoteInquiryService`/`_RemoteOrderService`/
	  `_RemoteOperationalCoreService`), never by constructing
	  `InquiryService`/`OrderService`/`OperationalCoreService` directly
	  against the remote client — that would reproduce Core's business
	  rules on Proxmox, which the pack forbids
	•	the three remote_core_client.py fixes above are exactly that —
	  bug fixes to match the frozen contract, not new behavior; no new
	  route, shape, or precondition was added
