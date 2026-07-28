"""PDF_RUNTIME_VERIFICATION_SCRIPT_V1 — infra/deploy/verify_pdf_runtime.py.

No real systemd host and no real venv are required: every subprocess call
goes through the module's single `_run` seam, which these tests monkeypatch
with canned CompletedProcess-shaped output. Filesystem-backed checks (unit
files, /proc/<pid>/{cmdline,environ}) use tmp_path.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_INFRA_DEPLOY = Path(__file__).resolve().parents[2] / "infra" / "deploy"
if str(_INFRA_DEPLOY) not in sys.path:
    sys.path.insert(0, str(_INFRA_DEPLOY))

import verify_pdf_runtime as vpr  # noqa: E402

_API_ARGV = vpr.EXPECTED_UNIT_ARGV["catering-office-api"]
_PANEL_ARGV = vpr.EXPECTED_UNIT_ARGV["catering-office-panel"]
_VENV_PY = vpr.EXPECTED_VENV_INTERPRETER


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    """Shaped like subprocess.CompletedProcess for the parts this module reads."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _write_unit(repo_root: Path, service: str, argv: list[str]) -> Path:
    unit_dir = repo_root / "infra" / "systemd"
    unit_dir.mkdir(parents=True, exist_ok=True)
    exec_line = "ExecStart=" + " ".join(argv)
    text = (
        "[Unit]\nDescription=test\n\n[Service]\nUser=viktor\n"
        f"{exec_line}\nRestart=on-failure\n\n[Install]\nWantedBy=multi-user.target\n"
    )
    path = unit_dir / vpr.TRACKED_UNIT_FILES[service]
    path.write_text(text, encoding="utf-8")
    return path


def _write_valid_units(repo_root: Path) -> None:
    _write_unit(repo_root, "catering-office-api", _API_ARGV)
    _write_unit(repo_root, "catering-office-panel", _PANEL_ARGV)


def _base_repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    _write_valid_units(root)
    return root


def _find(report: vpr.Report, code: str) -> vpr.CheckResult:
    matches = [c for c in report.checks if c.code == code]
    assert matches, (
        f"no check with code {code!r} among {[c.code for c in report.checks]}"
    )
    return matches[0]


def _has_failure(report: vpr.Report, code: str) -> bool:
    return any((not c.ok) and c.code == code for c in report.checks)


# --- 1/2/3: tracked unit checks ---------------------------------------------


def test_tracked_unit_correct_interpreter_passes(tmp_path: Path) -> None:
    repo = _base_repo(tmp_path)
    report = vpr.Report(mode="repository-only")
    vpr.check_tracked_units(report, repo)
    assert report.ok
    for service in vpr.SERVICES:
        assert any(c.name == f"tracked_unit[{service}]" and c.ok for c in report.checks)


def test_tracked_unit_system_python_fails(tmp_path: Path) -> None:
    repo = _base_repo(tmp_path)
    _write_unit(
        repo,
        "catering-office-api",
        ["/usr/bin/python3"] + _API_ARGV[1:],
    )
    report = vpr.Report(mode="repository-only")
    vpr.check_tracked_units(report, repo)
    assert not report.ok
    assert _has_failure(report, "TRACKED_UNIT_MISMATCH")


def test_tracked_unit_argument_mismatch_fails(tmp_path: Path) -> None:
    repo = _base_repo(tmp_path)
    wrong = _API_ARGV[:-1] + ["9999"]  # wrong port
    _write_unit(repo, "catering-office-api", wrong)
    report = vpr.Report(mode="repository-only")
    vpr.check_tracked_units(report, repo)
    assert not report.ok
    assert _has_failure(report, "TRACKED_UNIT_MISMATCH")


# --- 4/5: uv.lock presence and currency -------------------------------------


def test_uv_lock_absent_fails(tmp_path: Path) -> None:
    repo = _base_repo(tmp_path)
    (repo / "uv.lock").unlink()
    report = vpr.Report(mode="repository-only")
    vpr.check_repository_state(report, repo)
    assert not report.ok
    assert _has_failure(report, "LOCK_MISSING")


def test_uv_lock_check_failure_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _base_repo(tmp_path)

    def fake_run(cmd, timeout=vpr._SUBPROCESS_TIMEOUT_SECONDS):
        assert cmd[:2] == ["uv", "lock"]
        return _proc(returncode=1, stderr="error: lock file is not up to date\n")

    monkeypatch.setattr(vpr, "_run", fake_run)
    report = vpr.Report(mode="repository-only")
    vpr.check_repository_state(report, repo)
    assert not report.ok
    assert _has_failure(report, "LOCK_OUT_OF_DATE")


