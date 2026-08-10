"""Runtime configuration for the kitchen print agent."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class AgentConfig:
    api_url: str
    agent_token: str
    poll_interval_seconds: float
    printer_name: str

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> AgentConfig:
        env = environ if environ is not None else os.environ
        return cls(
            api_url=env["KITCHEN_PRINT_API_URL"],
            agent_token=env["KITCHEN_PRINT_AGENT_TOKEN"],
            poll_interval_seconds=float(
                env.get("KITCHEN_PRINT_POLL_INTERVAL_SECONDS", "5")
            ),
            printer_name=env.get("KITCHEN_PRINT_PRINTER_NAME", ""),
        )
