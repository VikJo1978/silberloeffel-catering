#!/usr/bin/env python3
"""Import explicit production station requirements and date capacities into Core.

The input file is declarative business truth. This command never infers station
assignments, load units, or capacity from catalog categories or order history.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from catering_system.services.production_capacity_import import (
    apply_production_capacity_config,
    parse_production_capacity_config,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="Path to core.db")
    parser.add_argument("--config", required=True, help="Path to explicit capacity JSON")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the entire config and references without writing facts",
    )
    args = parser.parse_args(argv)

    db_path = Path(args.db)
    config_path = Path(args.config)
    if not db_path.exists():
        print(f"database not found: {db_path}", file=sys.stderr)
        return 1
    if not config_path.exists():
        print(f"config file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
        plan = parse_production_capacity_config(payload)
        result = apply_production_capacity_config(
            db_path,
            plan,
            dry_run=args.dry_run,
        )
    except (ValueError, json.JSONDecodeError, sqlite3.DatabaseError) as exc:
        print(f"capacity import failed: {exc}", file=sys.stderr)
        return 1

    action = "validated" if args.dry_run else "applied"
    print(
        f"capacity config {action}: "
        f"stations={result.stations} "
        f"requirements={result.requirements} "
        f"capacity_days={result.capacity_days}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
