CONFIGURATOR_OFFICE_MANUAL_HANDOFF_PACK_V1

0. Purpose

Planning-only pack. Designs the first safe handoff step between the
configurator (fingerfood-app, Angebotsphase, separate repository) and the
office panel (controlled entry into Core), without touching Core truth.
Narrows CONFIGURATOR_EXECUTION_PACK_V1 §3's "known gap" direction into one
concrete, boundaried artifact: a proposal payload the configurator can export
and the office panel can display as a read-only preview. No write path is
opened by this pack. Evidence rule as in OPERATIONAL_CORE_EXECUTION_PACK_V1 §2.

⸻

1. Boundary

	•	configurator data is proposal data, never Core truth — this holds for
		every field in the payload, including event_date, guest_count, items,
		and prices; none of them become truth by virtue of being exported
	•	office preview is not truth — displaying an imported JSON payload in
		the office panel is a read-only rendering step, not a write, and not
		an implicit confirmation of anything it contains
	•	Core truth (Inquiry, Order, OrderVersion, print confirm, wirksam,
		READY_TO_SEND, Wochenübersicht, STORNO) appears only after a distinct,
		manual, office-initiated action — this pack defines no such action
	•	importing a JSON file, by itself, creates nothing in Core — no Order,
		no OrderVersion, no Inquiry; import means "render for inspection",
		nothing else
	•	this boundary matches CONFIGURATOR_EXECUTION_PACK_V1 §2's existing
		rule ("no automated parsing of configurator exports into inquiries or
		orders") — this pack narrows a future safe first step inside that
		frozen boundary, it does not loosen it

⸻

2. Proposal payload v1

Schema name: proposal_payload_v1. Produced by the configurator, consumed
(read-only) by the office panel.

{
  "schema_version": "proposal_payload_v1",
  "source": "fingerfood-configurator",
  "proposal_id": "optional-local-id",
  "title": "Angebot / Eventname",
  "event_date": "YYYY-MM-DD",
  "guest_count": 30,
  "selected_items": [
    {
      "name": "Mini Wraps",
      "quantity": 30,
      "unit_price": 2.9,
      "total_price": 87.0,
      "notes": "optional"
    }
  ],
  "calculated_total_net": 0,
  "calculated_total_gross": 0,
  "notes": "Freitext aus Angebotsphase"
}

Field rules:
	•	schema_version is mandatory — identifies this exact shape; any future
		v2 gets a new value, not an in-place mutation of v1's meaning
	•	source is mandatory and fixed to "fingerfood-configurator" for this
		pack — it marks every field below as proposal-phase data, not
		office-authored data, at the moment the office panel reads it
	•	proposal_id is optional and local to the configurator; it is not a
		Core identifier and must never be treated as one (no Inquiry/Order id
		collision risk because no Core row is created from it)
	•	title, event_date, guest_count, selected_items, calculated_total_net,
		calculated_total_gross, notes are all proposal data — see §1; none
		carry Core-field semantics (e.g. event_date is not an Order field
		until an office user manually enters an Order with that date)
	•	no field in this schema maps 1:1 or automatically to any Core field —
		that mapping, if it is ever built, is a separate, later, explicitly
		accepted pack (§4 does not authorize it)

⸻

3. Manual flow

	1.	configurator composes a proposal (existing Angebotsphase behavior,
		unchanged by this pack)
	2.	configurator exports it as a proposal_payload_v1 JSON file (mechanism
		— download, copy, etc. — is a configurator-side implementation detail,
		out of scope here)
	3.	office panel imports the JSON file (file picker / paste — office-panel
		implementation detail, out of scope here)
	4.	office panel renders it as a preview
	5.	the preview is explicitly labeled "proposal / import preview — not
		Core truth" wherever it is shown; this label is not optional styling,
		it is the mechanism that keeps §1 honest in the UI
	6.	the office user manually reviews the previewed data against reality
		(does the client actually want this, are the dates and counts right)
	7.	at this step, no button, link, or action in the office panel writes
		this data into Core — there is nothing to click that creates or
		changes an Inquiry, Order, or OrderVersion
	8.	Core objects are unchanged before, during, and after this flow

⸻

4. First accepted step

The smallest accepted step is documentation only:
	•	this pack (schema + boundary + manual flow + non-goals) merged as
		accepted design
	•	no code in this repository, the configurator repository, kitchen
		kiosk, or release/READY_TO_SEND logic changes as a result

Acceptance criterion (if a technical one is wanted, this is the only one):
	•	a markdown document describing boundary, schema, manual flow, and
		non-goals exists in this repository
	•	Core code (domain/services/repositories) is unchanged
	•	kitchen/kiosk/release logic is unchanged

Any future step that renders proposal_payload_v1 in an actual office panel
screen, or that lets the configurator produce a real export file, is its own
separate accepted step with its own WORKLOG entry — not authorized by this
pack on its own.

⸻

5. Non-goals / forbidden

This pack does not authorize, propose a mechanism for, or take a first step
toward any of the following. Each remains exactly as frozen by
CONFIGURATOR_EXECUTION_PACK_V1 and OPERATIONAL_CORE_EXECUTION_PACK_V1 unless
and until its own accepted pack says otherwise:
	•	auto-create Inquiry from an imported payload
	•	auto-create Order from an imported payload
	•	auto-create OrderVersion from an imported payload
	•	direct configurator write into Core (no API bridge, no shared database,
		no file drop Core ingests automatically)
	•	CRM → Core bridge
	•	treating a sent offer as truth
	•	treating a draft as truth
	•	auto-effective switch (wirksam)
	•	auto-READY_TO_SEND
	•	kitchen kiosk, Wochenübersicht, or release-logic changes of any kind
	•	a new source of truth alongside Core
	•	a large office-panel UI redesign (this pack is additive-only, scoped to
		one future read-only preview surface)
	•	recommendation or decision logic running inside Core

⸻

6. Exit

Complete when this document is merged as an accepted pack and no code has
changed. The next step — an actual read-only import/preview screen in the
office panel — needs its own narrow diff plan and its own WORKLOG entry,
following the same review-before-code discipline as the rest of this
project. This pack does not pre-approve that step's implementation details.
