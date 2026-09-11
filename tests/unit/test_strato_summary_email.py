from __future__ import annotations

from catering_system.intake.strato_summary_email import (
    llm_extraction_json_schema,
    parse_strato_summary_mail,
    structured_call_facts_from_mapping,
)


def test_parse_realistic_strato_summary_mail() -> None:
    raw = """Anrufer: +4917642795029
Name: Viktor Merkel
Telefonnummer: +49 176 42795029
Betreff: Catering-Anfrage für Geburtstagsfeier am 12.01.2027
Zusammenfassung: Herr Viktor Merkel rief an, um ein Catering für seine Geburtstagsfeier
am 12.01.2027 um 16:45 Uhr in Hamburg zu organisieren.
ID: 07a45b4c-68e4-424e-a670-372c3d50df92
"""

    parsed = parse_strato_summary_mail(raw)

    assert parsed.name == "Viktor Merkel"
    assert parsed.phone == "+4917642795029"
    assert parsed.subject.startswith("Catering-Anfrage")
    assert "16:45" in parsed.summary
    assert parsed.strato_id == "07a45b4c-68e4-424e-a670-372c3d50df92"


def test_parse_real_strato_plain_text_with_standalone_labels() -> None:
    raw = """STRATO Smart-Telefonassistent
Neuer Anruf

Anrufer: +4917642795029

Name
Viktor Merkel

Telefonnummer
+49 176 42795029

Betreff
Catering-Anfrage für Geburtstagsfeier am 12.01.2027

Zusammenfassung
Herr Viktor Merkel rief an, um ein Catering für seine Geburtstagsfeier
am 12.01.2027 um 16:45 Uhr in Hamburg zu organisieren.

ID: 07a45b4c-68e4-424e-a670-372c3d50df92
"""

    parsed = parse_strato_summary_mail(raw)

    assert parsed.name == "Viktor Merkel"
    assert parsed.phone == "+4917642795029"
    assert parsed.subject.startswith("Catering-Anfrage")
    assert "16:45" in parsed.summary
    assert parsed.strato_id == "07a45b4c-68e4-424e-a670-372c3d50df92"


def test_structured_facts_keep_missing_values_missing() -> None:
    facts = structured_call_facts_from_mapping(
        {
            "event_type": "Private Veranstaltung",
            "event_date": None,
            "event_period": "Januar 2027",
            "guest_count": 60,
            "customer_request": "Ohne Schweinefleisch, vegetarische Optionen",
            "callback_requested": True,
        }
    )

    assert facts.event_date is None
    assert facts.event_period == "Januar 2027"
    assert facts.guest_count == 60
    assert facts.callback_requested is True
    assert facts.location == ""


def test_structured_facts_normalize_budget_and_time() -> None:
    facts = structured_call_facts_from_mapping(
        {
            "event_date": "2027-01-12",
            "event_start": "16:45",
            "guest_count": 100,
            "budget_per_person": "30,00",
            "fulfillment_mode": "unknown",
            "callback_time": "13:20",
        }
    )

    assert facts.event_date is not None
    assert facts.event_date.isoformat() == "2027-01-12"
    assert facts.event_start is not None
    assert facts.event_start.strftime("%H:%M") == "16:45"
    assert facts.budget_per_person_cents == 3000
    assert facts.fulfillment_mode == "UNKNOWN"


def test_llm_extraction_json_schema_is_strict_and_complete() -> None:
    schema = llm_extraction_json_schema()

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    properties = schema["properties"]
    assert isinstance(properties, dict)
    assert set(schema["required"]) == set(properties)
    assert properties["fulfillment_mode"] == {
        "type": "string",
        "enum": ["UNKNOWN", "DELIVERY", "PICKUP"],
    }
