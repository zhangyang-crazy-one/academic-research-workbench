"""Source-capsule and actual sandbox-test gate for the optional MCP tool."""

from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

from .method import canonical
from .provenance import verify_proof
from .sandbox import SandboxError, probe_namespace, probe_timeout, run_worker

ROOT = Path(__file__).resolve().parents[4]
EXT = ROOT / "extensions" / "paper-method"
CAPSULE = EXT / "source-capsule.json"
FIXTURE = EXT / "fixtures" / "example-2.json"
SOURCE_PATHS = (
    "src/arw/__init__.py",
    "src/arw/mcp_stdio.py",
    "src/arw/kernel/__init__.py",
    "src/arw/kernel/core/__init__.py",
    "src/arw/kernel/core/canonical.py",
    "extensions/paper-method/src/arw_paper_method/__init__.py",
    "extensions/paper-method/src/arw_paper_method/method.py",
    "extensions/paper-method/src/arw_paper_method/sandbox.py",
    "extensions/paper-method/src/arw_paper_method/qualification.py",
    "extensions/paper-method/src/arw_paper_method/server.py",
    "extensions/paper-method/src/arw_paper_method/provenance.py",
    "extensions/paper-method/src/arw_paper_method/installation.py",
    "extensions/paper-method/schemas/input.schema.json",
    "extensions/paper-method/schemas/output.schema.json",
    "extensions/paper-method/fixtures/example-2.json",
)
PAPER_DOI = "10.1080/00029890.1962.11989827"
PAPER_PDF_SHA256 = "3971ec3e3b048b6ace92248fcc8fa8f021808ca76cbc09d439275b8c0a07bb41"


class QualificationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json(path: Path):
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualificationError("metadata_unavailable") from error
    if not isinstance(value, dict):
        raise QualificationError("metadata_invalid")
    return raw, value


def build_capsule(commit: str) -> dict:
    """Build after the source commit; this does not claim qualification."""
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise QualificationError("invalid_source_commit")
    return {
        "schema_version": "arw.paper-method-capsule.v1",
        "paper": {
            "title": "College Admissions and the Stability of Marriage",
            "authors": ["D. Gale", "L. S. Shapley"],
            "year": 1962,
            "doi": PAPER_DOI,
            "source_url": "https://iqua.ece.toronto.edu/baochun/ece1771f/papers/Gale-Shapley-1962.pdf",
            "pdf_sha256": PAPER_PDF_SHA256,
            "reference_location": "printed page 12, Example 2",
            "method_location": "Theorem 1 proof, printed pages 12-13",
        },
        "scope": "strict-complete-equal-sized-no-ties-or-quotas",
        "source_commit": commit,
        "source_files": {
            path: sha((ROOT / path).read_bytes()) for path in SOURCE_PATHS
        },
        "input_schema": "extensions/paper-method/schemas/input.schema.json",
        "output_schema": "extensions/paper-method/schemas/output.schema.json",
        "dependency_inventory": [],
        "execution_contract": {
            "python_floor": "3.13",
            "isolation": "bwrap-unshare-net-ro-usr",
            "filesystem": "read-only standard library and method source; ephemeral tmpfs",
            "input": "bounded stdin",
            "output": "bounded stdout",
            "credentials": "no home mount; clean environment",
        },
        "qualification_cases": [
            "network_namespace",
            "author_example_2",
            "deterministic_repeat",
            "invalid_type",
            "invalid_ranking",
            "participant_range",
            "timeout",
        ],
    }


def validate_capsule(path: Path = CAPSULE) -> tuple[bytes, dict]:
    raw, capsule = _json(path)
    if canonical(capsule) != raw:
        raise QualificationError("capsule_noncanonical")
    if capsule.get("schema_version") != "arw.paper-method-capsule.v1":
        raise QualificationError("capsule_version_mismatch")
    commit = capsule.get("source_commit")
    if not isinstance(commit, str):
        raise QualificationError("source_commit_missing")
    try:
        expected = build_capsule(commit)
    except (OSError, QualificationError) as error:
        raise QualificationError("source_file_unavailable") from error
    if capsule != expected:
        raise QualificationError("capsule_metadata_or_source_drift")
    # Installed adapters carry Git commit/tree witnesses, not a Git checkout.
    # Hashing each blob through the authenticated trees verifies the same pin.
    if not (ROOT / ".git").exists():
        try:
            _, proof = _json(EXT / "source-proof.json")
            verify_proof(ROOT, commit, SOURCE_PATHS, proof)
        except (KeyError, TypeError, ValueError, OSError) as error:
            raise QualificationError("source_commit_unverifiable") from error
        return raw, capsule
    for relative in SOURCE_PATHS:
        try:
            historical = subprocess.run(
                ["git", "-C", str(ROOT), "show", f"{commit}:{relative}"],
                capture_output=True,
                check=True,
                timeout=2,
            ).stdout
        except (OSError, subprocess.SubprocessError) as error:
            raise QualificationError("source_commit_unverifiable") from error
        if sha(historical) != capsule["source_files"][relative]:
            raise QualificationError("source_commit_mismatch")
    return raw, capsule


