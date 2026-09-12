"""Minimal STRATO Gmail importer wiring for the demo environment.

This script intentionally keeps Gmail/OAuth and the LLM client outside the
Core package dependency set. Install the Google client packages in the worker
venv, then provide a structurer that returns the documented JSON mapping.
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path
from typing import Any

from catering_system.intake.strato_summary_email import (
    parse_strato_summary_mail,
    structured_call_facts_from_mapping,
)
from catering_system.repositories.sqlite_ai_telefon_call_repository import (
    SQLiteAiTelefonCallRepository,
)
from catering_system.services.ai_telefon_call_service import AiTelefonCallService

STRATO_SENDER = "noreply@ai-voicereceptionist.com"
STRATO_SUBJECT = "Neuer Anruf"


def _plain_text(payload: dict[str, Any]) -> str:
    body = payload.get("body", {})
    data = body.get("data")
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain" and data:
        return base64.urlsafe_b64decode(data + "===").decode("utf-8", errors="replace")
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


def import_once(*, db_path: Path, token_path: Path, structured_json_dir: Path | None) -> int:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise SystemExit(
            "Google client packages fehlen. Im Worker-vEnv installieren: "
            "google-api-python-client google-auth-httplib2 google-auth-oauthlib"
        ) from exc

    credentials = Credentials.from_authorized_user_file(
        str(token_path), ["https://www.googleapis.com/auth/gmail.readonly"]
    )
    gmail = build("gmail", "v1", credentials=credentials)
    result = (
        gmail.users()
        .messages()
        .list(
            userId="me",
            q=f'from:{STRATO_SENDER} subject:"{STRATO_SUBJECT}"',
            maxResults=50,
        )
        .execute()
    )

    repository = SQLiteAiTelefonCallRepository(db_path)
    service = AiTelefonCallService(repository)
    imported = 0
    try:
        for item in result.get("messages", []):
            message_id = item["id"]
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

            # For a live worker, replace this file-based handoff with the chosen
            # LLM client. The JSON shape is validated by structured_call_facts_from_mapping.
            structured: dict[str, Any] = {}
            if structured_json_dir is not None:
                candidate = structured_json_dir / f"{parsed.strato_id}.json"
                if candidate.exists():
                    structured = json.loads(candidate.read_text(encoding="utf-8"))
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
                event_time_text=facts.event_time_text,
                guest_count=facts.guest_count,
                location=facts.location,
                budget_per_person_cents=facts.budget_per_person_cents,
                fulfillment_mode=facts.fulfillment_mode,
                customer_request=facts.customer_request,
                callback_requested=facts.callback_requested,
                callback_date=facts.callback_date,
                callback_time=facts.callback_time,
            )
            imported += 1
    finally:
        repository.close()
    return imported


def main() -> None:
    parser = argparse.ArgumentParser(description="Import STRATO call summaries from Gmail")
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--token", required=True, type=Path)
    parser.add_argument("--structured-json-dir", type=Path)
    args = parser.parse_args()
    count = import_once(
        db_path=args.db,
        token_path=args.token,
        structured_json_dir=args.structured_json_dir,
    )
    print(f"{count} neue STRATO-Gespräche importiert")


if __name__ == "__main__":
    main()
