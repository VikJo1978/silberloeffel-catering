# OFFICE_PANEL_UI_V2_IMPLEMENTATION_PACK_V1

Status: implementation-ready design pack, local and undeployed
Prepared: 2026-07-14
Project baseline: `20566dd` (`Prevent contradictory office actions`)
Source UI package: `/Users/viktorjohanson/office_panell/office-panel-ui-v2`

## 1. Purpose

Replace the current Office Panel presentation layer with the approved UI v2
visual system while preserving the existing Core, Core Office API, commands,
routes, security boundaries and operational truth.

This is a presentation migration, not a new workflow subsystem. The target is
one server-rendered UI shared by direct and remote modes. Demo text and static
prototype controls are not executable truth; existing Core-derived views and
command helpers remain authoritative.

No production code is changed by this pack itself.

## 2. Reviewed source baseline

The corrected external package was reviewed read-only after its five-point
correction pass. The reviewed inputs are pinned by SHA-256 so later source
drift is visible:

| Input | SHA-256 |
|---|---|
| `build.py` | `303b54a62af1255b2726ef192647dedd5045508f633277525817c80b3c950912` |
| `reference/office-panel-premium-prototype.html` | `4d6c42a7fd216ae9ea5e22ac4ad9c4aca451dda88abd83808ebfb022c385af2c` |
| `assets/office-panel-v2.css` | `2946e3eba73337b7b326d968e0ecfba4456af75601d7637d66e2ebf7ea74cce1` |
| `assets/office-panel-v2.js` | `771562ad4c7d79b7ebae9268deabff3c2ae9f7381ad23d8d98b6c3b25486d20e` |
| `assets/icons.svg` | `78267fb0c3fbe5cf8ce87a455550d6453fe7f36435f7591b023c7682091522b7` |

The correction pass is present:

- mobile navigation has a no-JS fallback and the drawer is progressive
  enhancement;
- Auftrag-Detail includes `Druck bestätigen` and does not expose premature
  `Wirksam machen`;
- active-Order CRM compatibility is documented as `Bestätigt / Auftrag`, with
  `active_order_crm_stage_conflict` as the remote Core rejection;
- the multi-page Anfragen screen uses `GET /anfragen?q=`;
- `event_date` is documented as required in both modes.

The external directory is a design source, not a runtime dependency. The
production project must not use symlinks, absolute references or runtime reads
from `/Users/viktorjohanson/office_panell`.

## 3. Scope

Included:

- v2 visual tokens, layout, cards, typography and inline SVG icons;
- a server-rendered shell with desktop navigation and no-JS mobile navigation;
- presentation replacements for Arbeitszentrale, Anfragen, Anfrage-Detail,
  Aufträge, Auftrag-Detail and Rückrufe;
- the existing current-week section on Arbeitszentrale, styled as v2;
- truthful server-side search forms;
- presentation-only labels, summaries, steppers and next-step cards derived
  from existing facts;
- direct/remote HTML parity, except for the existing remote hidden command and
  precondition fields;
- responsive and accessibility regression coverage;
- status documentation and manual acceptance instructions.

Not included:

- Phase 3B print-agent, heartbeat, Lenovo monitoring or Office attention API;
- new Core facts, statuses, tables, migrations or repositories;
- new CRM capabilities, contact model, call history, notes or follow-up dates;
- changes to kitchen agents, physical printers, kiosk or courier applications;
- a separate `/woche` route; the week remains on `/` and the full kitchen week
  remains the existing `kiosk_url` link;
- new search semantics or global search;
- a Core Office API expansion merely to make list cards richer;
- redesign of Neue Anfrage, Anfrage bearbeiten, Neue Version,
  Angebots-Import or the printable Küchenzettel in the first slices;
- mandatory JavaScript;
- push or deploy.

## 4. Non-negotiable invariants

### 4.1 Domain and workflow

1. `derive_inquiry_office_state()` remains the sole source for open Inquiry
   membership and its primary `verify` or `convert` action.
2. Rejected and already-converted Inquiries do not reappear in `Offene
   Anfragen`.
3. An active linked Order requires `crm_stage == ACTIVE_ORDER_CRM_STAGE`, i.e.
   `Bestätigt / Auftrag`. The form shows fixed text plus the existing hidden
   field, never an incompatible select.
4. Cancelled-only Order history preserves the existing explicit reconversion
   contract.