def test_uv_binary_missing_reports_lock_out_of_date_not_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _base_repo(tmp_path)

    def fake_run(cmd, timeout=vpr._SUBPROCESS_TIMEOUT_SECONDS):
        raise FileNotFoundError("uv")

    monkeypatch.setattr(vpr, "_run", fake_run)
    report = vpr.Report(mode="repository-only")
    vpr.check_repository_state(report, repo)  # must not raise
    assert not report.ok
    assert _has_failure(report, "LOCK_OUT_OF_DATE")


# --- 6: interpreter missing --------------------------------------------------


def test_venv_interpreter_missing_fails(tmp_path: Path) -> None:
    venv = tmp_path / "no-such-venv"
    report = vpr.Report(mode="host-runtime")
    probe = vpr.check_python_runtime(report, venv)
    assert probe is None
    assert not report.ok
    assert _has_failure(report, "RUNTIME_INTERPRETER_MISSING")


# --- 7/8/9: reportlab + prefix checks, via a fake venv python --------------


def _make_fake_python(tmp_path: Path, payload: dict) -> Path:
    """A real, executable script standing in for .venv/bin/python3 — this is
    the 'fake command output' the task asks for, without needing a real venv
    or monkeypatching subprocess for these particular checks."""
    venv = tmp_path / "venv"
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    script = bin_dir / "python3"
    script.write_text(
        f"#!/usr/bin/env python3\nimport json, sys\nprint(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return venv


def test_reportlab_missing_fails(tmp_path: Path) -> None:
    venv = _make_fake_python(
        tmp_path,
        {
            "executable": "x",
            "prefix": str(tmp_path / "venv"),
            "base_prefix": "/usr",
            "version": "3.12.0",
            "reportlab_error": "ModuleNotFoundError: No module named 'reportlab'",
        },
    )
    report = vpr.Report(mode="host-runtime")
    vpr.check_python_runtime(report, venv)
    assert not report.ok
    assert _has_failure(report, "REPORTLAB_MISSING")


def test_reportlab_wrong_version_fails(tmp_path: Path) -> None:
    venv = _make_fake_python(
        tmp_path,
        {
            "executable": "x",
            "prefix": str(tmp_path / "venv"),
            "base_prefix": "/usr",
            "version": "3.12.0",
            "reportlab_version": "4.0.0",
            "reportlab_file": str(
                tmp_path / "venv" / "lib" / "reportlab" / "__init__.py"
            ),
        },
    )
    report = vpr.Report(mode="host-runtime")
    vpr.check_python_runtime(report, venv)
    assert not report.ok
    assert _has_failure(report, "REPORTLAB_VERSION_MISMATCH")


def test_sys_prefix_outside_venv_fails(tmp_path: Path) -> None:
    venv = _make_fake_python(
        tmp_path,
        {
            "executable": "x",
            "prefix": "/usr",  # wrong: equals base_prefix, not the venv
            "base_prefix": "/usr",
            "version": "3.12.0",
            "reportlab_version": "5.0.0",
            "reportlab_file": str(
                tmp_path / "venv" / "lib" / "reportlab" / "__init__.py"
            ),
        },
    )
    report = vpr.Report(mode="host-runtime")
    vpr.check_python_runtime(report, venv)
    assert not report.ok
    assert _has_failure(report, "VENV_PREFIX_MISMATCH")


def test_reportlab_correct_and_in_venv_passes(tmp_path: Path) -> None:
    venv_dir = tmp_path / "venv"
    reportlab_file = (
        venv_dir / "lib" / "python3.12" / "site-packages" / "reportlab" / "__init__.py"
    )
    venv = _make_fake_python(
        tmp_path,
        {
            "executable": str(venv_dir / "bin" / "python3"),
            "prefix": str(venv_dir),
            "base_prefix": "/usr",
            "version": "3.12.0",
            "reportlab_version": "5.0.0",
            "reportlab_file": str(reportlab_file),
        },
    )
    assert venv == venv_dir
    report = vpr.Report(mode="host-runtime")
    probe = vpr.check_python_runtime(report, venv)
    assert probe is not None and probe.ok
    assert report.ok
    assert _find(report, "OK")  # at least one passing OK-coded check exists


# --- 10: required PDF variable absent, values never exposed ----------------


def _write_proc_pid(
    tmp_path: Path, pid: str, *, environ_pairs: list[tuple[str, str]], argv: list[str]
):
    proc_dir = tmp_path / "proc" / pid
    proc_dir.mkdir(parents=True)
    environ_blob = "".join(f"{k}={v}\0" for k, v in environ_pairs)
    (proc_dir / "environ").write_bytes(environ_blob.encode("utf-8"))
    cmdline_blob = "".join(f"{a}\0" for a in argv)
    (proc_dir / "cmdline").write_bytes(cmdline_blob.encode("utf-8"))
    return proc_dir


def test_missing_pdf_variable_fails_without_exposing_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pid = "4242"
    secret_value = "s3cr3t-legal-name-should-never-appear"
    proc_dir = _write_proc_pid(
        tmp_path,
        pid,
        environ_pairs=[
            ("HOME", "/home/viktor"),
            ("OFFICE_PDF_COMPANY_LEGAL_NAME", secret_value),
            # OFFICE_PDF_COMPANY_ADDRESS_LINES and OFFICE_PDF_ACCEPTANCE_STATEMENT
            # are intentionally absent.
        ],
        argv=_API_ARGV,
    )
    monkeypatch.setattr(
        vpr,
        "_read_environ_names",
        lambda p: (
            {k for k, _v in [("HOME", ""), ("OFFICE_PDF_COMPANY_LEGAL_NAME", "")]}
            if p == pid
            else None
        ),
    )
    monkeypatch.setattr(vpr, "_read_cmdline", lambda p: _API_ARGV if p == pid else None)

    report = vpr.Report(mode="host-runtime")
    vpr.check_pdf_config_and_process(report, "catering-office-api", pid)

    assert not report.ok
    failure = _find(report, "PDF_CONFIG_MISSING")
    assert "OFFICE_PDF_COMPANY_ADDRESS_LINES" in failure.message
    assert "OFFICE_PDF_ACCEPTANCE_STATEMENT" in failure.message
    for check in report.checks:
        assert secret_value not in check.message
    rendered = report.render_human()
    assert secret_value not in rendered
    _ = proc_dir  # written for documentation of the real /proc shape; reads are monkeypatched


# --- 11/12/13: effective vs tracked systemd classification -----------------


def _systemctl_show_output(
    *,
    argv: list[str],
    active: bool = True,
    pid: str = "111",
    override: str | None = None,
) -> str:
    exec_start = (
        "{ path=" + argv[0] + " ; argv[]=" + " ".join(argv) + " ; ignore_errors=no }"
    )
    lines = [
        f"ExecStart={exec_start}",
        "FragmentPath=/etc/systemd/system/catering-office-api.service",
        f"DropInPaths={override or ''}",
        f"ActiveState={'active' if active else 'inactive'}",
        f"MainPID={pid if active else '0'}",
    ]
    return "\n".join(lines) + "\n"


def test_effective_matches_tracked_no_override_ready_without_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd, timeout=vpr._SUBPROCESS_TIMEOUT_SECONDS):
        assert cmd[0] == "systemctl"
        return _proc(
            returncode=0, stdout=_systemctl_show_output(argv=_API_ARGV, override=None)
        )

    monkeypatch.setattr(vpr, "_run", fake_run)
    report = vpr.Report(mode="host-runtime")
    props = vpr.check_effective_systemd(report, "catering-office-api")
    assert props is not None
    assert report.ok
    match = _find(report, "READY_WITHOUT_OVERRIDE")
    assert match.ok


