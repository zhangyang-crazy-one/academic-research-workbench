from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True)
class JsonRpcProcessResult:
    completed: subprocess.CompletedProcess[str]
    responses: tuple[dict[str, Any], ...]


def canonical_request(identifier: int, method: str, params: Mapping[str, object]) -> str:
    return json.dumps(
        {"jsonrpc": "2.0", "id": identifier, "method": method, "params": params},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def invoke_jsonrpc_process(
    argv: Sequence[str],
    requests: Iterable[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout: float = 15.0,
) -> JsonRpcProcessResult:
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        env=dict(environment),
        input="\n".join(requests) + "\n",
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout,
    )
    responses = tuple(
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    )
    if not all(isinstance(response, dict) for response in responses):
        raise AssertionError("JSON-RPC responses must be objects")
    return JsonRpcProcessResult(completed=completed, responses=responses)


def snapshot_tree(root: Path) -> tuple[dict[str, object], ...]:
    """Return a path-independent, deterministic snapshot without following symlinks."""

    entries: list[dict[str, object]] = []
    if not root.exists():
        return ()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            entries.append(
                {
                    "path": relative,
                    "kind": "symlink",
                    "target": os.readlink(path),
                }
            )
        elif stat.S_ISDIR(metadata.st_mode):
            entries.append({"path": relative, "kind": "directory"})
        elif stat.S_ISREG(metadata.st_mode):
            body = path.read_bytes()
            entries.append(
                {
                    "path": relative,
                    "kind": "file",
                    "size": len(body),
                    "sha256": hashlib.sha256(body).hexdigest(),
                }
            )
        else:
            entries.append({"path": relative, "kind": "other"})
    return tuple(entries)


@dataclass(frozen=True)
class NamedBarrier:
    """File-backed barrier controlled by the parent test process."""

    directory: Path
    name: str

    @property
    def receipt_path(self) -> Path:
        return self.directory / f"{self.name}.reached.json"

    @property
    def release_path(self) -> Path:
        return self.directory / f"{self.name}.release"

    def await_receipt(self, timeout: float = 5.0) -> dict[str, object]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                payload = json.loads(self.receipt_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                time.sleep(0.01)
                continue
            if not isinstance(payload, dict) or payload.get("barrier") != self.name:
                raise AssertionError(f"invalid barrier receipt: {payload!r}")
            return payload
        raise AssertionError(f"barrier {self.name!r} was not reached before timeout")

    def release(self) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        self.release_path.write_text(f"{self.name}\n", encoding="utf-8")