5. The target OrderVersion is chosen by the current candidate/highest-version
   display rule. No new active/effective status is introduced.
6. An unconfirmed target version may offer `Küchenzettel öffnen` and `Druck
   bestätigen`, but never `Wirksam machen`.
7. `Wirksam machen` appears only when the exact target version has
   `kitchen_print_confirmed_at` and is not already effective.
8. `Freigabe anfordern` does not replace or bypass print confirmation or
   effective-version selection.
9. A cancelled Order offers no mutating version, print, effective or ready
   action.
10. B7 progression blockers, call-verification labels and READY_TO_SEND
    blockers remain separate vocabularies.

### 4.2 Security and transport

1. Basic Auth, CSRF validation, `Cache-Control: no-store`, frame blocking and
   referrer policy remain unchanged.
2. Every POST form is built with `_csrf_input(context)`.
3. Remote forms retain `_command_fields()` and exact `_expect_*`
   preconditions. Static prototype forms must never be copied over these
   helpers.
4. User and Core text is escaped with `_e()` before insertion into HTML.
5. No secret, token, contact detail or payload is added to logs or URLs.
6. Direct and remote modes render the same presentation. Remote mode alone has
   hidden idempotency and optimistic-concurrency fields.
7. The UI does not reproduce Core business rules on the Proxmox side. It
   consumes existing derived state and named commands.

## 5. Current presentation boundaries

| Current boundary | Responsibility after migration |
|---|---|
| `office_panel_views.py::_STYLE` | repo-owned v2 tokens and compatibility styles, inline |
| `office_panel_views.py::_page()` | common semantic shell, active navigation, inline sprite |
| `OfficePageContext` | request-local CSRF and optional shell display facts only |
| `OfficePanel.render_queue()` / `_render_remote_queue()` | Arbeitszentrale from the existing direct projection / remote QueueView |
| `render_anfragen()` | server-filtered Inquiry cards |
| `render_auftraege()` | truthful Order cards from existing list projection |
| `render_inquiry()` | Inquiry facts, one next step, existing edit form |
| `render_order()` | target-version summary, one Core-derived next action, history |
| `render_rueckruf()` | existing Auerswald facts and degradation behavior |
| `render_print_sheet()` | unchanged utility print page |
| `office_panel_http.py` | unchanged routes, auth, CSRF and error boundary |

Rendering may be split into small pure helpers or immutable view dataclasses,
but those helpers must not persist state or become a second business layer.

## 6. Target presentation architecture

### 6.1 Source ownership

Only these design inputs are adopted:

- CSS tokens and component rules from `assets/office-panel-v2.css`;
- symbol bodies from `assets/icons.svg`;
- semantic structure from `screens/*.html`;
- display mappings and explicit omissions from `integration/DATA_CONTRACT.md`.

Generated demo data, hard-coded IDs, names, dates, counts and buttons are not
copied into production renderers.

Recommended repo structure:

```text
src/catering_system/ui/
├── office_panel.py                 # orchestration + existing commands
├── office_panel_http.py            # transport/security, unchanged routes
├── office_panel_views.py           # shell, CSS, labels, shared helpers
└── office_panel_components.py      # optional pure card/detail renderers
```

Do not add a template engine for this migration. The project currently has a
small stdlib-only server, and a new runtime dependency would increase rollout
risk without changing the data contract.

### 6.2 Shell contract

`_page()` should accept an explicit active section rather than infer it from a
translated title:

```python
OfficeSection = Literal[
    "home", "inquiries", "orders", "week", "callbacks", "proposal"
]

def _page(
    title: str,
    body: str,
    *,
    active_section: OfficeSection,
    context: OfficePageContext = _EMPTY_PAGE_CONTEXT,
) -> str: ...
```

Shell counts are presentation facts only. A badge is shown only when its value
is already available for the request or can be obtained through one existing
bounded projection. Missing Auerswald data stays unknown/hidden, never `0`.

The shell must not cause per-Order or per-Inquiry remote reads. If a global
badge would require N+1 hydration, omit it until a separately approved bounded
projection exists.

### 6.3 Assets and CSP

Initial implementation is no-JS:

- v2 CSS remains inline in `_page()`;
- the SVG symbol sprite is inlined once near the start of `<body>`;
- icons use local `<use href="#i-...">` references;
- system fonts replace Google Fonts;
- no static asset route is added;
- no `script-src` is added;
- `fonts.googleapis.com` and `fonts.gstatic.com` are removed from CSP only in
  the same slice that removes the CSS `@import`;
