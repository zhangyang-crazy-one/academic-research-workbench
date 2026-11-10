"""Command-construction/fail-closed tests; real sudo coverage is in integration."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "fail_drop",
    [0, 2, 3, -1],
    ids=["starts", "probe-fails", "launch-fails", "loopback-fails"],
)
def test_sudo_namespace_and_drop_chain(tmp_path: Path, fail_drop: int) -> None:
    commands = tmp_path / "bin"
    commands.mkdir()
    log = tmp_path / "calls.jsonl"
    shim = """#!/usr/bin/python3
import json, os, pathlib, sys
name = pathlib.Path(sys.argv[0]).name
args = sys.argv[1:]
log = pathlib.Path(os.environ['CALL_LOG'])
with log.open('a') as f:
    f.write(json.dumps([name, *args]) + '\\n')
if name == 'id':
    print('0')
    sys.exit(0)
if name == 'bwrap':
    sys.exit(88)  # sudo must never use this backend
if name == 'ip':
    sys.exit(1 if os.environ['FAIL_DROP'] == '-1' else 0)
if name == 'setpriv':
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    count = sum(call[0] == name for call in calls)
    if count == int(os.environ['FAIL_DROP']):
        print('setpriv: simulated identity drop failure', file=sys.stderr)
        sys.exit(127)
    args = args[args.index('--') + 1:]
elif name == 'unshare':
    args = args[5:]
elif name == 'strace':
    pathlib.Path(args[args.index('-o') + 1]).write_text('')
    args = args[args.index('--') + 1:]
os.execvp(args[0], args)
"""
    for name in ("id", "setpriv", "bwrap", "unshare", "strace", "ip"):
        path = commands / name
        path.write_text(shim)
        path.chmod(0o755)
    marker = tmp_path / "target-started"
    evidence = tmp_path / "evidence"
    result = subprocess.run(
        [
            str(ROOT / "scripts/offline-exec"),
            "--evidence-root",
            str(evidence),
            "/usr/bin/touch",
            str(marker),
        ],
        env={
            **os.environ,
            "PATH": f"{commands}:{os.environ['PATH']}",
            "SUDO_UID": "1000",
            "SUDO_GID": "1000",
            "CALL_LOG": str(log),
            "FAIL_DROP": str(fail_drop),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    calls = [json.loads(line) for line in log.read_text().splitlines()]
    assert not any(call[0] == "bwrap" for call in calls)
    unshares = [call for call in calls if call[0] == "unshare"]
    assert len(unshares) == (1 if fail_drop in (2, -1) else 2)
    for call in unshares:
        assert call[:6] == [
            "unshare",
            "--net",
            "--pid",
            "--fork",
            "--kill-child=KILL",
            "--mount-proc",
        ]
        assert call[6:8] == ["/bin/bash", "-c"]
        assert call[8] == 'set -euo pipefail; "$1" link set dev lo up; shift; exec "$@"'
        assert call[9:11] == ["offline-exec-init", str(commands / "ip")]
        assert call[11:21] == [
            "setpriv",
            "--reuid=1000",
            "--regid=1000",
            "--init-groups",
            "--inh-caps=-all",
            "--bounding-set=-all",
            "--no-new-privs",
            "--pdeathsig",
            "keep",
            "--",
        ]
    assert unshares[0][-1] == "/bin/true"
    assert marker.exists() is (fail_drop == 0)
    ip_calls = [call for call in calls if call[0] == "ip"]
    assert len(ip_calls) == len(unshares)
    assert all(call[1:] == ["link", "set", "dev", "lo", "up"] for call in ip_calls)
    assert calls.index(unshares[0]) < calls.index(ip_calls[0])
    if fail_drop in (2, -1):
        assert result.returncode == 69
        assert "privilege drop failed" in result.stderr
    else:
        # Mock namespaces are deliberately not certified as isolated.
        assert result.returncode == 97
        verdict = json.loads((evidence / "verdict.json").read_text())
        assert verdict["technical_qualification"] == "FAIL"
        assert verdict["command_status"] == (127 if fail_drop == 3 else 0)
