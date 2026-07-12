CONFIGURATOR_EXECUTION_PACK_V1

0. Purpose

Planning-only pack fixing the role of the fingerfood-app configurator
(separate repository, ~/fingerfood-app) inside this system's architecture.
The configurator's own WORKLOG already shares this project's frozen
vocabulary and self-limits correctly ("Configurator is not operational
truth... outcomes must land in Core under OrderVersion rules"); this pack
makes that relationship binding on THIS side too. Evidence rule as in
OPERATIONAL_CORE_EXECUTION_PACK_V1 §2.

1. Role fixed by this pack

	•	the configurator is the office's Angebot-phase editing surface: catalog
		browsing, offer composition, pricing preview, Angebotsvorschau — the
		tooling for CRM stages "Vorschlag vorbereiten" → "Angebot gesendet"
	•	it operates on the inquiry/CRM axis, strictly BEFORE operational truth:
		its output is an offer for a client, never an order for the kitchen
	•	it stays a separate repository and a separate deployable; it is not
		merged into this repo and does not import from it

2. Boundaries (binding)

	•	the configurator never writes into Core — no API bridge, no shared
		database, no file drop that Core ingests automatically
	•	configurator drafts (its Draft Storage) are never Orders, OrderVersions,
		or any Core truth — the office panel remains the only write surface
	•	the catalog (items.json / future catalog storage) never moves into Core:
		Core is not a CMS (same rule as public-site content, PUBLIC_SITE pack §8)
	•	configurator prices are vorläufig by definition; Core stores no prices
		under this pack — OrderVersion gains no price fields
	•	the configurator's "Neue Anfrage" form stays a local Gesprächsprotokoll /
		planning aid; Core inquiries are created only through the office panel
		(or the §5.3 public intake contract) — no third intake path arises
	•	no automated parsing of configurator exports into inquiries or orders —
		same hidden-bridge family as the forbidden email parser and CRM→Core
		sync (PUBLIC_SITE pack §5.2)

3. The known gap this pack points at (direction, not mechanism)

OrderVersion carries no dish/menu content; the Küchenzettel therefore prints
logistics (date, place, guests) but not WHAT to prepare. The composition
lives in the configurator (offer lines, composite items_included).

Direction fixed now: the accepted offer's composition must eventually reach
the kitchen sheet. Mechanism deliberately NOT fixed here — the implementation
step (§4) will choose between:
	•	(a) an optional free-text composition field on OrderVersion — an explicit,
		additive amendment of the frozen field contract, its own accepted step
		with WORKLOG entry (same procedure as kitchen_print_confirmed_at)
	•	(b) a separate printable attachment surfaced next to the Küchenzettel
		without touching the OrderVersion contract

Until then, the office carries composition manually (as today) — honest
interim, not a defect.

4. Phased plan

Now (this pack): accept roles and boundaries; no code anywhere.
After the observation window (each an own accepted step):
	•	composition seam V1 per §3 (this is the deferred "integration V1")
	•	single authoritative price calculator = configurator backend
		(direction already recorded in the configurator's WORKLOG 2026-07-05;
		its parity guard contains the duplication until then)
Much later (own packs, only on proven office need):
	•	structured menu lines in OrderVersion
	•	configurator reading (never writing) Core data for prefill

5. Must-fail conditions

	•	any configurator→Core write path appears without an accepted pack
	•	drafts or exports get treated as operational truth
	•	catalog or price data lands in Core
	•	a third inquiry intake path is created via the configurator
	•	the §3 mechanism gets implemented "quickly" during the observation window
