"""Bounded process boundary and public structured binary inspection."""

import base64
import json
import os
import subprocess
import sys

from arw.kernel.core.canonical import sha256_hex
from arw.ports.artifacts import BinaryArtifactInspection, DetectorResult

FAMILIES = (
    "unicode",
    "exif",
    "xmp",
    "pdf_properties",
    "docx_properties",
    "c2pa",
    "statistical",
)


def invoke(content, selection=(), strip=False):
    if len(content) > 1024 * 1024:
        return {"status": "unsupported", "reason": "input_too_large"}
    if os.name != "posix":
        return {
            "status": "unsupported",
            "reason": "bounded_parser_platform_unsupported",
        }
    payload = json.dumps(
        {
            "content": base64.b64encode(content).decode(),
            "selection": list(selection),
            "strip": strip,
        }
    ).encode()
    try:
        result = subprocess.run(
            [sys.executable, "-m", "arw_artifact_integrity.binary_worker"],
            input=payload,
            capture_output=True,
            timeout=8,
            check=False,
        )
        if result.returncode or len(result.stdout) > 2 * 1024 * 1024:
            return {"status": "unknown", "reason": "parser_resource_limit"}
        return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return {"status": "unknown", "reason": "parser_timeout_or_invalid_output"}


def inspect_binary(content, detectors=None):
    result = invoke(content)
    requested = set(FAMILIES) | set(detectors or ())
    outcomes = {
        name: DetectorResult(
            status="unsupported", reason_code="detector_not_applicable_or_implemented"
        )
        for name in requested
    }
    if result["status"] == "ok":
        outcomes.update(
            {
                name: DetectorResult(**value)
                for name, value in result["detectors"].items()
            }
        )
    else:
        for name in ("exif", "xmp", "pdf_properties", "docx_properties", "c2pa"):
            outcomes[name] = DetectorResult(
                status=result["status"], reason_code=result["reason"]
            )
    counts = result.get("counts", {})
    return BinaryArtifactInspection(
        status="inspected" if result["status"] == "ok" else "unsupported",
        reason_code=result.get("reason", "format_presence_inspected"),
        content_sha256=sha256_hex(content),
        input_bytes=len(content),
        detectors=outcomes,
        format=result.get("format"),
        dependency_versions=result.get("dependency_versions", {}),
        category_counts=counts,
        total_findings=sum(counts.values()),
        verification=result.get("verification", {}),
    )
