"""Entry point: python -m kitchen_print_agent"""

from __future__ import annotations

import logging
import sys

from kitchen_print_agent.agent import KitchenPrintAgent
from kitchen_print_agent.config import AgentConfig
from kitchen_print_agent.printer import CupsPrinterAdapter

_log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        config = AgentConfig.from_env()
    except KeyError as exc:
        _log.error("missing required environment variable: %s", exc.args[0])
        sys.exit(1)

    printer = CupsPrinterAdapter(config.printer_name)
    agent = KitchenPrintAgent.from_config(config, printer)
    _log.info(
        "starting kitchen print agent api=%s printer=%s",
        config.api_url,
        config.printer_name,
    )
    agent.run_forever()


if __name__ == "__main__":
    main()
