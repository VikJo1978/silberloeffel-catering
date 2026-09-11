"""Long-running Gmail -> KI Telefonassistent importer for the Lenovo demo.

The worker reads only STRATO Smart-Telefonassistent summaries, parses the
stable outer mail format deterministically, asks an LLM only for semantic facts
from the free-text summary, validates those facts through the Core parser, and
then inserts one deduplicated AiTelefonCall row into core.db.

Google and OpenAI SDKs intentionally live in the worker venv rather than the
Core runtime dependency set.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from catering_system.intake.strato_summary_email import (
    llm_extraction_contract,
    llm_extraction_json_schema,
    parse_strato_summary_mail,
    structured_call_facts_from_mapping,
)
from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)
from catering_system.services.ai_telefon_call_service import AiTelefonCallService

STRATO_SENDER = "noreply@ai-voicereceptionist.com"
STRATO_SUBJECT = "Neuer Anruf"
GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
BERLIN = ZoneInfo("Europe/Berlin")


def _plain_text(payload: dict[str, Any]) -> str:
    body = payload.get("body", {})
    data = body.get("data")
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain" and data:
        return base64.urlsafe_b64decode(str(data) + "===").decode(
            "utf-8", errors="replace"
        )
    for part in payload.get("parts", []) or []:
        text = _plain_text(part)
        if text:
            return text
    return ""


def _header(payload: dict[str, Any], name: str) -> str:
    for header in payload.get("headers", []) or []:
        if str(header.get("name", "")).lower() == name.lower():
            return str(header.get("value", ""))
    return ""


def _received_at(message: dict[str, Any]) -> datetime:
    raw = message.get("internalDate")
    try:
        milliseconds = int(str(raw))
    except (TypeError, ValueError):
        return datetime.now(UTC)
    return datetime.fromtimestamp(milliseconds / 1000, tz=UTC)


def _prompt(summary: str, reference_time: datetime) -> str:
    reference_local = reference_time.astimezone(BERLIN)
    contract = json.dumps(llm_extraction_contract(), ensure_ascii=False, indent=2)
    return f"""Du extrahierst ausschließlich Fakten aus einer deutschen Zusammenfassung eines Catering-Telefonats.

Referenzzeit des eingegangenen Anrufs in Europe/Berlin: {reference_local.isoformat(timespec='minutes')}

Regeln:
- Erfinde nichts. Nicht genannte Werte sind null.
- Verwende exakt die vorgegebenen Felder.
- event_date und callback_date: YYYY-MM-DD oder null.
- event_start und callback_time: HH:MM oder null.
- Wenn nur ein Zeitraum wie "im Januar" bekannt ist, bleibt event_date null und event_period enthält den genannten Zeitraum.
- Relative Angaben wie "morgen" dürfen nur relativ zur Referenzzeit aufgelöst werden.
- guest_count ist eine ganze Zahl oder null.
- budget_per_person ist der Euro-Betrag pro Person als Zahl oder null.
- fulfillment_mode ist ausschließlich UNKNOWN, DELIVERY oder PICKUP.
- customer_request enthält nur geäußerte Wünsche/Besonderheiten, keine Empfehlung.
- callback_requested ist true, false oder null.

Erwartete Felder:
{contract}