def environment() -> dict:
    bwrap = Path("/usr/bin/bwrap")
    python = Path("/usr/bin/python3")
    if not bwrap.is_file() or not python.is_file() or sys.version_info < (3, 13):
        raise QualificationError("isolation_prerequisite_missing")
    return {
        "python_version": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "worker_python_sha256": sha(python.resolve().read_bytes()),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "bwrap_path": str(Path(bwrap).resolve()),
        "bwrap_sha256": sha(Path(bwrap).read_bytes()),
    }


def run_cases(*, inject_failure: bool = False) -> list[dict]:
    fixture = json.loads(FIXTURE.read_bytes())
    raw = canonical(fixture["input"])
    cases = []

    def record(name, action):
        try:
            result = action()
            cases.append(
                {
                    "name": name,
                    "status": "PASS",
                    "output_sha256": sha(canonical(result)),
                }
            )
        except (AssertionError, OSError, ValueError, SandboxError) as error:
            cases.append(
                {
                    "name": name,
                    "status": "FAIL",
                    "reason_code": getattr(error, "code", "assertion_failed"),
                }
            )

    def worker(value):
        return json.loads(run_worker(canonical(value)))

    def golden():
        result = worker(fixture["input"])
        assert result["status"] == "executed"
        assert result["result"]["matching"] == fixture["expected_matching"]
        assert result["result"]["stable_verified"] is True
        return result

    record("network_namespace", lambda: bool(probe_namespace()))
    record("author_example_2", golden)
    record(
        "deterministic_repeat",
        lambda: (
            (
                run_worker(raw) == run_worker(raw) == run_worker(raw)
                and worker(fixture["input"])["result"]["matching"]
                == fixture["expected_matching"]
            )
            or (_ for _ in ()).throw(AssertionError())
        ),
    )
    record(
        "invalid_type",
        lambda: (
            worker({"proposers": [], "receivers": {}})["reason_code"] == "invalid_type"
            or (_ for _ in ()).throw(AssertionError())
        ),
    )
    bad = json.loads(raw)
    bad["proposers"]["alpha"][1] = "A"
    record(
        "invalid_ranking",
        lambda: (
            worker(bad)["reason_code"] == "invalid_ranking"
            or (_ for _ in ()).throw(AssertionError())
        ),
    )
    oversized = {f"p{i}": [] for i in range(65)}
    reverse = {f"r{i}": [] for i in range(65)}
    record(
        "participant_range",
        lambda: (
            worker({"proposers": oversized, "receivers": reverse})["reason_code"]
            == "participant_range"
            or (_ for _ in ()).throw(AssertionError())
        ),
    )
    record("timeout", lambda: probe_timeout() or True)
    if inject_failure:
        cases.append(
            {
                "name": "injected_failure",
                "status": "FAIL",
                "reason_code": "injected_test_failure",
            }
        )
    return cases


def qualify(
    path: Path, *, capsule_path: Path = CAPSULE, inject_failure: bool = False
) -> dict:
    capsule_raw, capsule = validate_capsule(capsule_path)
    env = environment()
    cases = run_cases(inject_failure=inject_failure)
    body = {
        "schema_version": "arw.paper-method-qualification.v1",
        "source_capsule_sha256": sha(capsule_raw),
        "source_commit": capsule["source_commit"],
        "environment": env,
        "cases": cases,
        "qualification": "PASS"
        if all(case["status"] == "PASS" for case in cases)
        else "FAIL",
    }
    receipt = {**body, "receipt_sha256": sha(canonical(body))}
    with path.open("xb") as stream:
        stream.write(canonical(receipt))
    return receipt


def verify(path: Path, *, capsule_path: Path = CAPSULE) -> dict:
    capsule_raw, capsule = validate_capsule(capsule_path)
    raw, receipt = _json(path)
    if raw != canonical(receipt):
        raise QualificationError("receipt_noncanonical")
    body = dict(receipt)
    claimed = body.pop("receipt_sha256", None)
    if claimed != sha(canonical(body)):
        raise QualificationError("receipt_tampered")
    if receipt.get("qualification") != "PASS":
        raise QualificationError("qualification_not_passed")
    if (
        receipt.get("source_capsule_sha256") != sha(capsule_raw)
        or receipt.get("source_commit") != capsule["source_commit"]
    ):
        raise QualificationError("receipt_source_mismatch")
    if receipt.get("environment") != environment():
        raise QualificationError("environment_drift")
    actual = run_cases()
    if receipt.get("cases") != actual or any(
        case["status"] != "PASS" for case in actual
    ):
        raise QualificationError("qualification_replay_failed")
    return receipt