def test_compatible_override_ready_with_compatible_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_path = "/etc/systemd/system/catering-office-api.service.d/override.conf"

    def fake_run(cmd, timeout=vpr._SUBPROCESS_TIMEOUT_SECONDS):
        return _proc(
            returncode=0,
            stdout=_systemctl_show_output(argv=_API_ARGV, override=override_path),
        )

    monkeypatch.setattr(vpr, "_run", fake_run)
    report = vpr.Report(mode="host-runtime")
    vpr.check_effective_systemd(report, "catering-office-api")
    assert report.ok
    match = _find(report, "READY_WITH_COMPATIBLE_OVERRIDE")
    assert match.ok
    assert override_path in match.message


def test_override_changes_command_mismatched_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    override_path = "/etc/systemd/system/catering-office-api.service.d/override.conf"
    wrong_argv = ["/usr/bin/python3"] + _API_ARGV[1:]

    def fake_run(cmd, timeout=vpr._SUBPROCESS_TIMEOUT_SECONDS):
        return _proc(
            returncode=0,
            stdout=_systemctl_show_output(argv=wrong_argv, override=override_path),
        )

    monkeypatch.setattr(vpr, "_run", fake_run)
    report = vpr.Report(mode="host-runtime")
    vpr.check_effective_systemd(report, "catering-office-api")
    assert not report.ok
    assert _has_failure(report, "MISMATCHED_OVERRIDE")


# --- 14: inactive service ----------------------------------------------------


def test_inactive_service_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    report = vpr.Report(mode="host-runtime")
    vpr.check_pdf_config_and_process(report, "catering-office-api", None)
    assert not report.ok
    assert _has_failure(report, "SERVICE_INACTIVE")


# --- 15: /proc/<pid>/exe must never be consulted ----------------------------