STRATO-Zusammenfassung:
{summary}
"""


def _json_mapping(text: str) -> dict[str, Any]:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()
    parsed = json.loads(candidate)
    if not isinstance(parsed, dict):
        raise ValueError("LLM response is not a JSON object")
    return parsed


def _openai_structured_facts(
    summary: str, *, reference_time: datetime, model: str
) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError(
            "OpenAI SDK fehlt im Worker-vEnv. Installieren: pip install openai"
        ) from exc

    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY ist nicht gesetzt")

    client = OpenAI()
    response = client.responses.create(
        model=model,
        input=_prompt(summary, reference_time),
        text={
            "format": {
                "type": "json_schema",
                "name": "strato_call_facts",
                "strict": True,
                "schema": llm_extraction_json_schema(),
            }
        },
    )
    output_text = getattr(response, "output_text", "")
    if not isinstance(output_text, str) or not output_text.strip():
        raise ValueError("OpenAI response contains no output_text")
    return _json_mapping(output_text)


def import_once(
    *,
    db_path: Path,
    token_path: Path,
    model: str,
    max_results: int = 50,
) -> int:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError(
            "Google SDK fehlt im Worker-vEnv. Installieren: "
            "pip install google-api-python-client google-auth-httplib2 "
            "google-auth-oauthlib"
        ) from exc

    credentials = Credentials.from_authorized_user_file(str(token_path), [GMAIL_SCOPE])
    gmail = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    result = (
        gmail.users()
        .messages()
        .list(
            userId="me",
            q=f'from:{STRATO_SENDER} subject:"{STRATO_SUBJECT}"',
            maxResults=max_results,
        )
        .execute()
    )

    repository = SQLiteAiTelefonCallRepository(db_path)
    service = AiTelefonCallService(repository)
    imported = 0
    try:
        # Gmail returns newest first. Reverse so a batch is inserted in call order.
        for item in reversed(result.get("messages", [])):
            message_id = str(item["id"])
            if repository.find_by_gmail_message_id(message_id) is not None:
                continue

            message = (
                gmail.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            payload = message.get("payload", {})
            sender = _header(payload, "From")
            subject = _header(payload, "Subject")
            if STRATO_SENDER not in sender.lower() or subject.strip() != STRATO_SUBJECT:
                continue

            raw_text = _plain_text(payload)
            parsed = parse_strato_summary_mail(raw_text)
            if repository.find_by_strato_id(parsed.strato_id) is not None:
                continue

            received_at = _received_at(message)
            structured = _openai_structured_facts(
                parsed.summary,
                reference_time=received_at,
                model=model,
            )
            # This validator is the trust boundary. Even if the model returns a
            # plausible-looking but malformed value, it never reaches core.db.
            facts = structured_call_facts_from_mapping(structured)
            service.ingest(
                strato_id=parsed.strato_id,
                gmail_message_id=message_id,
                caller_phone=parsed.phone,
                contact_name=parsed.name,
                email=facts.email,
                subject=parsed.subject,
                summary=parsed.summary,
                raw_message=parsed.raw_text,
                event_type=facts.event_type,
                event_date=facts.event_date,
                event_period=facts.event_period,
                event_start=facts.event_start,
                guest_count=facts.guest_count,
                location=facts.location,
                budget_per_person_cents=facts.budget_per_person_cents,
                fulfillment_mode=facts.fulfillment_mode,
                customer_request=facts.customer_request,
                callback_requested=facts.callback_requested,
                callback_date=facts.callback_date,
                callback_time=facts.callback_time,
                received_at=received_at,
            )
            imported += 1
            print(
                f"STRATO {parsed.strato_id}: importiert als {parsed.name or parsed.phone}",
                flush=True,
            )
    finally:
        repository.close()
    return imported


def run_forever(
    *,
    db_path: Path,
    token_path: Path,
    model: str,
    poll_seconds: int,
) -> None:
    while True:
        try:
            count = import_once(db_path=db_path, token_path=token_path, model=model)
            if count:
                print(f"{count} neue STRATO-Gespräche importiert", flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            # Do not mark the Gmail message as consumed. A failed LLM/API/database
            # step is retried on the next poll and therefore cannot silently lose
            # a customer call.
            print(f"STRATO Gmail Worker: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuously import STRATO Smart-Telefonassistent summaries from Gmail"
    )
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--token", required=True, type=Path)
    parser.add_argument(
        "--model",
        default=os.environ.get("STRATO_LLM_MODEL", "gpt-5.6-luna"),
    )
    parser.add_argument("--poll-seconds", type=int, default=30)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    if args.poll_seconds < 10:
        raise SystemExit("--poll-seconds muss mindestens 10 sein")
    if not args.token.exists():
        raise SystemExit(f"Gmail token.json nicht gefunden: {args.token}")

    if args.once:
        count = import_once(db_path=args.db, token_path=args.token, model=args.model)
        print(f"{count} neue STRATO-Gespräche importiert")
        return
    run_forever(
        db_path=args.db,
        token_path=args.token,
        model=args.model,
        poll_seconds=args.poll_seconds,
    )


if __name__ == "__main__":
    main()
