# STRATO AI telephone intake API

Purpose: create one Core Inquiry from a STRATO Smart-Telefonassistent API tool.

## Core receiver

Local receiver:

```text
POST http://127.0.0.1:8085/intake/ai-telefonist
```

Authentication:

```http
Authorization: Bearer <AI_TELEFONIST_INTAKE_TOKEN>
Content-Type: application/json
```

The service is intentionally loopback-only. STRATO requires a publicly reachable
HTTPS endpoint, so a narrow TLS reverse proxy/tunnel must forward only this
receiver. Do not expose the Office Panel, Office API, Kitchen API, or SQLite.

Success:

```json
{"accepted": true, "inquiry_id": "<uuid>"}
```

The receiver creates Inquiry only. It does not create an Offer, Order,
OrderVersion, print job, customer document, or payment state.

## STRATO tool definition

Name:

```text
create_catering_inquiry
```

Description:

```text
Erstellt eine Catering-Anfrage im internen System. Nutze dieses Tool, wenn ein
Anrufer konkret Catering anfragt oder ein Angebot erhalten möchte. Erfasse
mindestens Name, Telefonnummer, Veranstaltungsdatum und Gästezahl. Frage, soweit
bekannt, zusätzlich nach Firma, E-Mail-Adresse, Beginn, Veranstaltungsort,
Veranstaltungsart, Lieferung oder Abholung sowie besonderen Wünschen.
```

Parameters:

```json
{
  "type": "object",
  "properties": {
    "contact_name": {
      "type": "string",
      "description": "Vor- und Nachname der Kontaktperson"
    },
    "company_name": {
      "type": "string",
      "description": "Firmenname, falls vorhanden"
    },
    "phone": {
      "type": "string",
      "description": "Telefonnummer für Rückfragen"
    },
    "email": {
      "type": "string",
      "description": "E-Mail-Adresse, falls vorhanden"
    },
    "event_date": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
      "description": "Datum der Veranstaltung im Format YYYY-MM-DD"
    },
    "event_start": {
      "type": "string",
      "description": "Beginn der Veranstaltung im Format HH:MM, falls bekannt"
    },
    "guest_count": {
      "type": "integer",
      "minimum": 1,
      "maximum": 2000,
      "description": "Voraussichtliche Anzahl der Gäste"
    },
    "location": {
      "type": "string",
      "description": "Veranstaltungsort oder Veranstaltungsadresse, falls bekannt"
    },
    "event_type": {
      "type": "string",
      "description": "Art der Veranstaltung, zum Beispiel Firmenfeier, Hochzeit oder Geburtstag"
    },
    "fulfillment_mode": {
      "type": "string",
      "enum": ["DELIVERY", "PICKUP", "UNKNOWN"],
      "description": "DELIVERY bei Lieferung, PICKUP bei Abholung, UNKNOWN wenn noch offen"
    },
    "customer_request": {
      "type": "string",
      "description": "Speisenwünsche, Ernährungswünsche, Allergien oder sonstige Hinweise"
    }
  },
  "required": [
    "contact_name",
    "phone",
    "event_date",
    "guest_count"
  ]
}
```

The technical `submission_id` is not a customer-facing parameter. The current
STRATO HAR builds it from already collected values so the assistant never asks
the caller for an internal identifier.

## HAR request template

Replace only the public HTTPS URL and bearer token with the live values in
STRATO. Parameter values use STRATO's `{{ variableName }}` placeholders.

```json
{
  "method": "POST",
  "url": "https://YOUR_PUBLIC_HTTPS_HOST/intake/ai-telefonist",
  "headers": [
    {
      "name": "Authorization",
      "value": "Bearer YOUR_AI_TELEFONIST_INTAKE_TOKEN"
    },
    {
      "name": "Content-Type",
      "value": "application/json"
    }
  ],
  "postData": {
    "mimeType": "application/json",
    "text": "{\"submission_id\":\"strato-{{ phone }}-{{ event_date }}-{{ guest_count }}-{{ contact_name }}\",\"contact_name\":\"{{ contact_name }}\",\"company_name\":\"{{ company_name }}\",\"phone\":\"{{ phone }}\",\"email\":\"{{ email }}\",\"event_date\":\"{{ event_date }}\",\"event_start\":\"{{ event_start }}\",\"guest_count\":{{ guest_count }},\"location\":\"{{ location }}\",\"event_type\":\"{{ event_type }}\",\"fulfillment_mode\":\"{{ fulfillment_mode }}\",\"customer_request\":\"{{ customer_request }}\"}"
  }
}
```

STRATO may render absent optional string placeholders as empty strings. The
receiver therefore treats blank `event_start` as absent and blank
`fulfillment_mode` as `UNKNOWN`.

STRATO may also transcribe a spoken phone number as comma-separated digits such
as `0,1,7,6,...`. The receiver compacts common separators before storing the
phone number and compacts comma-separated digits in the technical submission
reference.

## Stored Core facts

- `inquiry_source = ai_telefonist`
- `crm_stage = Neue Anfrage`
- call verification required, status `pending`
- event date and exact event start are stored separately
- guest count and event location are stored on Inquiry
- contact name/company/phone/email are stored in the Inquiry customer snapshot
- event type and customer wishes are stored in the intake message
- fulfillment mode is stored as `DELIVERY`, `PICKUP`, or `UNKNOWN`
- `submission_id` is source-scoped and unique for retry protection

## Public HTTPS note

A `trycloudflare.com` quick tunnel is suitable only for an integration test.
Its URL exists only while that foreground `cloudflared tunnel --url ...`
process is running. Production needs a persistent public HTTPS endpoint.
