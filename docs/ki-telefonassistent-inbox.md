# KI Telefonassistent Inbox

## Ziel

STRATO-Gespräche werden zunächst als eigener Office-Inbox-Eintrag gespeichert. Ein Telefonat ist noch keine Anfrage. Erst ein Mitarbeiter entscheidet, ob daraus eine Anfrage, eine Aufgabe, eine Verknüpfung mit einem bestehenden Vorgang oder nur ein erledigter Gesprächseintrag wird.

## Ziel-Flow

```text
STRATO Smart-Telefonassistent
  -> E-Mail-Zusammenfassung in Gmail
  -> Gmail Worker
  -> deterministisches Parsen der STRATO-Hülle
  -> LLM strukturiert nur die freie Zusammenfassung
  -> AiTelefonCall
  -> Office: KI Telefonassistent
  -> Als Anfrage übernehmen / Als Aufgabe übernehmen / Verknüpfen / Erledigt
```

## Sicherheits- und Datenregeln

- `strato_id` und `gmail_message_id` sind eindeutig und verhindern Doppelimporte.
- Das Original der STRATO-Zusammenfassung bleibt erhalten.
- Fehlende Angaben bleiben `null`/leer. Die LLM darf keine Daten ergänzen, die nicht im Gespräch enthalten sind.
- Keine automatische Empfehlung, welcher Geschäftsvorgang erstellt werden soll.
- Keine automatische Änderung eines bestehenden Angebots oder Auftrags.
- Der bestehende direkte Endpoint `/intake/ai-telefonist` bleibt unverändert.
- Eine direkte Übernahme als Inquiry ist nur möglich, wenn mindestens Datum, Name und Telefonnummer vorhanden sind. Das entspricht der aktuellen Inquiry-Domäne, die ein Veranstaltungsdatum benötigt.

## MVP für Demo

1. STRATO-Mail importieren und deduplizieren.
2. Strukturierte Fakten im `AiTelefonCall` speichern.
3. Liste und Detailansicht `KI Telefonassistent` anzeigen.
4. `Als Anfrage übernehmen` über den bestehenden `InquiryService`.
5. `Erledigt`.
6. `Als Aufgabe übernehmen`, wenn Mitarbeiter-Authentifizierung/ManualTaskService verfügbar ist.

`Mit bestehendem Vorgang verknüpfen` ist im Domänenmodell vorgesehen, die Such-/Auswahl-UX kann nach der Demo ergänzt werden.
