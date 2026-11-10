"""Real namespace/drop regression; explicitly required by the Linux CI job.

Run with ARW_TEST_SUDO=1 python -m pytest -q <this file> on a sudo-capable host.
No fake namespace or privilege tools are used in this test.
"""

from __future__ import annotations

import json
import os
import subprocess
import signal
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(
    os.environ.get("ARW_TEST_SUDO") != "1",
    reason="requires explicit sudo-capable CI host (ARW_TEST_SUDO=1)",
)

TARGET = r"""
import json, os, pathlib, socket, subprocess, sys
root = pathlib.Path(sys.argv[1])
status = pathlib.Path('/proc/self/status').read_text().splitlines()
record = {
    'uid': os.getuid(), 'euid': os.geteuid(),
    'gid': os.getgid(), 'egid': os.getegid(),
    'net': os.readlink('/proc/self/ns/net'),
    'pid': os.readlink('/proc/self/ns/pid'),
    'no_new_privs': next(line.split(':')[1].strip() for line in status if line.startswith('NoNewPrivs:')),
    'root_owner': pathlib.Path('/').stat().st_uid,
    'caps': {line.split(':')[0]: line.split(':')[1].strip()
             for line in status if line.startswith('Cap')},
}
(root / 'identity.json').write_text(json.dumps(record))
(root / 'target-started').write_text('started\n')
# Exercise actual localhost traffic, not merely socket creation. This fails
# when a new network namespace has loopback down, even if startup succeeded.
with socket.socket() as server, socket.socket() as client:
    server.settimeout(3)
    client.settimeout(3)
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    client.connect(server.getsockname())
    with server.accept()[0] as connection:
        connection.settimeout(3)
        client.sendall(b'ping')
        assert connection.recv(4) == b'ping'
        connection.sendall(b'pong')
        assert client.recv(4) == b'pong'
(root / 'loopback-round-trip').write_text('passed\n')
# Leave a detached descendant behind. PID namespace teardown must kill it,
# allowing strace -f to finish instead of hanging until the timeout.
subprocess.Popen(['sleep', '90'], start_new_session=True)
if sys.argv[2] == 'network':
    socket.socket(socket.AF_INET, socket.SOCK_STREAM)
if sys.argv[2] == 'failure':
    sys.exit(23)
"""


@pytest.mark.parametrize("sudo", [False, True], ids=["normal", "sudo"])
@pytest.mark.parametrize("mode", ["success", "failure", "network"])
def test_actual_target_identity_and_audit(
    tmp_path: Path, sudo: bool, mode: str
) -> None:
    assert os.getuid() != 0, "run the regression as the ordinary runner user"
    evidence = tmp_path / "evidence"
    host_net = os.readlink("/proc/self/ns/net")
    host_pid = os.readlink("/proc/self/ns/pid")
    command = [
        str(ROOT / "scripts/offline-exec"),
        "--evidence-root",
        str(evidence),
        "/usr/bin/python3",
        "-c",
        TARGET,
        str(evidence),
        mode,
    ]
    if sudo:
        command = ["sudo", "-n", *command]
    result = subprocess.run(command, capture_output=True, text=True, timeout=30)
    error_log = evidence / "stderr.log"
    details = result.stderr + (error_log.read_text() if error_log.exists() else "")
    assert result.returncode == (0 if mode == "success" else 97), details
    assert (evidence / "target-started").is_file(), details
    assert (evidence / "target-started").read_text() == "started\n"
    assert (evidence / "loopback-round-trip").read_text() == "passed\n"
    identity = json.loads((evidence / "identity.json").read_text())
    verdict = json.loads((evidence / "verdict.json").read_text())
    assert identity["net"] != host_net
    assert identity["pid"] != host_pid
    assert verdict["child_network_namespace"] == identity["net"]
    assert verdict["network_namespace_denied"] is True
    assert verdict["strace_network_audit"] is True
    assert verdict["command_status"] == (23 if mode == "failure" else 0)
    assert verdict["technical_qualification"] == (
        "PASS" if mode == "success" else "FAIL"
    )
    assert bool(verdict["network_syscall_attempts"]) is (mode == "network")
    if sudo:
        assert verdict["network_denial_mechanism"] == "unshare-root-net"
        assert identity["uid"] == identity["euid"] == os.getuid()
        assert identity["gid"] == identity["egid"] == os.getgid()
        assert identity["root_owner"] == 0
        assert identity["no_new_privs"] == "1"
        assert all(int(value, 16) == 0 for value in identity["caps"].values())


def test_sudo_supervisor_cancellation_kills_target(tmp_path: Path) -> None:
    """UID changes must not clear the namespace init's parent-death signal."""
    assert os.getuid() != 0
    evidence = tmp_path / "cancel-evidence"
    target = """
import ctypes, json, os, pathlib, signal, subprocess, sys, time
root = pathlib.Path(sys.argv[1])
sig = ctypes.c_int()
assert ctypes.CDLL(None, use_errno=True).prctl(2, ctypes.byref(sig), 0, 0, 0) == 0
assert sig.value == signal.SIGKILL, sig.value
subprocess.Popen(['sleep', '90'], start_new_session=True)
(root / 'target-started').write_text(json.dumps({'uid': os.getuid(), 'pdeathsig': sig.value}))
time.sleep(90)
"""
    process = subprocess.Popen(
        [
            "sudo",
            "-n",
            str(ROOT / "scripts/offline-exec"),
            "--evidence-root",
            str(evidence),
            "/usr/bin/python3",
            "-c",
            target,
            str(evidence),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    supervisor = None
    killed = False
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            for proc in Path("/proc").glob("[0-9]*"):
                try:
                    argv = (proc / "cmdline").read_bytes().split(b"\0")
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    continue
                if (
                    argv
                    and Path(os.fsdecode(argv[0])).name == "unshare"
                    and os.fsencode(evidence) in argv
                ):
                    supervisor = int(proc.name)
            if supervisor and (evidence / "target-started").exists():
                break
            assert process.poll() is None, "offline target exited before cancellation"
            time.sleep(0.05)
        assert supervisor is not None, "namespace supervisor did not start"
        assert (evidence / "target-started").exists(), (
            "target did not reach post-drop check"
        )
        started = json.loads((evidence / "target-started").read_text())
        assert started == {"uid": os.getuid(), "pdeathsig": signal.SIGKILL}
        subprocess.run(
            ["sudo", "-n", "/bin/kill", "-KILL", str(supervisor)], check=True
        )
        killed = True
        # strace -f waits for every descendant, including detached sleep. If the
        # signal was lost at setpriv, this blocks until timeout rather than pass.
        process.communicate(timeout=10)
        assert process.returncode == 97
        verdict = json.loads((evidence / "verdict.json").read_text())
        assert verdict["command_status"] != 0
        assert verdict["technical_qualification"] == "FAIL"
    finally:
        if supervisor and not killed:
            subprocess.run(
                ["sudo", "-n", "/bin/kill", "-KILL", str(supervisor)], check=False
            )
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