- the corrected horizontal mobile navigation remains usable without JS.

The v2 JavaScript file is deferred to an optional, separately reviewed slice.
No required action, search, navigation or Storno safeguard may depend on it.

### 6.4 View models

Presentation-only immutable projections are allowed when they reduce repeated
branching. Examples:

- `InquiryCardView`: source label, title fallback, summary fallback, event
  facts, derived status label, link;
- `OrderCardView`: order/source IDs, cancellation, readiness label and existing
  blocker label;
- `OrderTargetView`: target version, print link, one next command and stepper;
- `ShellView`: active section and already-known optional badge/week values.

They must be derived per request and never stored in SQLite.

## 7. Screen contracts

### 7.1 Arbeitszentrale (`GET /`)

- Uses the existing direct queue derivation or remote `QueueView`.
- Keeps `neue_anfragen` / `neue_anfragen_top` transport keys unchanged.
- Presents one combined visual work list from already-loaded top rows; it does
  not introduce a scheduler, priority or deadline fact.
- Current-week entries remain only effective versions.
- Auerswald unavailable remains distinguishable from an empty callback list.
- No new `/woche` route is added.

### 7.2 Anfragen (`GET /anfragen?q=`)

- Search remains server-side and preserves/escapes the current `q` value.
- Cards use existing Inquiry fields and display dictionaries.
- Open/closed wording is derived, not persisted.
- No structured contact is inferred from intake text.
- `intake_subject` and `intake_summary` have honest location/date fallbacks.

### 7.3 Anfrage-Detail (`GET /inquiry/{id}`)

- Displays the actual CRM stage and verification status.
- Shows exactly the action from `InquiryOfficeState`, if any.
- An active Order replaces CRM select with fixed `Bestätigt / Auftrag` plus
  the existing hidden input.
- Existing linked Order and cancelled-history links remain visible.
- Existing truncation warning remains visible in remote mode.
- The edit form stays functional even if it retains compatibility styling in
  the first detail slice.

### 7.4 Aufträge (`GET /auftraege?q=`)

- Initial migration uses fields already supplied by the existing list
  projection: Order ID, source Inquiry ID, cancelled state, readiness, blocker
  and effective-version presence.
- It does not hydrate every row with separate Inquiry and version detail calls.
- Therefore demo titles and event facts are omitted when not present in the
  bounded projection. A truthful `Auftrag {id[:8]}` is preferred over invented
  or N+1-loaded detail.
- Rich event cards require a separate reviewed API projection slice and are not
  silently folded into this presentation migration.

### 7.5 Auftrag-Detail (`GET /order/{id}`)

- Uses one target version: valid candidate, otherwise highest version number.
- Keeps every historical version accessible under `<details>`.
- Shows the print sheet link and exactly one primary command:
  `print-confirm`, then `effective`, then none.
- For an unconfirmed version, `Druck bestätigen` is present and `Wirksam
  machen` is absent.
- `Freigabe anfordern` remains a separate existing command and its actual
  READY_TO_SEND result remains visible.
- Remote truncation metadata and optimistic preconditions remain intact.
- Storno is placed in a danger zone. Without JS, use a deliberate `<details>`
  disclosure containing consequence text and the existing POST form.

### 7.6 Rückrufe (`GET /rueckruf`)

- Keeps Auerswald and Core facts separate.
- `Erledigt` still writes only to auerswald-sync.
- `Anfrage erfassen` remains a prefilled GET navigation, not automatic intake.
- Remote mode without configured local Auerswald continues to say
  `Rückruf-Liste: nur vor Ort verfügbar`.
- Merging verify-Inquiries into this screen is deferred unless it can be built
  from an already-loaded bounded projection without changing semantics.

### 7.7 Existing forms and utility pages

Neue Anfrage, edit forms, Neue Version, proposal preview/import and the print
sheet remain operational throughout migration. They receive the shared shell
and compatibility styles but are not structurally redesigned in early slices.

## 8. Direct/remote parity

The current equality rule remains:

```text
direct HTML == remote HTML after stripping remote-only
_command_id and _expect_* hidden fields
```

Every migrated screen must extend the existing parity suite. Do not normalize
away visible differences, ordering differences, missing warnings or different
actions.

Remote-specific metadata must survive the redesign:

