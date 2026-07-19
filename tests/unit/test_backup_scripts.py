from __future__ import annotations

import subprocess
from pathlib import Path

_ROOT = Path(__file__).parents[2]
_RECEIVER = _ROOT / "infra/backup/catering-backup-receive.sh"
_SENDER = _ROOT / "infra/backup/catering-offsite-backup.sh"


def test_backup_scripts_have_valid_posix_shell_syntax() -> None:
    for script in (_RECEIVER, _SENDER):
        subprocess.run(["sh", "-n", script], check=True)


def test_receiver_uses_a_forced_command_allowlist() -> None:
    source = _RECEIVER.read_text()
    assert "SSH_ORIGINAL_COMMAND" in source
    assert '"put "*' in source
    assert '"sha256 "*' in source
    assert "prune)" in source
    assert "backup command denied" in source
    assert "core-[0-9][0-9][0-9][0-9]-" in source
    assert "courier-[0-9][0-9][0-9][0-9]" in source
    assert "fingerfood-[0-9][0-9][0-9][0-9]" in source
    assert ".gpg.sha256" in source
    assert "prune_fingerfood_family" in source
    assert "bs=1048576 count=256" in source


def test_sender_encrypts_before_transport_and_verifies_checksum() -> None:
    source = _SENDER.read_text()
    encryption = source.index("--encrypt")
    upload = source.index('"put $name"')
    assert encryption < upload
    assert "local_sum=" in source
    assert "remote_sum=" in source
    assert 'test "$local_sum" = "$remote_sum"' in source
