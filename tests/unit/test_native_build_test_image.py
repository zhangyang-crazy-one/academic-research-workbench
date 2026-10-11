"""Real ELF probes keep the compressed TSan profile and failure evidence honest."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts/build-file-base").read_text()
IMAGE_FUNCTION = re.search(
    r"(?m)^record_test_build_image\(\) \{\n.*?^\}", SCRIPT, re.DOTALL
).group()


def _compiler(suite: str) -> list[str]:
    start = SCRIPT.index('TEST_CC="cc"')
    end = SCRIPT.index('[[ "$SANITIZERS"', start)
    result = subprocess.run(
        ["bash", "-e", "-c", SCRIPT[start:end] + '\nprintf "%s" "$TEST_CC"'],
        env={**os.environ, "SUITE_KIND": suite},
        capture_output=True,
        text=True,
        check=True,
    )
    return shlex.split(result.stdout)


def _build(tmp_path: Path, compiler: list[str]) -> Path:
    if shutil.which("cc") is None or shutil.which("readelf") is None:
        pytest.skip("native compiler and independent readelf are required")
    source = tmp_path / "probe.c"
    source.write_text(
        "#include <stdio.h>\n"
        "typedef struct { int count; double values[64]; } probe_state;\n"
        "static double probe(probe_state *p) {\n"
        "  double total = 0;\n"
        "  for (int i = 0; i < p->count; ++i) total += p->values[i];\n"
        "  return total;\n}\n"
        "int main(void) { probe_state p = { .count = 2, .values = {1, 2} };\n"
        '  printf("%f\\n", probe(&p)); return 0; }\n'
    )
    image = tmp_path / "build/c/test-runner"
    image.parent.mkdir(parents=True)
    result = subprocess.run(
        [
            *compiler,
            "-g",
            "-O1",
            "-fsanitize=thread",
            "-fno-omit-frame-pointer",
            "-c",
            str(source),
            "-o",
            str(image),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    sections = subprocess.check_output(
        ["readelf", "--wide", "--section-headers", str(image)], text=True
    )
    symbols = subprocess.check_output(
        ["readelf", "--wide", "--symbols", str(image)], text=True
    )
    (tmp_path / "readelf-sections.txt").write_text(sections)
    (tmp_path / "readelf-symbols.txt").write_text(symbols)
    debug_info = subprocess.check_output(
        ["readelf", "--debug-dump=info", str(image)], text=True
    )
    (tmp_path / "readelf-debug-info.txt").write_text(debug_info)
    assert "probe_state" in debug_info
    assert "__tsan_init" in symbols and "__tsan_func_entry" in symbols
    return image


def _record(
    tmp_path: Path, suite: str, compiler: list[str], status: int = 0
) -> subprocess.CompletedProcess:
    evidence = tmp_path / "evidence"
    evidence.mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", "-e", "-c", IMAGE_FUNCTION + "\nrecord_test_build_image"],
        env={
            **os.environ,
            "BUILD_SOURCE": str(tmp_path),
            "EVIDENCE_ROOT": str(evidence),
            "SUITE_KIND": suite,
            "TEST_CC": shlex.join(compiler),
            "TEST_STATUS": str(status),
        },
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize("suite", ["upstream", "asan-ubsan", "tsan"])
def test_real_compiler_preserves_instrumentation_and_only_tsan_compresses(
    tmp_path: Path, suite: str
) -> None:
    compiler = _compiler(suite)
    image = _build(tmp_path, compiler)
    observed = _record(tmp_path, suite, compiler)
    assert observed.returncode == 0, observed.stderr
    record = json.loads((tmp_path / "evidence/test-build-image.json").read_text())
    assert record["image"]["sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
    assert record["image"]["size_bytes"] == image.stat().st_size
    assert record["test_compiler"] == shlex.join(compiler)
    assert record["debug_compression_matches_profile"] is True
    info = next(
        item for item in record["debug_sections"] if item["name"] == ".debug_info"
    )
    independent = next(
        line
        for line in (tmp_path / "readelf-sections.txt").read_text().splitlines()
        if ".debug_info " in line
    )
    if suite == "tsan":
        assert info["compression"] == "zlib" and info["shf_compressed"] is True
        assert info["uncompressed_size_bytes"] > info["size_bytes"]
        assert independent.split()[-4] == "C"
    else:
        assert info["compression"] is None and info["shf_compressed"] is False
        assert "C" not in independent.split()[3:]


def test_uncompressed_tsan_image_is_rejected_with_original_failed_status_retained(
    tmp_path: Path,
) -> None:
    _build(tmp_path, ["cc"])
    result = _record(tmp_path, "tsan", ["cc", "-gz=zlib"], status=2)
    assert result.returncode != 0
    record = json.loads((tmp_path / "evidence/test-build-image.json").read_text())
    assert record["test_status"] == 2
    assert record["debug_compression_matches_profile"] is False
    assert "technical_qualification" not in record


def test_compile_failure_without_runner_is_retained_without_an_invented_image(
    tmp_path: Path,
) -> None:
    result = _record(tmp_path, "tsan", ["cc", "-gz=zlib"], status=2)
    assert result.returncode == 0, result.stderr
    record = json.loads((tmp_path / "evidence/test-build-image.json").read_text())
    assert record["image"] is None and record["test_status"] == 2
    assert record["debug_compression_matches_profile"] is False
    assert "technical_qualification" not in record


@pytest.mark.parametrize(
    ("status", "diagnostic", "message"),
    [
        (2, "", "upstream suite failed"),
        (
            0,
            "WARNING: ThreadSanitizer: test diagnostic",
            "sanitizer diagnostics were emitted",
        ),
        (
            0,
            "FATAL: ThreadSanitizer: test diagnostic",
            "sanitizer diagnostics were emitted",
        ),
        (
            0,
            "SUMMARY: ThreadSanitizer: test diagnostic",
            "sanitizer diagnostics were emitted",
        ),
    ],
)
def test_original_fatal_guards_reject_failure_after_real_image_capture(
    tmp_path: Path,
    status: int,
    diagnostic: str,
    message: str,
) -> None:
    compiler = _compiler("tsan")
    _build(tmp_path, compiler)
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    start = SCRIPT.index('  set +e\n  make -C "$BUILD_SOURCE"')
    end = SCRIPT.index('  python3 - "$EVIDENCE_ROOT" "$SUITE_KIND"', start)
    shell = (
        IMAGE_FUNCTION + '\nfail() { printf "%s\\n" "$1" >&2; exit "$2"; }\n'
        'make() { printf "%s\\n" "$ARW_TEST_DIAGNOSTIC"; return "$ARW_TEST_STATUS"; }\n'
        + SCRIPT[start:end]
    )
    result = subprocess.run(
        ["bash", "-e", "-c", shell],
        env={
            **os.environ,
            "BUILD_SOURCE": str(tmp_path),
            "EVIDENCE_ROOT": str(evidence),
            "SUITE_KIND": "tsan",
            "TEST_CC": shlex.join(compiler),
            "SANITIZE_FLAGS": "-fsanitize=thread",
            "ARW_TEST_STATUS": str(status),
            "ARW_TEST_DIAGNOSTIC": diagnostic,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 70 and message in result.stderr
    assert (evidence / "test-status.txt").read_text().strip() == str(status)
    record = json.loads((evidence / "test-build-image.json").read_text())
    assert record["test_status"] == status and record["image"] is not None
    assert not (evidence / "sanitizer-verdict.json").exists()
