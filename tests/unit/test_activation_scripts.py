from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_STAGING_CORE_INTAKE = _ROOT / "infra/deploy/activate-staging-core-intake.sh"


def test_staging_core_intake_activation_has_valid_posix_shell_syntax() -> None:
    subprocess.run(["sh", "-n", _STAGING_CORE_INTAKE], check=True)


def test_staging_core_intake_activation_waits_for_http_readiness() -> None:
    source = _STAGING_CORE_INTAKE.read_text()

    assert 'while [ "$attempt" -le 15 ]' in source
    assert "--connect-timeout 1 --max-time 2" in source
    assert 'if [ "$status" = 401 ]' in source
    assert "website-intake readiness check failed" in source