- list/detail truncation warnings;
- true latest version count for optimistic version creation;
- current effective version precondition;
- current entity `updated_at` precondition;
- idempotent command ID per rendered mutating form;
- fixed unavailable-Core degradation page.

## 9. Performance rules

1. No presentation helper performs repository or HTTP reads.
2. Render orchestration loads each bounded collection once per request and
   passes data down.
3. No N+1 remote hydration for list titles, event facts, shell badges or
   status chips.
4. Existing API page limits and truncation warnings remain honest.
5. The dashboard reuses its already-loaded queue/week projection.
6. Any richer list projection is a separate API contract change with its own
   tests and review, not an incidental UI edit.

## 10. Accessibility and responsive requirements

- semantic landmarks: `<nav>`, `<main>`, headings in order;
- one visible `<h1>` per page;
- current navigation uses `aria-current="page"`;
- icon-only controls have accessible names;
- all decorative SVG uses `aria-hidden="true"`;
- visible keyboard focus remains on links, buttons, inputs and summaries;
- forms retain labels and errors remain readable without color alone;
- mobile navigation is usable with JavaScript blocked;
- content remains usable at 320 px width and 200% zoom;
- reduced motion is respected if a later JS/drawer slice is approved;
- danger actions require a deliberate disclosure/confirmation step.

## 11. Test matrix

### 11.1 Static/presentation

- no external font or CDN URL in generated Office Panel HTML/CSS;
- inline sprite contains every referenced symbol exactly once;
- no required script tag or inline script;
- CSP has no stale Google font origins after font removal;
- active navigation and page title are correct for every route;
- server-side Anfragen search has `method="get"`, `action="/anfragen"`,
  `name="q"` and escaped current value;
- no demo company, contact, date, count or ID leaks into renderers.

### 11.2 Security/forms

- every POST form carries CSRF;
- every remote POST form carries a command ID;
- update/effective/version/cancel forms preserve exact precondition fields;
- hostile intake/location/query strings are escaped;
- Basic Auth and all security headers remain unchanged except deliberate
  removal of external font origins;
- no GET action performs a write.

### 11.3 Inquiry states

- open + no verification required: convert only;
- verification pending: verify only;
- rejected: no verify/convert and absent from open queue;
- active Order: fixed `Bestätigt / Auftrag`, no CRM select, no convert;
- crafted incompatible update rejected direct and remote;
- cancelled-only history: explicit reconversion remains available;
- remote truncated linked-Order history keeps its warning.

### 11.4 Order states

- no versions: no invented next action;
- unconfirmed target: print link + print-confirm, no effective;
- confirmed non-effective target: effective, no print-confirm;
- effective target: neither print-confirm nor effective;
- candidate target wins only when it resolves to the Order;
- invalid candidate falls back to highest version;
- multiple versions render correct history and exact per-version facts;
- cancelled Order: no mutating operational action;
- READY_TO_SEND reasons retain their own labels;
- remote 200-version truncation warning and true count remain visible.

### 11.5 Direct/remote and browser regression

- direct/remote parity for dashboard, lists and both details;
- full remote write flow remains create → update → convert → print-confirm
  → effective → ready → cancel;
- viewport checks at 1280, 820, 620 and 320 px;
- no-JS manual pass for navigation, search, forms and Storno disclosure;
- keyboard-only pass for navigation, primary action and details disclosure;
- printable Küchenzettel remains unchanged.

### 11.6 Full project gate

- relevant Office Panel, API and remote tests;
- full `pytest`;
- full coverage with the project 90% minimum;
- `ruff check`;
- `ruff format --check`;
- full mypy;
- documentation tests;
- `git diff --check`.

## 12. Implementation slices

### UI2A — Foundation and shell

- import reviewed v2 tokens and icon symbols into repo-owned Python constants;
- remove Google font import and matching CSP origins atomically;
- add explicit active section to `_page()`;
- implement desktop shell and no-JS mobile navigation;
- keep every existing body renderer and command form semantically unchanged;
- add compatibility CSS for current tables/forms during gradual migration;
- add shell/security/direct-remote regression tests.

This is the recommended first implementation slice.

### UI2B — Anfragen list

- replace the table with truthful Inquiry cards;
- retain `GET /anfragen?q=` and exact server filtering;
- retain links, source labels, CRM stage and verification facts;
- add empty/search/XSS/direct-remote tests.

### UI2C — Auftrag-Detail

