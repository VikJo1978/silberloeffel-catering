#!/usr/bin/env python3
"""Read-only verification of the PDF runtime and systemd alignment.

PDF_RUNTIME_VERIFICATION_SCRIPT_V1 (Slice C of PDF_RUNTIME_VENV_AND_SYSTEMD_V1).

This tool never mutates anything: no package installation, no `uv sync`, no
systemd unit installation, no `daemon-reload`, no service restart, no
override edit/removal, no application code change, no database write. It
only reads git-tracked files, runs `uv lock --check` (itself read-only),
queries systemd with `systemctl show` (never `systemctl cat` — `show` alone
is sufficient, since it already reports the effective, drop-in-resolved
property values this tool needs), reads `/proc/<pid>/cmdline` and
`/proc/<pid>/environ` (variable *names* only — values are never printed),
and runs the target interpreter with a side-effect-free `-c` probe to
introspect `sys.prefix` and import `reportlab`.

Why not `/proc/<pid>/exe`: the project venv is a standard stdlib venv, so
`.venv/bin/python3` is a *symlink* to the system interpreter. `/proc/<pid>/
exe` resolves through that symlink and reports the system Python for a
process that is genuinely running inside the venv — a false negative. The
reliable signals are the argv actually invoked (systemd's own resolved
`argv[]=`, or `/proc/<pid>/cmdline`) and an independent probe of the same
interpreter *path* run separately. A live process's own `sys.prefix` cannot
be read without code injection or a debugger, which this tool does not do —
see `_HOST_LIMITATIONS` below.

Two modes, one of which must be selected explicitly (no silent default):

    --repository-only   No systemd or production access. Safe for CI and any
                         checkout. Verifies pyproject.toml/uv.lock, that
                         `uv lock --check` is clean, and that the tracked
                         office-api/office-panel units declare the expected
                         venv interpreter, module and arguments.

    --host-runtime       Adds: the real `.venv` interpreter runs and reports
                         the expected sys.prefix; `reportlab` is importable,
                         is version 5.0.0, and lives inside the venv;
                         required OFFICE_PDF_* variables are present (never
                         their values) in each service's actual process
                         environment; the effective (loaded) systemd
                         ExecStart is compared against the tracked target,
                         classifying the result as READY_WITHOUT_OVERRIDE or
                         READY_WITH_COMPATIBLE_OVERRIDE (both are success) or
                         MISMATCHED_OVERRIDE (failure); each service is
                         active and its running command line matches.

Exit code 0 only when every check that ran passed. Non-zero otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

# --- constants ----------------------------------------------------------

EXPECTED_REPORTLAB_VERSION = "5.0.0"

# In-scope services only. catering-kiosk and catering-website-intake do not
# import reportlab and are never inspected by this script.
SERVICES: tuple[str, ...] = ("catering-office-api", "catering-office-panel")

TRACKED_UNIT_FILES: dict[str, str] = {
    "catering-office-api": "catering-office-api.service",
    "catering-office-panel": "catering-office-panel.service",
}

# The absolute path baked into the tracked unit files. This is a
# production-host fact (the repository is checked out at exactly this path
# on the one host the units target), not something --repo-root can move —
# overriding --repo-root changes where *this script* looks for pyproject.toml
# / uv.lock / unit files for local testing, it does not change what those
# unit files are expected to declare.
EXPECTED_VENV_INTERPRETER = (
    "/home/viktor/projects/silberloeffel-catering/.venv/bin/python3"
)

EXPECTED_UNIT_ARGV: dict[str, list[str]] = {
    "catering-office-api": [
        EXPECTED_VENV_INTERPRETER,
        "-m",
        "catering_system.ui.office_api",
        "--db",
        "/home/viktor/catering-runtime/core.db",
        "--host",
        "100.109.6.74",
        "--port",
        "8084",
    ],
    "catering-office-panel": [
        EXPECTED_VENV_INTERPRETER,
        "-m",
        "catering_system.ui.office_panel",
        "--db",
        "/home/viktor/catering-runtime/core.db",
        "--port",
        "8081",
    ],
}

REQUIRED_PDF_ENV_VARS: tuple[str, ...] = (
    "OFFICE_PDF_COMPANY_LEGAL_NAME",
    "OFFICE_PDF_COMPANY_ADDRESS_LINES",
    "OFFICE_PDF_ACCEPTANCE_STATEMENT",
)
OPTIONAL_LOGO_PATH_VAR = "OFFICE_PDF_LOGO_PATH"

_SUBPROCESS_TIMEOUT_SECONDS = 10.0

# A live process's own sys.prefix cannot be read without attaching a
# debugger or injecting code — both out of scope for a read-only tool. This
# message is surfaced once in host-runtime output rather than silently
# omitted, per the design brief.
_HOST_LIMITATIONS = (
    "Live process sys.prefix cannot be verified without code injection or a "
    "debugger; relying instead on the effective systemd ExecStart, the "
    "process command line (/proc/<pid>/cmdline), and an independent probe "
    "of the same interpreter path run separately. /proc/<pid>/exe is not "
    "used as evidence of venv use: .venv/bin/python3 is a symlink to the "
    "system interpreter, so /proc/<pid>/exe resolves to the system path "
    "even for a process genuinely running inside the venv."
)

_PROBE_SCRIPT = """
import json, sys
result = {
    "executable": sys.executable,
    "prefix": sys.prefix,
    "base_prefix": sys.base_prefix,
    "version": sys.version.split()[0],
}
try:
    import reportlab
    result["reportlab_version"] = reportlab.Version
    result["reportlab_file"] = str(reportlab.__file__)
