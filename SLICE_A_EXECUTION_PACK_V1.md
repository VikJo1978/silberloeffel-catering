SLICE_A_EXECUTION_PACK_V1

0. Purpose

This document defines the execution pack for Slice A of Catering System MVP.

Its purpose is:
	•	to turn the frozen architecture into the first controlled implementation step
	•	to define the exact execution boundary of Slice A
	•	to prevent premature expansion into later operational slices
	•	to provide a practical implementation target without redesigning the system

This document is execution-oriented, but remains bounded by the frozen architecture package.

⸻

1. Slice identity

Slice name
Slice A — External intake baseline

Primary goal
Establish controlled inquiry intake through the external intake path and office-facing intake creation.

Primary result
A new inquiry can enter the system in a controlled way from all allowed channels, without creating operational truth outside Core architecture and without exposing direct browser-to-HubSpot secrets.

⸻

2. Frozen dependencies

Before executing Slice A, the following documents are binding:
	•	MASTER_ARCHITECTURE_INDEX_V1
	•	STATE_MODEL_V2
	•	COMMANDS_AND_EVENTS_V1
	•	ENTITY_AND_FIELD_CONTRACTS_V1
	•	IMPLEMENTATION_SLICES_V1
	•	TEST_AND_ACCEPTANCE_MATRIX_V1

Slice A must not contradict any of these.

⸻

3. Exact scope of Slice A

3.1 In scope

Slice A includes only:
	•	Wix inquiry flow baseline
	•	External Secure Intake Layer baseline
	•	HubSpot intake creation baseline
	•	controlled inquiry intake from allowed channels:
	•	wix_form
	•	email
	•	phone
	•	manual
	•	minimal Inquiry creation/update path
	•	minimal customer linkage at inquiry level
	•	inquiry entry into frozen inquiry / CRM axis

3.2 Out of scope

Slice A does not include:
	•	Core operational truth ownership for orders/versions
	•	order creation as accepted operational truth
	•	OrderVersion activation
	•	mandatory kitchen print acceptance
	•	effective operational switching
	•	READY_TO_SEND logic
	•	Wochenübersicht generation
	•	kitchen kiosk behavior
	•	buffet cards
	•	advanced office workflow
	•	driver logic
	•	AI
	•	infrastructure redesign

⸻

4. Slice A domain target

By the end of Slice A, the system must be able to do the following:
	•	accept inquiry input through the allowed channels
	•	pass inquiry data through a controlled External Secure Intake Layer where applicable
	•	create/update inquiry records in office-facing flow
	•	preserve inquiry source
	•	preserve inquiry-level customer linkage
	•	place inquiry into the frozen CRM/inquiry process axis
	•	keep CRM as office-facing visibility, not operational truth

It must not claim that:
	•	kitchen operational truth has been established
	•	order/version truth is already active
	•	any kitchen acceptance has happened

⸻

5. Entities touched

Slice A may touch only these domain entities directly:
	•	Inquiry
	•	Customer linkage context only

Slice A must not establish full operational behavior for:
	•	Order
	•	OrderVersion
	•	WochenübersichtVersion
	•	WochenübersichtEntry

⸻

6. Commands and events touched

6.1 Commands allowed in Slice A
	•	CreateInquiry
	•	UpdateInquiry
	•	VerifyCustomerByCall where needed for inquiry-level progression only

6.2 Events expected in Slice A
	•	InquiryCreated
	•	InquiryUpdated
	•	CustomerCallVerified where applicable

6.3 Commands explicitly deferred beyond Slice A
	•	ConvertInquiryToOrder
	•	CreateInitialOrderVersion
	•	CreateRelevantOrderChangeVersion
	•	all mandatory kitchen print commands
	•	all effective switch commands
	•	all READY_TO_SEND commands
	•	all Wochenübersicht commands

⸻

7. Minimal field scope for Slice A

The minimum inquiry-level field scope for Slice A should align with ENTITY_AND_FIELD_CONTRACTS_V1.

Required inquiry-level fields:
	•	inquiry_id
	•	inquiry_source
	•	customer_linkage
	•	event_date
	•	time_window_text
	•	location_text
	•	guest_count_estimate
	•	planning_mode
	•	crm_stage
	•	call_verification_required
	•	call_verification_status
	•	created_at
	•	updated_at

Optional:
	•	notes_text

Slice A must not prematurely expand into order/version-only field responsibility.

⸻

8. External Secure Intake Layer baseline

8.1 Role

External Secure Intake Layer is a frozen architectural role.

For MVP, this role may be implemented via Cloudflare Worker.

8.2 Required behavior

The intake layer must:
	•	receive external inquiry input where applicable
	•	validate/sanitize/minimally normalize inquiry data
	•	protect secrets from direct browser exposure
	•	pass inquiry data into controlled office-facing flow

8.3 Forbidden behavior

