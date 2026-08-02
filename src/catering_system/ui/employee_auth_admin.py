"""Operator CLI for AUTH_RBAC_V1 bootstrap and recovery."""

from __future__ import annotations

import argparse
import getpass
from pathlib import Path

from catering_system.repositories.bootstrap_employee_auth_schema import (
    bootstrap_employee_auth_schema,
)
from catering_system.repositories.core_transaction import open_core_connection
from catering_system.repositories.sqlite_employee_auth_repository import (
    SQLiteEmployeeAuthRepository,
)
from catering_system.services.employee_auth_service import EmployeeAuthService


def _read_password(args: argparse.Namespace, *, prompt: str) -> str:
    if args.password_stdin:
        import sys

        value = sys.stdin.readline().rstrip("\n")
    else:
        value = getpass.getpass(prompt)
    if not value:
        raise SystemExit("password must not be empty")
    return value


def _service(db_path: str | Path) -> EmployeeAuthService:
    connection = open_core_connection(db_path)
    bootstrap_employee_auth_schema(connection)
    repository = SQLiteEmployeeAuthRepository.from_connection(connection)
    return EmployeeAuthService(repository)


def main() -> None:
    parser = argparse.ArgumentParser(description="Employee auth bootstrap/recovery CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser(
        "bootstrap-superadmin",
        help="Create the first SUPERADMIN when no employee account exists",
    )
    bootstrap.add_argument(
        "--db", required=True, help="Path to the Core SQLite database"
    )
    bootstrap.add_argument("--username", required=True)
    bootstrap.add_argument("--display-name", required=True)
    bootstrap.add_argument("--email")
    bootstrap.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the temporary password from stdin instead of prompting",
    )

    reset = subparsers.add_parser(
        "reset-password",
        help="Audited local recovery reset for an existing employee account",
    )
    reset.add_argument("--db", required=True, help="Path to the Core SQLite database")
    reset.add_argument("--username", required=True)
    reset.add_argument(
        "--password-stdin",
        action="store_true",
        help="Read the new temporary password from stdin instead of prompting",
    )

    args = parser.parse_args()
    service = _service(args.db)
    if args.command == "bootstrap-superadmin":
        password = _read_password(
            args, prompt="Temporary password for first SUPERADMIN: "
        )
        account = service.bootstrap_superadmin(
            username=args.username,
            display_name=args.display_name,
            email=args.email,
            password=password,
            metadata={"operator_flow": "bootstrap-superadmin"},
        )
        print(
            f"Bootstrapped SUPERADMIN {account.username} ({account.display_name}); "
            "must_change_password=true"
        )
        return
    if args.command == "reset-password":
        password = _read_password(args, prompt="New temporary password: ")
        account = service.reset_password(
            actor=None,
            target_username=args.username,
            temporary_password=password,
            recovery=True,
        )
        print(
            f"Reset password for {account.username}; all existing sessions revoked; "
            "must_change_password=true"
        )
        return
    raise SystemExit(f"unknown command {args.command!r}")


if __name__ == "__main__":
    main()