except Exception as exc:  # noqa: BLE001 - reported, not raised
    result["reportlab_error"] = f"{type(exc).__name__}: {exc}"
print(json.dumps(result))
"""


# --- result model ---------------------------------------------------------


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    code: str
    message: str


@dataclass
class Report:
    mode: str
    checks: list[CheckResult] = field(default_factory=list)

    def record(self, name: str, ok: bool, code: str, message: str) -> CheckResult:
        result = CheckResult(name=name, ok=ok, code=code, message=message)
        self.checks.append(result)
        return result

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_json(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "ok": self.ok,
            "checks": [
                {
                    "name": c.name,
                    "ok": c.ok,
                    "code": c.code,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }

    def render_human(self) -> str:
        lines = [f"PDF runtime verification — mode: {self.mode}", ""]
        for check in self.checks:
            marker = "PASS" if check.ok else "FAIL"
            lines.append(f"[{marker}] {check.code}: {check.message}")
        lines.append("")
        lines.append("OVERALL: " + ("OK" if self.ok else "FAILED"))
        return "\n".join(lines)


# --- subprocess plumbing (isolated for testability) ------------------------


def _run(
    cmd: Sequence[str],
    timeout: float = _SUBPROCESS_TIMEOUT_SECONDS,
    cwd: Path | None = None,
):
    """The only place that shells out. No shell=True, explicit timeout.

    Tests replace this function (module-level monkeypatch) to supply canned
    output instead of requiring a real systemd host or a real venv.
    """
    return subprocess.run(
        list(cmd),
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


class CommandUnavailable(RuntimeError):
    """Raised when the target command could not be launched at all — the
    binary is missing, not executable, or the launch otherwise failed at the
    OS level (covers FileNotFoundError, PermissionError, NotADirectoryError,
    and similar subprocess-launch OSErrors uniformly)."""


class ExecStartParseError(ValueError):
    """Raised when an ExecStart value cannot be tokenized (e.g. unbalanced
    quoting). Callers convert this into a clean failed CheckResult instead of
    letting shlex's ValueError propagate as an uncaught traceback."""


