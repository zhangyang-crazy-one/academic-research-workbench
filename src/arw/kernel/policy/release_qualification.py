"""Portable release evidence: installed behavior, without a host/version lock."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads

RECEIPT = "release-qualification.json"
SCHEMA = "arw.release-qualification.v1"
MAX_STREAM = 8 * 1024 * 1024
CHECKS = (
    "core-integrity",
    "bounded-artifact-read",
    "run-init",
    "run-status",
    "journal-replay",
)
PLANS = {
    "stage-validate": [
        "$SOURCE/scripts/stage-plugin",
        "--validate-only",
        "--stage-root",
        "$QUALIFICATION/stage",
    ],
    "installed-core": [
        "$PYTHON",
        "$SOURCE/scripts/probe-installed-core",
        "--stage-root",
        "$QUALIFICATION/stage",
    ],
}


def direct_files(root: Path) -> list[Path]:
    if any(p.is_symlink() for p in (root, *root.parents)) or not root.is_dir():
        raise ValueError("missing or symlink qualification directory")
    files = []
    for p in sorted(root.rglob("*")):
        mode = p.lstat().st_mode
        if stat.S_ISREG(mode):
            files.append(p)
        elif not stat.S_ISDIR(mode):
            raise ValueError("non-regular qualification input")
    return files


def digest(path: Path) -> str:
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError("missing or unsafe qualification file")
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            value.update(block)
    return value.hexdigest()


def read(path: Path) -> dict:
    digest(path)
    value = strict_json_loads(path.read_bytes())
    if not isinstance(value, dict):
        raise TypeError("qualification receipt must be an object")
    return value


def stage_digest(stage: Path) -> str:
    return hashlib.sha256(
        canonical_json_bytes(
            sorted(
                (p.relative_to(stage).as_posix(), digest(p))
                for p in direct_files(stage)
            )
        )
    ).hexdigest()


def verify(
    root: Path, *, source_commit: str, wheel_sha256: str, build_sha256: str
) -> dict:
    """Recheck retained observations; host/tool versions are informational only."""
    files = direct_files(root)
    if (root / "phase-7-verification.json").exists():
        raise ValueError("mixed legacy and portable release profiles")
    receipt = read(root / RECEIPT)
    expected_fields = {
        "schema_version",
        "source_commit",
        "wheel_sha256",
        "build_evidence_sha256",
        "stage_sha256",
        "technical_qualification",
        "commands",
        "observations",
    }
    if (
        set(receipt) != expected_fields
        or receipt["schema_version"] != SCHEMA
        or receipt["source_commit"] != source_commit
        or receipt["wheel_sha256"] != wheel_sha256
        or receipt["build_evidence_sha256"] != build_sha256
        or receipt["technical_qualification"] != "PASS"
        or not isinstance(receipt["observations"], dict)
    ):
        raise ValueError("portable release candidate identity or verdict differs")
    stage = root / "stage"
    if receipt["stage_sha256"] != stage_digest(stage):
        raise ValueError("portable release installed stage changed")
    wheels = list((stage / "share/arw/wheels").glob("*.whl"))
    if (
        len(wheels) != 1
        or digest(wheels[0]) != wheel_sha256
        or digest(stage / "share/arw/evidence/candidate-build.json") != build_sha256
    ):
        raise ValueError("portable installed wheel/build differs from candidate")
    rows = receipt["commands"]
    if not isinstance(rows, list) or len(rows) != len(PLANS):
        raise ValueError("portable release command set differs")
    expected = {RECEIPT, *(p.relative_to(root).as_posix() for p in direct_files(stage))}
    for row, (name, argv) in zip(rows, PLANS.items(), strict=True):
        location = root / "commands" / name
        retained = read(location / "result.json")
        if (
            not isinstance(row, dict)
            or row != retained
            or set(row)
            != {"name", "argv", "returncode", "stdout_sha256", "stderr_sha256"}
            or row["name"] != name
            or row["argv"] != argv
            or type(row["returncode"]) is not int
            or row["returncode"] != 0
        ):
            raise ValueError("portable release command failed or plan differs")
        for stream in ("stdout", "stderr"):
            path = location / f"{stream}.log"
            if (
                path.stat().st_size > MAX_STREAM
                or digest(path) != row[f"{stream}_sha256"]
            ):
                raise ValueError(
                    "portable release command output changed or exceeds bound"
                )
        expected.update(
            f"commands/{name}/{file}"
            for file in ("result.json", "stdout.log", "stderr.log")
        )
    if {p.relative_to(root).as_posix() for p in files} != expected:
        raise ValueError("portable release evidence has unbound extra files")
    probe = read(root / "commands/installed-core/stdout.log")
    if (
        probe.get("schema_version") != "arw.release-core-probe.v1"
        or probe.get("status") != "PASS"
        or probe.get("checks") != list(CHECKS)
    ):
        raise ValueError("installed core behavior probe is incomplete")
    return receipt