- introduce target-version view projection and v2 detail layout;
- render print link plus exactly one primary Core command;
- retain version history, truncation warning, ready result and forms;
- introduce no-JS Storno danger disclosure;
- add the full order-state matrix in both modes.

### UI2D — Anfrage-Detail

- introduce v2 facts/message/next-step layout;
- retain exact `InquiryOfficeState` action derivation;
- retain active-Order CRM lock, linked Orders, warnings and edit form;
- add state and crafted-form regressions in both modes.

### UI2E — Arbeitszentrale

- replace dashboard composition with v2 attention/work/week layout;
- reuse current direct derivation and remote QueueView;
- do not add priority/deadline facts;
- keep Auerswald unknown distinct from zero;
- add direct/remote projection and empty-state tests.

### UI2F — Aufträge list and Rückrufe

- replace tables/lists with truthful bounded cards;
- do not N+1-hydrate Order event details;
- preserve current search scope and remote Auerswald degradation;
- add list, cancellation, callback and parity tests.

### UI2G — Forms polish and optional progressive enhancement

- separately review styling of Neue Anfrage, edit and Neue Version forms;
- translate existing select display labels without changing submitted values;
- only then consider a local JS route/CSP change for drawer, live filtering or
  confirm enhancement;
- all behavior must remain available without JS.

## 13. Migration and rollout

No database migration is required. No stored value changes.

For every slice:

1. implement against an isolated temporary SQLite database;
2. run relevant direct and remote tests;
3. run a no-JS manual pass;
4. run the full quality gate;
5. commit the slice separately;
6. do not combine implementation with deploy;
7. update `CHANGELOG.md`, `WORKLOG.md`, `docs/current-status.md` and the user
   guide only with facts completed by that slice.

Deployment, when separately authorized, remains the existing controlled Office
Panel rollout. The Core Office API/Proxmox cutover status must remain truthful;
new visuals do not imply remote mode is deployed.

Rollback is code-only: restore the previous Office Panel commit and restart the
panel. Since there is no schema or data migration, no database rollback is
needed. Before deploy, retain screenshots or HTML fixtures for the prior shell
and every migrated route.

## 14. Risks and controls

| Risk | Control |
|---|---|
| Static demo actions replace real command forms | Hand-adapt structure; require CSRF/command/precondition tests |
| Direct and remote pages diverge | Existing stripped-hidden-field parity remains a hard gate |
| Rich Order cards cause N+1 API traffic | Use bounded existing list projection; defer richer API shape |
| New shell adds hidden reads/failure modes | Shell helpers are pure; optional badges use already-loaded bounded data |
| JS becomes required under strict CSP | Initial migration is no-JS; corrected fallback is mandatory |
| Premature `Wirksam machen` returns | Order-state matrix asserts absence before exact version confirmation |
| Active Order gets contradictory CRM stage | Fixed stage UI plus unchanged direct/API Core gates |
| Technical demo text becomes false business data | No hard-coded prototype facts; explicit truthful fallbacks |
| Storno becomes easier to trigger accidentally | Danger zone plus no-JS deliberate disclosure |
| Week screen invents a route | Keep existing `/` section and `kiosk_url`; no `/woche` in this pack |
| Visual migration obscures operational warnings | Truncation, unavailable-Core and blocker messages are acceptance criteria |

## 15. Acceptance criteria

The migration is complete only when:

- every in-scope route uses the repo-owned v2 shell and components;
- no runtime dependency on the external UI folder exists;
- direct and remote parity is green for every migrated route;
- all Core-derived action and CRM invariants remain green;
- all POST forms retain CSRF, command IDs and preconditions;
- no required workflow depends on JavaScript;
- no N+1 remote list hydration was introduced;
- current-week, Auerswald and truncation behavior remains truthful;
- the full project gate passes;
- manual desktop/mobile/no-JS flows pass on an isolated database;
- documentation distinguishes local implementation from deployed state;
- push and deploy occur only under separate explicit authorization.

## 16. Recommended first slice

Implement **UI2A — Foundation and shell** only.

It delivers the v2 identity across the existing panel while leaving every
current renderer, route and Core action intact. Its acceptance proof is narrow
and strong: no external fonts, corrected CSP, inline icons, usable no-JS mobile
navigation, byte-equivalent direct/remote presentation modulo remote hidden
fields, and zero changes to production data or domain behavior.

Do not start list/detail restructuring in the same commit. A clean UI2A gate
creates a stable presentation foundation for the later screen-by-screen slices.