def _run_or_raise(
    cmd: Sequence[str],
    timeout: float = _SUBPROCESS_TIMEOUT_SECONDS,
    cwd: Path | None = None,
):
    try:
        return _run(cmd, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired as exc:
        raise CommandUnavailable(f"timed out after {timeout}s: {exc}") from exc
    except OSError as exc:
        # FileNotFoundError (binary missing) is an OSError subclass, so this
        # also covers PermissionError (exists but not executable) and other
        # exec-time failures without needing a separate except clause.
        raise CommandUnavailable(f"{type(exc).__name__}: {exc}") from exc


# --- repository-state checks (safe in both modes) ---------------------------


def check_repository_state(report: Report, repo_root: Path) -> None:
    if not repo_root.is_dir():
        report.record(
            "repository_root",
            False,
            "REPO_ROOT_NOT_FOUND",
            f"repository root does not exist: {repo_root}",
        )
        return
    report.record("repository_root", True, "OK", f"repository root: {repo_root}")

    pyproject = repo_root / "pyproject.toml"
    if pyproject.is_file():
        report.record("pyproject_exists", True, "OK", f"found {pyproject}")
    else:
        report.record(
            "pyproject_exists",
            False,
            "PYPROJECT_MISSING",
            f"pyproject.toml not found at {pyproject}",
        )
        return

    lock = repo_root / "uv.lock"
    if lock.is_file():
        report.record("uv_lock_exists", True, "OK", f"found {lock}")
    else:
        report.record(
            "uv_lock_exists",
            False,
            "LOCK_MISSING",
            f"uv.lock not found at {lock}",
        )
        return

    try:
        result = _run_or_raise(["uv", "lock", "--check"], timeout=60.0, cwd=repo_root)
    except CommandUnavailable as exc:
        report.record(
            "uv_lock_check",
            False,
            "LOCK_OUT_OF_DATE",
            f"could not run `uv lock --check` (uv unavailable): {exc}",
        )
        return
    if result.returncode == 0:
        report.record("uv_lock_check", True, "OK", "uv.lock matches pyproject.toml")
    else:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        tail = detail[-1] if detail else "uv lock --check failed"
        report.record(
            "uv_lock_check",
            False,
            "LOCK_OUT_OF_DATE",
            f"uv.lock does not match pyproject.toml: {tail}",
        )


# --- tracked systemd unit checks (safe in both modes) -----------------------


def _parse_exec_start(unit_text: str) -> list[str] | None:
    """Returns None when no ExecStart line is present (or it's empty).
    Raises ExecStartParseError — never a bare shlex ValueError — when a line
    is present but its syntax can't be tokenized (e.g. unbalanced quoting)."""
    for line in unit_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("ExecStart="):
            value = stripped[len("ExecStart=") :].strip()
            if not value:
                return None
            try:
                return shlex.split(value)
            except ValueError as exc:
                raise ExecStartParseError(
                    f"ExecStart has malformed syntax: {exc}"
                ) from exc
    return None


def check_tracked_units(report: Report, repo_root: Path) -> None:
    for service, filename in TRACKED_UNIT_FILES.items():
        unit_path = repo_root / "infra" / "systemd" / filename
        name = f"tracked_unit[{service}]"
        if not unit_path.is_file():
            report.record(
                name,
                False,
                "TRACKED_UNIT_MISSING",
                f"{unit_path} not found",
            )
            continue
        try:
            argv = _parse_exec_start(unit_path.read_text(encoding="utf-8"))
        except ExecStartParseError as exc:
            report.record(
                name,
                False,
                "TRACKED_UNIT_MISMATCH",
                f"{filename}: {exc}",
            )
            continue
        expected = EXPECTED_UNIT_ARGV[service]
        if argv == expected:
            report.record(
                name,
                True,
                "OK",
                f"{filename} declares the expected venv interpreter, "
                "module and arguments",
            )
        else:
            report.record(
                name,
                False,
                "TRACKED_UNIT_MISMATCH",
                f"{filename} ExecStart is {argv!r}, expected {expected!r}",
            )


# --- host-runtime: python interpreter + reportlab ---------------------------


@dataclass(frozen=True)
class InterpreterProbe:
    ok: bool
    executable: str | None = None
    prefix: str | None = None
    base_prefix: str | None = None
    version: str | None = None
    reportlab_version: str | None = None
    reportlab_file: str | None = None
    reportlab_error: str | None = None
    error: str | None = None


def probe_interpreter(python_path: Path) -> InterpreterProbe:
    try:
        result = _run_or_raise([str(python_path), "-c", _PROBE_SCRIPT], timeout=30.0)
    except CommandUnavailable as exc:
        return InterpreterProbe(ok=False, error=str(exc))
    if result.returncode != 0:
        stderr_tail = (result.stderr or "").strip().splitlines()
        tail = stderr_tail[-1] if stderr_tail else f"exit code {result.returncode}"
        return InterpreterProbe(ok=False, error=tail)
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as exc:
        return InterpreterProbe(ok=False, error=f"unparseable probe output: {exc}")
    return InterpreterProbe(
        ok=True,
        executable=data.get("executable"),
        prefix=data.get("prefix"),
        base_prefix=data.get("base_prefix"),
        version=data.get("version"),
        reportlab_version=data.get("reportlab_version"),
        reportlab_file=data.get("reportlab_file"),
        reportlab_error=data.get("reportlab_error"),
    )


def check_python_runtime(report: Report, venv_path: Path) -> InterpreterProbe | None:
    python_path = venv_path / "bin" / "python3"
    if not python_path.exists():
        report.record(
            "runtime_interpreter_present",
            False,
            "RUNTIME_INTERPRETER_MISSING",
            f"{python_path} does not exist",
        )
        return None
    if not (python_path.is_file() or python_path.is_symlink()):
        report.record(
            "runtime_interpreter_present",
            False,
            "RUNTIME_INTERPRETER_MISSING",
            f"{python_path} is not a regular file or symlink",
        )
        return None
    if not os.access(python_path, os.X_OK):
        report.record(
            "runtime_interpreter_present",
            False,
            "RUNTIME_INTERPRETER_MISSING",
            f"{python_path} exists but is not executable",
        )
        return None
    report.record(
        "runtime_interpreter_present",
        True,
        "OK",
        f"{python_path} exists and is executable",
    )

    probe = probe_interpreter(python_path)
    if not probe.ok:
        report.record(
            "runtime_interpreter_runs",
            False,
            "RUNTIME_INTERPRETER_MISSING",
            f"{python_path} did not run successfully: {probe.error}",
        )
        return probe
    report.record(
        "runtime_interpreter_runs",
        True,
        "OK",
        f"{python_path} runs (Python {probe.version})",
    )

    expected_prefix = str(venv_path)
    prefix_matches = probe.prefix == expected_prefix
    base_differs = probe.base_prefix is not None and probe.base_prefix != probe.prefix
    if prefix_matches and base_differs:
        report.record(
            "venv_prefix",
            True,
            "OK",
            f"sys.prefix={probe.prefix} (base_prefix differs, venv active)",
        )
    else:
        report.record(
            "venv_prefix",
            False,
            "VENV_PREFIX_MISMATCH",
            f"sys.prefix={probe.prefix!r} base_prefix={probe.base_prefix!r}, "
            f"expected prefix {expected_prefix!r} with base_prefix differing",
        )

    if probe.reportlab_version is not None:
        report.record(
            "reportlab_importable",
            True,
            "OK",
            f"reportlab {probe.reportlab_version} importable",
        )
        if probe.reportlab_version == EXPECTED_REPORTLAB_VERSION:
            report.record(
                "reportlab_version",
                True,
                "OK",
                f"reportlab version {probe.reportlab_version} matches expected "
                f"{EXPECTED_REPORTLAB_VERSION}",
            )
        else:
            report.record(
                "reportlab_version",
                False,
                "REPORTLAB_VERSION_MISMATCH",
                f"reportlab version {probe.reportlab_version!r} != expected "
                f"{EXPECTED_REPORTLAB_VERSION!r}",
            )
        reportlab_file = probe.reportlab_file
        located_in_venv = bool(
            reportlab_file
            and Path(reportlab_file).resolve().is_relative_to(venv_path.resolve())
        )
        report.record(
            "reportlab_location",
            located_in_venv,
            "OK" if located_in_venv else "REPORTLAB_LOCATION_OUTSIDE_VENV",
            (
                f"reportlab installed inside {venv_path}"
                if located_in_venv
                else f"reportlab location is outside {venv_path}"
            ),
        )
    else:
        report.record(
            "reportlab_importable",
            False,
            "REPORTLAB_MISSING",
            f"import reportlab failed: {probe.reportlab_error}",
        )
    return probe


# --- host-runtime: systemd effective configuration --------------------------


def _systemctl_show(service: str, *properties: str) -> dict[str, str] | None:
    args = ["systemctl", "show", service]
    for prop in properties:
        args += ["-p", prop]
    try:
        result = _run_or_raise(args, timeout=15.0)
    except CommandUnavailable:
        return None
    if result.returncode != 0:
        return None
    # `systemctl show -p A -p B` prints exactly one "Key=Value" line per
    # requested property (confirmed against the real production output for
    # ExecStart/FragmentPath/DropInPaths/ActiveState/MainPID) — no
    # multi-line values to reassemble here.
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, sep, value = line.partition("=")
        if sep and key in properties:
            values[key] = value
    return values


def _extract_effective_argv(exec_start_value: str) -> list[str] | None:
    """Returns None when no argv[]= segment is present. Raises
    ExecStartParseError — never a bare shlex ValueError — when a segment is
    present but its syntax can't be tokenized (e.g. unbalanced quoting)."""
    marker = "argv[]="
    start = exec_start_value.find(marker)
    if start == -1:
        return None
    start += len(marker)
    end = exec_start_value.find(" ;", start)
    segment = exec_start_value[start:end] if end != -1 else exec_start_value[start:]
    try:
        return shlex.split(segment.strip())
    except ValueError as exc:
        raise ExecStartParseError(
            f"effective ExecStart has malformed syntax: {exc}"
        ) from exc


def check_effective_systemd(report: Report, service: str) -> dict[str, str] | None:
    props = _systemctl_show(
        service, "ExecStart", "FragmentPath", "DropInPaths", "ActiveState", "MainPID"
    )
    name = f"effective_systemd[{service}]"
    if props is None:
        report.record(
            name,
            False,
            "TRACKED_UNIT_MISMATCH",
            f"could not query systemctl for {service} (systemctl unavailable "
            "or command failed)",
        )
        return None

    exec_start = props.get("ExecStart", "")
    expected_argv = EXPECTED_UNIT_ARGV.get(service)
    drop_in_paths = props.get("DropInPaths", "").strip()
    override_present = bool(drop_in_paths)

    try:
        effective_argv = _extract_effective_argv(exec_start)
    except ExecStartParseError as exc:
        code = "MISMATCHED_OVERRIDE" if override_present else "TRACKED_UNIT_MISMATCH"
        report.record(name, False, code, f"{service}: {exc}")
        return props

    if effective_argv is None:
        report.record(
            name,
            False,
            "TRACKED_UNIT_MISMATCH",
            f"{service}: could not parse effective ExecStart",
        )
        return props

    if effective_argv != expected_argv:
        code = "MISMATCHED_OVERRIDE" if override_present else "TRACKED_UNIT_MISMATCH"
        report.record(
            name,
            False,
            code,
            f"{service}: effective command {effective_argv!r} does not match "
            f"expected {expected_argv!r}"
            + (f" (override: {drop_in_paths})" if override_present else ""),
        )
        return props

    if override_present:
        report.record(
            name,
            True,
            "READY_WITH_COMPATIBLE_OVERRIDE",
            f"{service}: effective command matches the tracked target via a "
            f"compatible override ({drop_in_paths})",
        )
    else:
        report.record(
            name,
            True,
            "READY_WITHOUT_OVERRIDE",
            f"{service}: effective command matches the tracked target with "
            "no override present",
        )
    return props


# --- host-runtime: PDF configuration presence --------------------------------


def _read_environ_names(pid: str) -> set[str] | None:
    environ_path = Path(f"/proc/{pid}/environ")
    try:
        raw = environ_path.read_bytes()
    except OSError:
        return None
    names = set()
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        key, _, _value = entry.partition(b"=")
        names.add(key.decode("utf-8", errors="replace"))
    return names


def _read_cmdline(pid: str) -> list[str] | None:
    cmdline_path = Path(f"/proc/{pid}/cmdline")
    try:
        raw = cmdline_path.read_bytes()
    except OSError:
        return None
    parts = [p.decode("utf-8", errors="replace") for p in raw.split(b"\0") if p]
    return parts or None


def check_pdf_config_and_process(
    report: Report, service: str, props: dict[str, str] | None
) -> None:
    """`props` is the dict returned by check_effective_systemd — this reuses
    the already-fetched ActiveState/MainPID rather than re-querying. Both
    ActiveState == 'active' and a non-zero MainPID are required: MainPID
    alone is not sufficient evidence (a unit mid-'activating' can already
    have a forked-but-not-yet-active MainPID), and ActiveState alone doesn't
    tell us which PID to inspect."""
    active_name = f"service_active[{service}]"
    active_state = props.get("ActiveState") if props else None
    main_pid = props.get("MainPID") if props else None
    has_pid = bool(main_pid) and main_pid not in ("0", "")
    if active_state != "active" or not has_pid:
        report.record(
            active_name,
            False,
            "SERVICE_INACTIVE",
            f"{service}: not active (ActiveState={active_state!r}, "
            f"MainPID={main_pid!r})",
        )
        report.record(
            f"pdf_config[{service}]",
            False,
            "PDF_CONFIG_MISSING",
            f"{service}: cannot inspect environment, service is not active",
        )
        return
    assert main_pid is not None  # narrowed by has_pid above
    report.record(active_name, True, "OK", f"{service}: active, MainPID={main_pid}")

    names = _read_environ_names(main_pid)
    if names is None:
        report.record(
            f"pdf_config[{service}]",
            False,
            "PDF_CONFIG_MISSING",
            f"{service}: /proc/{main_pid}/environ not readable",
        )
    else:
        missing = [v for v in REQUIRED_PDF_ENV_VARS if v not in names]
        if missing:
            report.record(
                f"pdf_config[{service}]",
                False,
                "PDF_CONFIG_MISSING",
                f"{service}: missing required variable(s): "
                + ", ".join(sorted(missing))
                + " (values never inspected or printed)",
            )
        else:
            report.record(
                f"pdf_config[{service}]",
                True,
                "OK",
                f"{service}: all required OFFICE_PDF_* variables are present "
                "(values not inspected)",
            )
        if OPTIONAL_LOGO_PATH_VAR in names:
            # The variable's own value is a file path, not a secret, but per
            # the read-only contract for this tool it is never printed here
            # either — only whether it resolves to a readable regular file.
            logo_ok = _check_logo_path_readable(main_pid, OPTIONAL_LOGO_PATH_VAR)
            report.record(
                f"pdf_logo_path[{service}]",
                logo_ok,
                "OK" if logo_ok else "PDF_CONFIG_MISSING",
                f"{service}: {OPTIONAL_LOGO_PATH_VAR} is "
                + (
                    "a readable regular file"
                    if logo_ok
                    else "set but not a readable regular file"
                ),
            )
        else:
            report.record(
                f"pdf_logo_path[{service}]",
                True,
                "OK",
                f"{service}: {OPTIONAL_LOGO_PATH_VAR} not set (optional)",
            )

    cmdline = _read_cmdline(main_pid)
    expected_argv = EXPECTED_UNIT_ARGV.get(service)
    if cmdline is None:
        report.record(
            f"process_cmdline[{service}]",
            False,
            "TRACKED_UNIT_MISMATCH",
            f"{service}: /proc/{main_pid}/cmdline not readable",
        )
    elif cmdline == expected_argv:
        report.record(
            f"process_cmdline[{service}]",
            True,
            "OK",
            f"{service}: running command line matches the expected target",
        )
    else:
        report.record(
            f"process_cmdline[{service}]",
            False,
            "TRACKED_UNIT_MISMATCH",
            f"{service}: running command line {cmdline!r} does not match "
            f"expected {expected_argv!r}",
        )


def _check_logo_path_readable(pid: str, var_name: str) -> bool:
    """Reads the variable's own value only to test file readability — the
    value itself (a filesystem path) is never printed or stored."""
    names = _read_environ_names(pid)
    if names is None or var_name not in names:
        return False
    environ_path = Path(f"/proc/{pid}/environ")
    try:
        raw = environ_path.read_bytes()
    except OSError:
        return False
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        key, sep, value = entry.partition(b"=")
        if sep and key.decode("utf-8", errors="replace") == var_name:
            candidate = Path(value.decode("utf-8", errors="replace"))
            return candidate.is_file()
    return False


# --- mode assembly ------------------------------------------------------


def run_repository_only(repo_root: Path) -> Report:
    report = Report(mode="repository-only")
    check_repository_state(report, repo_root)
    check_tracked_units(report, repo_root)
    return report


def run_host_runtime(repo_root: Path, venv_path: Path) -> Report:
    report = Report(mode="host-runtime")
    check_repository_state(report, repo_root)
    check_tracked_units(report, repo_root)
    check_python_runtime(report, venv_path)

    report.checks.append(
        CheckResult(
            name="process_prefix_limitation",
            ok=True,
            code="OK",
            message=_HOST_LIMITATIONS,
        )
    )

    for service in SERVICES:
        props = check_effective_systemd(report, service)
        check_pdf_config_and_process(report, service, props)

    return report


# --- CLI ------------------------------------------------------------------


def _default_repo_root() -> Path:
    # infra/deploy/verify_pdf_runtime.py -> repo root is two parents up.
    return Path(__file__).resolve().parents[2]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only verification of the PDF runtime and systemd "
            "alignment. Never mutates anything — see module docstring."
        )
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--repository-only",
        action="store_true",
        help="Checks that need no systemd or production access (CI-safe).",
    )
    mode.add_argument(
        "--host-runtime",
        action="store_true",
        help="Adds real venv/reportlab/systemd/process checks. Run on the "
        "target host only.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Override the repository root (defaults to the checkout this "
        "script lives in). Use for local/test runs.",
    )
    parser.add_argument(
        "--venv-path",
        type=Path,
        default=None,
        help="Override the expected venv path for --host-runtime (defaults "
        "to <repo-root>/.venv). Use for local/test runs.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON in addition to the human-readable report.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    repo_root = args.repo_root or _default_repo_root()

    if args.repository_only:
        report = run_repository_only(repo_root)
    else:
        venv_path = args.venv_path or (repo_root / ".venv")
        report = run_host_runtime(repo_root, venv_path)

    if args.json:
        print(json.dumps(report.to_json(), indent=2, sort_keys=True))
    else:
        print(report.render_human())

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
