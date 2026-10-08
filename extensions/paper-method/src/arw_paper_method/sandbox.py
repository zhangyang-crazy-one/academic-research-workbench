"""Bounded, credential-free execution of the paper method in a network namespace."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .method import MAX_INPUT_BYTES, MAX_OUTPUT_BYTES

METHOD = Path(__file__).with_name("method.py")
MAX_TIMEOUT_MS = 2000


class SandboxError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _command(program: list[str]) -> list[str]:
    bwrap = Path("/usr/bin/bwrap")
    python = Path("/usr/bin/python3")
    if not bwrap.is_file() or not python.is_file() or not METHOD.is_file():
        raise SandboxError("isolation_prerequisite_missing")
    return [
        bwrap,
        "--die-with-parent",
        "--unshare-net",
        "--unshare-pid",
        "--ro-bind",
        "/usr",
        "/usr",
        "--symlink",
        "usr/lib",
        "/lib",
        "--symlink",
        "usr/lib64",
        "/lib64",
        "--ro-bind",
        str(METHOD),
        "/app/method.py",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",
        "--chdir",
        "/app",
        "--clearenv",
        "--setenv",
        "PATH",
        "/usr/bin",
        "--setenv",
        "HOME",
        "/nonexistent",
        "--setenv",
        "PYTHONDONTWRITEBYTECODE",
        "1",
        "--remount-ro",
        "/",
        "--",
        *program,
    ]


def _run(command: list[str], raw: bytes, timeout_ms: int) -> bytes:
    try:
        completed = subprocess.run(
            command,
            input=raw,
            capture_output=True,
            check=False,
            timeout=timeout_ms / 1000,
            env={"PATH": "/usr/bin", "HOME": "/nonexistent"},
            cwd="/",
            close_fds=True,
        )
    except subprocess.TimeoutExpired as error:
        raise SandboxError("execution_timeout") from error
    except OSError as error:
        raise SandboxError("isolation_prerequisite_missing") from error
    if completed.returncode != 0:
        raise SandboxError("isolation_execution_failed")
    if len(completed.stdout) > MAX_OUTPUT_BYTES:
        raise SandboxError("output_budget_exceeded")
    return completed.stdout


def probe_namespace() -> dict[str, str]:
    host = os.readlink("/proc/self/ns/net")
    child = (
        _run(_command(["/usr/bin/readlink", "/proc/self/ns/net"]), b"", 1000)
        .decode()
        .strip()
    )
    if not child or child == host:
        raise SandboxError("network_namespace_not_denied")
    return {
        "host_network_namespace": host,
        "child_network_namespace": child,
        "mechanism": "bwrap-unshare-net-ro-usr",
    }


def run_worker(raw: bytes, *, timeout_ms: int = MAX_TIMEOUT_MS) -> bytes:
    if len(raw) > MAX_INPUT_BYTES:
        raise SandboxError("input_budget_exceeded")
    if type(timeout_ms) is not int or not 1 <= timeout_ms <= MAX_TIMEOUT_MS:
        raise SandboxError("timeout_range")
    return _run(
        _command(["/usr/bin/python3", "-I", "-S", "-B", "/app/method.py"]),
        raw,
        timeout_ms,
    )


def probe_timeout() -> None:
    try:
        _run(
            _command(
                ["/usr/bin/python3", "-I", "-S", "-c", "import time; time.sleep(2)"]
            ),
            b"",
            10,
        )
    except SandboxError as error:
        if error.code == "execution_timeout":
            return
        raise
    raise SandboxError("timeout_probe_failed")


def probe_worker_boundary() -> bool:
    """Verify source/root are read-only, only tmpfs is writable, no home/env leaks."""
    program = """
import errno, json, os
denied = []
for path in ('/app/method.py', '/app/output', '/output'):
    try:
        with open(path, 'ab') as stream:
            stream.write(b'probe')
    except OSError as error:
        denied.append(error.errno == errno.EROFS)
    else:
        denied.append(False)
with open('/tmp/output', 'wb') as stream:
    stream.write(b'probe')
os.unlink('/tmp/output')
allowed_environment = {'PATH', 'HOME', 'PYTHONDONTWRITEBYTECODE', 'PWD', 'LC_CTYPE'}
print(json.dumps(all(denied) and not os.path.exists('/home')
    and os.environ.get('HOME') == '/nonexistent'
    and set(os.environ) <= allowed_environment))
"""
    result = _run(_command(["/usr/bin/python3", "-I", "-S", "-c", program]), b"", 1000)
    if result.strip() != b"true":
        raise SandboxError("worker_boundary_violation")
    return True
