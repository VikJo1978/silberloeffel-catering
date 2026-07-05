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