The intake layer must not:
	•	become operational truth
	•	bypass controlled inquiry flow
	•	store business logic that belongs to Core operational truth
	•	expose direct browser-to-HubSpot secret usage

⸻

9. Channel handling baseline

Slice A must explicitly support these channels:

9.1 wix_form

Baseline external form intake path.

9.2 email

Office-controlled inquiry capture into the same inquiry flow.

9.3 phone

Office-controlled inquiry capture into the same inquiry flow.

9.4 manual

Manual office entry into the same inquiry flow.

All four channels must enter one controlled inquiry model.
No channel may create a separate unmanaged truth path.

Support for email, phone, and manual does not require fully automatic intake in Slice A.
For Slice A, office-controlled capture into the same inquiry model is sufficient, provided the same frozen inquiry / CRM axis is used.

⸻

10. CRM boundary for Slice A

CRM in Slice A may:
	•	show inquiry visibility
	•	hold office-facing process stage
	•	support inquiry handling

CRM in Slice A may not:
	•	become operational truth
	•	claim order/version truth ownership
	•	bypass future Core-based operational rules

Slice A must preserve the frozen formula:

Inquiry / CRM axis is office-facing process truth, not kitchen operational truth.

⸻

11. Acceptance criteria

Slice A is accepted only if all of the following are true:
	•	inquiries can be created from wix_form, email, phone, and manual
	•	support for email, phone, and manual may be implemented through office-controlled capture into the same inquiry model
	•	inquiry enters the frozen inquiry / CRM axis
	•	inquiry source is preserved correctly
	•	inquiry-level customer linkage is preserved
	•	direct browser-to-HubSpot secret exposure does not exist
	•	CRM remains office-facing inquiry/process visibility only
	•	Slice A does not establish kitchen operational truth
	•	Slice A does not bypass future Core ownership
	•	Slice A does not introduce hidden order/version behavior

⸻

12. Must-fail conditions

Slice A must be considered not accepted if any of the following happens:
	•	only wix_form works while email / phone / manual are ignored as controlled channels
	•	a channel creates a separate unmanaged intake truth path
	•	direct browser-to-HubSpot secret exposure exists
	•	inquiry creation bypasses the controlled inquiry / CRM axis
	•	CRM is treated as operational truth
	•	Slice A implicitly creates active order truth
	•	Slice A introduces OrderVersion activation behavior
	•	Slice A mixes inquiry flow with mandatory kitchen acceptance logic
	•	Slice A expands into later slices under the label of “intake convenience”

⸻

13. Explicit freeze boundaries

Slice A must preserve these boundaries:
	•	no order activation
	•	no OrderVersion activation
	•	no mandatory kitchen print acceptance
	•	no effective switching
	•	no READY_TO_SEND semantics
	•	no Wochenübersicht generation
	•	no kiosk logic
	•	no hidden move of Core away from kitchen Lenovo
	•	no redesign of External Secure Intake Layer role

⸻

14. Recommended execution order inside Slice A

Recommended internal execution order:
	1.	establish minimum inquiry field contract
	2.	establish intake handling for wix_form
	3.	establish same-model intake handling for email
	4.	establish same-model intake handling for phone
	5.	establish same-model intake handling for manual
	6.	establish External Secure Intake Layer secret boundary
	7.	establish HubSpot office-facing inquiry creation/update baseline
	8.	verify inquiry enters frozen CRM/inquiry axis
	9.	verify no operational truth leakage is introduced

This order may be operationally adjusted, but the boundary of Slice A must remain intact.

⸻

15. Minimal deliverables for Slice A

Slice A should produce at least:
	•	controlled intake path for all allowed inquiry channels
	•	minimal inquiry creation/update capability
	•	documented External Secure Intake Layer boundary
	•	documented CRM office-facing boundary
	•	acceptance check against Slice A criteria
	•	no spillover into later slice behavior

⸻

16. What must not be changed while implementing Slice A

While implementing Slice A, the following must not be changed:
	•	STATE_MODEL_V2
	•	COMMANDS_AND_EVENTS_V1
	•	ENTITY_AND_FIELD_CONTRACTS_V1
	•	IMPLEMENTATION_SLICES_V1
	•	effective-switch invariant
	•	mandatory kitchen print requirement
	•	READY_TO_SEND blocked release semantics
	•	derived-only role of Wochenübersicht
	•	read-only MVP role of kitchen kiosk

⸻

17. Exit condition

Slice A is complete only when:
	•	intake from all allowed channels is controlled
	•	inquiry truth is normalized into one office-facing model
	•	external secret boundary is protected
	•	CRM remains non-operational truth
	•	later operational slices remain untouched

If any of these is missing, Slice A remains incomplete.

⸻

18. Next slice after acceptance

After Slice A is accepted, the next execution target is:

Slice B — Core domain baseline on kitchen Lenovo

That slice establishes:
	•	Core host baseline on kitchen Lenovo
	•	minimal domain model realization
	•	Order / OrderVersion baseline creation
	•	local operational truth ownership
