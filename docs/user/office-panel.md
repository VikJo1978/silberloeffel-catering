# Office panel guide

The office panel is the primary human write surface for inquiries and orders.
It is available only over the private network. Login user: `office`; obtain the
password through the agreed private credential channel.

## Pages

| Page | Purpose |
|---|---|
| Startseite | top action queues and current priorities |
| Rückrufe | missed-call list from the optional Auerswald sync service |
| Anfragen | searchable list of all inquiries |
| Aufträge | searchable list of all orders and next steps |
| Neue Anfrage | manual inquiry entry |
| Proposal preview | review configurator payload before creating an inquiry |

## Daily start

1. Open **Startseite**.
2. Work the three queues in order: callbacks, new inquiries, orders with a next
   step.
3. Open **Diese Woche** or the kitchen link to check near-term events.
4. Investigate any explicit blocker; do not bypass it by editing the database.

## New inquiry

1. Select **Neue Anfrage erfassen**.
2. Enter the event date and available context.
3. Choose the real intake source; do not use a convenient but false source.
4. Save and review the inquiry detail page.
5. For public or indirect channels, complete customer verification before
   conversion when the panel requires it.

Website contact information appears as labelled intake context. It is not yet a
verified structured customer record.

The staging website writes these records into the same Core Inquiry queue used
by the office panel. Until the staging URL has HTTPS, treat every such record as
test data. A website Inquiry remains blocked from conversion until the office
has completed the displayed telephone-verification step.

## Prepare an offer from an inquiry

When the separate configurator is deployed and linked, the Inquiry detail page
shows **Angebot mit Anfragedaten vorbereiten**. It opens an editable offer draft
with the known company/contact/event values already filled in.

Review every imported value. This action creates no Order, does not satisfy
verification, does not send anything to the customer, and does not make the
offer operational truth. If the guest count was unknown, the configurator keeps
its editable default instead of inventing a Core fact.

## Convert an inquiry to an order

Conversion is available only when the inquiry's verification gate is satisfied.
Conversion creates:

- one Order linked to the source Inquiry;
- immutable OrderVersion 1 containing the operational event snapshot.

If conversion is blocked, correct or verify the Inquiry. Do not create a second
manual inquiry to work around the gate.

## Version and kitchen workflow

For every operational version:

1. review date, time, location, guest count, and planning mode;
2. create a new version when facts change — do not overwrite history;
3. open **Küchenzettel** for the intended version;
4. print it and confirm **Druck bestätigt** only after the print step;
5. make that confirmed version effective;
6. request/check `READY_TO_SEND`.

The order cannot become ready when the effective version is missing or its
kitchen print is unconfirmed.

## Cancellation

`Storno` is explicit and irreversible through the application. It preserves
history but blocks operational commands and readiness. Confirm the correct order
before cancelling.

## Search and IDs

Lists prioritize operational information. Short IDs are links for technical
identification, not customer-facing order numbers. Search from the full
**Anfragen** or **Aufträge** pages, not the top-five dashboard queues.

## What not to do

- Do not expose or bookmark the office panel through a public URL.
- Do not share the office password.
- Do not edit `core.db` manually.
- Do not mark print confirmation before the actual kitchen print is handled.
- Do not use staging for real customer data.
- Do not treat CRM as the operational order truth.

## When something looks wrong

Record:

- page and action;
- approximate time;
- short Inquiry/Order ID;
- exact visible error text;
- whether retrying once changed the result.

Do not include customer contact details or passwords in screenshots. The
operator can then inspect the relevant systemd journal using the
[production runbook](../runbooks/lenovo-production.md).