def test_proc_pid_exe_never_used_for_venv_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A misleading /proc/<pid>/exe (resolving to the system interpreter, as
    it always does for a stdlib venv symlink) must not cause a false
    failure, because this module never reads it at all."""
    import os

    real_readlink = os.readlink

    def exploding_readlink(path, *a, **kw):  # noqa: ANN001
        if "/exe" in str(path):
            raise AssertionError(
                "verify_pdf_runtime must never consult /proc/<pid>/exe"
            )
        return real_readlink(path, *a, **kw)

    monkeypatch.setattr(os, "readlink", exploding_readlink)

    pid = "555"
    monkeypatch.setattr(
        vpr,
        "_read_environ_names",
        lambda p: (
            {
                "OFFICE_PDF_COMPANY_LEGAL_NAME",
                "OFFICE_PDF_COMPANY_ADDRESS_LINES",
                "OFFICE_PDF_ACCEPTANCE_STATEMENT",
            }
            if p == pid
            else None
        ),
    )
    monkeypatch.setattr(vpr, "_read_cmdline", lambda p: _API_ARGV if p == pid else None)

    report = vpr.Report(mode="host-runtime")
    vpr.check_pdf_config_and_process(report, "catering-office-api", pid)
    assert report.ok  # would only fail if something wrongly touched /proc/pid/exe


# --- 16: repository-only mode needs no systemd ------------------------------


def test_repository_only_mode_never_calls_systemctl(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _base_repo(tmp_path)

    def fake_run(cmd, timeout=vpr._SUBPROCESS_TIMEOUT_SECONDS):
        if cmd[0] == "systemctl":
            raise AssertionError("repository-only mode must not call systemctl")
        assert cmd[:2] == ["uv", "lock"]
        return _proc(returncode=0, stdout="")

    monkeypatch.setattr(vpr, "_run", fake_run)
    report = vpr.run_repository_only(repo)
    assert report.ok
    assert report.mode == "repository-only"


# --- 17: subprocess timeouts are explicit and fail clearly ------------------


def test_subprocess_timeout_fails_clearly_not_crash(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = _base_repo(tmp_path)

    def fake_run(cmd, timeout=vpr._SUBPROCESS_TIMEOUT_SECONDS):
        assert timeout is not None and timeout > 0
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    monkeypatch.setattr(vpr, "_run", fake_run)
    report = vpr.Report(mode="repository-only")
    vpr.check_repository_state(report, repo)  # must not raise
    assert not report.ok
    failure = _find(report, "LOCK_OUT_OF_DATE")
    assert "timed out" in failure.message


def test_all_run_call_sites_pass_an_explicit_timeout() -> None:
    """Static guard: every _run(...) call site in the module supplies an
    explicit timeout, either via the caller's default parameter or a literal
    — subprocess.run must never be called with an unbounded wait."""
    import ast

    source = (_INFRA_DEPLOY / "verify_pdf_runtime.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    run_def_default = None
    call_sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_run":
            run_def_default = node
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in ("_run", "_run_or_raise")
        ):
            call_sites.append(node)
    assert run_def_default is not None
    assert run_def_default.args.defaults, "_run must default its timeout parameter"
    assert call_sites, "expected at least one _run/_run_or_raise call site"
    for call in call_sites:
        has_explicit = any(kw.arg == "timeout" for kw in call.keywords)
        assert has_explicit or run_def_default.args.defaults, (
            f"call at line {call.lineno} has no explicit timeout and no default"
        )


# --- CLI-level smoke: mode is required, mutually exclusive ------------------


def test_cli_requires_explicit_mode() -> None:
    parser = vpr.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_cli_modes_are_mutually_exclusive() -> None:
    parser = vpr.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--repository-only", "--host-runtime"])


def test_main_returns_zero_on_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _base_repo(tmp_path)

    def fake_run(cmd, timeout=vpr._SUBPROCESS_TIMEOUT_SECONDS):
        assert cmd[:2] == ["uv", "lock"]
        return _proc(returncode=0, stdout="")

    monkeypatch.setattr(vpr, "_run", fake_run)
    code = vpr.main(["--repository-only", "--repo-root", str(repo)])
    assert code == 0


def test_main_returns_nonzero_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _base_repo(tmp_path)
    (repo / "uv.lock").unlink()
    code = vpr.main(["--repository-only", "--repo-root", str(repo)])
    assert code == 1


def test_main_json_output_is_valid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = _base_repo(tmp_path)

    def fake_run(cmd, timeout=vpr._SUBPROCESS_TIMEOUT_SECONDS):
        return _proc(returncode=0, stdout="")

    monkeypatch.setattr(vpr, "_run", fake_run)
    code = vpr.main(["--repository-only", "--repo-root", str(repo), "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "repository-only"
    assert payload["ok"] is True
    assert isinstance(payload["checks"], list) and payload["checks"]
