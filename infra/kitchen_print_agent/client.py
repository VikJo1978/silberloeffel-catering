"""Minimal HTTP client for the Kitchen Print Agent API."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from kitchen_print_agent.models import ClaimDocument, ClaimResponse, RejectResponse


@dataclass(frozen=True)
class KitchenApiClientError(Exception):
    status: int
    error: str

    def __str__(self) -> str:
        return f"Kitchen API error {self.status}: {self.error}"


class KitchenPrintAgentClient:
    def __init__(self, api_url: str, agent_token: str) -> None:
        self._api_url = api_url.rstrip("/")
        self._agent_token = agent_token

    def claim_next(self, command_id: str) -> ClaimResponse:
        status, body = self._post(
            f"{self._api_url}/kitchen/v1/print-jobs/claim-next",
            {"command_id": command_id},
        )
        if status == 204:
            response_command_id = body.get("command_id", command_id)
            return ClaimResponse(
                command_id=str(response_command_id),
                print_job_id=None,
                document=None,
            )
        if status != 200:
            raise KitchenApiClientError(status, str(body.get("error", "unknown")))

        document_payload = body.get("document")
        document = None
        if isinstance(document_payload, dict):
            content_type = document_payload["content_type"]
            body_base64 = document_payload["body_base64"]
            if not isinstance(content_type, str) or not isinstance(body_base64, str):
                raise KitchenApiClientError(status, "invalid_response")
            document = ClaimDocument(
                content_type=content_type,
                body=base64.b64decode(body_base64),
            )

        print_job_id = body.get("print_job_id")
        if not isinstance(print_job_id, str):
            raise KitchenApiClientError(status, "invalid_response")

        return ClaimResponse(
            command_id=str(body["command_id"]),
            print_job_id=print_job_id,
            document=document,
        )

    def reject(
        self,
        print_job_id: str,
        command_id: str,
        rejection_code: str,
    ) -> RejectResponse:
        status, body = self._post(
            f"{self._api_url}/kitchen/v1/print-jobs/{print_job_id}/reject",
            {
                "command_id": command_id,
                "rejection_code": rejection_code,
            },
        )
        if status != 200:
            raise KitchenApiClientError(status, str(body.get("error", "unknown")))

        response_print_job_id = body.get("print_job_id")
        response_rejection_code = body.get("rejection_code")
        if not isinstance(response_print_job_id, str) or not isinstance(
            response_rejection_code, str
        ):
            raise KitchenApiClientError(status, "invalid_response")

        return RejectResponse(
            command_id=str(body["command_id"]),
            print_job_id=response_print_job_id,
            rejection_code=response_rejection_code,
        )

    def _post(self, url: str, payload: dict[str, str]) -> tuple[int, dict[str, object]]:
        data = json.dumps(payload, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._agent_token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code

        if not raw:
            return status, {}

        parsed = json.loads(raw.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise KitchenApiClientError(status, "invalid_response")
        return status, parsed
