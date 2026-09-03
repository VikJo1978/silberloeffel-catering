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
HTTPS endpoint, so a narrow TLS reverse proxy/tunnel must forward exactly this
route to the local receiver. Do not expose the Office Panel, Office API, Kitchen
API, or the SQLite database.

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
Erstellt eine neue Catering-Anfrage im internen System. Nutze dieses Tool,
wenn ein Anrufer eine konkrete Catering-Anfrage stellt oder ein Angebot
erhalten möchte. Frage die Pflichtangaben ab und fasse freie Wünsche knapp
zusammen. submission_id ist eine technische UUID: nicht vom Anrufer erfragen,
sondern pro Tool-Aufruf selbst erzeugen.
```

Parameters:

```json
{
  "type": "object",
  "properties": {
    "submission_id": {
      "type": "string",
      "description": "Technische eindeutige UUID. Nicht vom Anrufer erfragen; pro Tool-Aufruf selbst erzeugen."
    },
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
      "description": "E-Mail-Adresse, falls der Anrufer eine angibt"
    },
    "event_date": {
      "type": "string",
      "pattern": "^\\d{4}-\\d{2}-\\d{2}$",
      "description": "Datum der Veranstaltung im Format YYYY-MM-DD"
    },
    "event_start": {
      "type": "string",
      "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$",
      "description": "Startzeit im Format HH:MM, falls bekannt"
    },
    "guest_count": {
      "type": "integer",
      "minimum": 1,
      "maximum": 2000,
      "description": "Voraussichtliche Anzahl der Gäste"
    },
    "location": {
      "type": "string",
      "description": "Ort oder Adresse der Veranstaltung"
    },
    "event_type": {
      "type": "string",
      "description": "Art der Veranstaltung"
    },
    "fulfillment_mode": {
      "type": "string",
      "enum": ["DELIVERY", "PICKUP", "UNKNOWN"],
      "description": "DELIVERY bei Lieferung, PICKUP bei Abholung, UNKNOWN wenn noch offen"
    },
    "customer_request": {
      "type": "string",
      "description": "Speisenwünsche, Besonderheiten, Allergien oder sonstige Hinweise"
    }
  },
  "required": [
    "submission_id",
    "contact_name",
    "phone",
    "event_date",
    "guest_count"
  ]
}
```

## HAR request template

Replace only the public HTTPS URL and bearer token with the real values inside
STRATO. Conversation values use STRATO's documented `{{ variableName }}`
placeholder syntax.

```json
{
  "log": {
    "version": "1.2",
    "creator": {
      "name": "STRATO Smart-Telefonassistent",
      "version": "1.0"
    },
    "entries": [
      {
        "request": {
          "method": "POST",
          "url": "https://YOUR_PUBLIC_HTTPS_HOST/intake/ai-telefonist",
          "httpVersion": "HTTP/1.1",
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
          "queryString": [],
          "cookies": [],
          "headersSize": -1,
          "bodySize": -1,
          "postData": {
            "mimeType": "application/json",
            "text": "{\"submission_id\":\"{{ submission_id }}\",\"contact_name\":\"{{ contact_name }}\",\"company_name\":\"{{ company_name }}\",\"phone\":\"{{ phone }}\",\"email\":\"{{ email }}\",\"event_date\":\"{{ event_date }}\",\"event_start\":\"{{ event_start }}\",\"guest_count\":{{ guest_count }},\"location\":\"{{ location }}\",\"event_type\":\"{{ event_type }}\",\"fulfillment_mode\":\"{{ fulfillment_mode }}\",\"customer_request\":\"{{ customer_request }}\"}"
          }
        },
        "response": {
          "status": 0,
          "statusText": "",
          "httpVersion": "",
          "headers": [],
          "cookies": [],
          "content": {
            "size": 0,
            "mimeType": "application/json"
          },
          "redirectURL": "",
          "headersSize": -1,
          "bodySize": -1
        },
        "cache": {},
        "timings": {
          "send": 0,
          "wait": 0,
          "receive": 0
        },
        "time": 0,
        "startedDateTime": "2026-09-03T00:00:00.000Z"
      }
    ]
  }
}
```

## Stored Core facts

- `inquiry_source = ai_telefonist`
- `crm_stage = Neue Anfrage`
- call verification required, status `pending`
- event date and exact event start are stored separately
- guest count and location are stored on Inquiry
- contact name/company/phone/email are stored in the Inquiry customer snapshot
- free customer wishes are stored in intake context
- `submission_id` is source-scoped and unique for retry protection
