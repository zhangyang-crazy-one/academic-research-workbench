"""Retained Phase 7 command streams and pinned prior evidence are mandatory."""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/phase7-release-evidence"


def module() -> dict:
    return runpy.run_path(str(SCRIPT))


def test_missing_evidence_and_handmade_pass_are_rejected(tmp_path: Path) -> None:
    code = module()
    value = {"technical_qualification": "PASS", "evidence_bound": True, "git_head": "a" * 40}
    (tmp_path / "phase-7-verification.json").write_text(json.dumps(value))
    with pytest.raises(ValueError):
        code["verify_qualification"](tmp_path, ROOT, "a" * 40)


def test_prior_receipts_are_revalidated_with_original_pins(tmp_path: Path) -> None:
    code = module()
    prior = tmp_path / "prior"
    for relative in code["PRIOR_TREES"]:
        (prior / relative).mkdir(parents=True)
    verdict = prior / "build/evidence/phase-05/verdict.json"
    verdict.write_bytes(code["canonical"]({"technical_qualification": "PASS"}))
    for name in ("summary.json", "stage-tree.json"):
        verdict.with_name(name).write_bytes(code["canonical"]({}))
    for relative in code["PRIOR_SCHEMAS"]:
        target = prior / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    with pytest.raises(RuntimeError, match="qualified corpus"):
        code["validate_prior"](prior, ROOT)


@pytest.fixture
def commands(tmp_path: Path) -> tuple[dict, Path, dict]:
    code = module()
    verifier = code["load_verifier"](ROOT)
    original = Path("/original-machine/project")
    verifier["PYTHON"] = original / ".venv/bin/python"
    stage = {"stage_relative_path": "build/stage/qualified",
             "lock_relative_path": "build/evidence/current/integration-lock.json",
             "canary_relative_path": "build/evidence/current/canary.json"}
    records = []
    for name in verifier["REQUIRED_COMMAND_NAMES"]:
        argv = verifier["_expected_command_argv"](name)
        if name == "stage-validate":
            argv[2] = str(original / stage["stage_relative_path"])
            argv[5] = str(original / stage["lock_relative_path"])
        directory = tmp_path / "commands" / name
        directory.mkdir(parents=True)
        stdout, stderr = b"retained command output\n", b""
        (directory / "stdout.log").write_bytes(stdout)
        (directory / "stderr.log").write_bytes(stderr)
        row = {"name": name, "argv": argv, "cwd": "<project>", "returncode": 0,
            "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
            "stdout_truncated": False, "stderr_truncated": False}
        (directory / "result.json").write_bytes(code["canonical"](row))
        records.append(row)
    return code, tmp_path, {"commands": records, "stage": stage}


def test_command_receipts_are_portable_without_original_python(commands: tuple) -> None:
    code, evidence, aggregate = commands
    rows, prefix = code["validate_commands"](evidence, aggregate, code["load_verifier"](ROOT))
    assert len(rows) == 4
    assert prefix == Path("/original-machine/project")


@pytest.mark.parametrize("mutation", ["missing-log", "changed-log", "missing-command", "forged-result",
    "unknown-field", "wrong-prefix", "wrong-stage", "wrong-argv", "bool-returncode", "changed-aggregate"])
def test_changed_or_forged_command_receipts_fail(commands: tuple, mutation: str) -> None:
    code, evidence, aggregate = commands
    directory = evidence / "commands/phase7-focused"
    row = copy.deepcopy(aggregate["commands"][0])
    if mutation == "missing-log":
        (directory / "stdout.log").unlink()
    elif mutation == "changed-log":
        (directory / "stdout.log").write_bytes(b"different output")
    elif mutation == "missing-command":
        (directory / "result.json").unlink()
    elif mutation == "forged-result":
        row["returncode"] = 1
    elif mutation == "unknown-field":
        row["PASS"] = True
    elif mutation == "wrong-prefix":
        aggregate["commands"][2]["argv"][0] = "/another/.venv/bin/python"
        other = evidence / "commands/phase7-nonhost/result.json"
        other.write_bytes(code["canonical"](aggregate["commands"][2]))
    elif mutation == "wrong-stage":
        aggregate["stage"]["stage_relative_path"] = "build/stage/different"
    elif mutation == "wrong-argv":
        row["argv"].append("--ignore=tests/integration")
    elif mutation == "bool-returncode":
        row["returncode"] = False
    elif mutation == "changed-aggregate":
        aggregate["commands"][0]["stdout_sha256"] = "0" * 64
    if mutation in {"forged-result", "unknown-field", "wrong-argv", "bool-returncode"}:
        aggregate["commands"][0] = row
        (directory / "result.json").write_bytes(code["canonical"](row))
    with pytest.raises(ValueError):
        code["validate_commands"](evidence, aggregate, code["load_verifier"](ROOT))


def test_export_refuses_symlinked_receipts(tmp_path: Path) -> None:
    code = module()
    (tmp_path / "receipt.json").symlink_to(ROOT / "supply-chain/license-verdict.json")
    with pytest.raises(ValueError, match="symlink"):
        code["direct_files"](tmp_path)


@pytest.mark.parametrize("mutation", ["none", "tree", "worktree", "dirty-source", "wrong-commit"])
def test_current_source_identity_is_checked_independently(tmp_path: Path, mutation: str) -> None:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    (source / "material.txt").write_text("reviewed source\n")
    subprocess.run(["git", "add", "material.txt"], cwd=source, check=True)
    subprocess.run(["git", "-c", "user.name=Evidence Test", "-c", "user.email=evidence@example.invalid",
                    "commit", "--quiet", "-m", "fixture"], cwd=source, check=True)
    code = module()
    verifier = code["load_verifier"](source)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=source, text=True).strip()
    aggregate = {"git_head": head, "git_tree": tree, "git_worktree_sha256": verifier["worktree_digest"]()}
    if mutation == "tree":
        aggregate["git_tree"] = "0" * 40
    elif mutation == "worktree":
        aggregate["git_worktree_sha256"] = "0" * 64
    elif mutation == "dirty-source":
        (source / "material.txt").write_text("changed source\n")
    elif mutation == "wrong-commit":
        head = "0" * 40
    if mutation == "none":
        # Tool-owned transfer files remain under build/, matching the producer.
        (source / "build").mkdir()
        (source / "build/qualified.tar.gz").write_bytes(b"ignored transfer")
        code["validate_source"](verifier, aggregate, source, head)
    else:
        with pytest.raises(ValueError, match="source commit, tree or clean worktree"):
            code["validate_source"](verifier, aggregate, source, head)


def test_altered_export_schema_fails_before_prior_can_claim_pass(tmp_path: Path) -> None:
    code = module()
    prior = tmp_path / "prior"
    for relative in code["PRIOR_TREES"]:
        (prior / relative).mkdir(parents=True)
    for relative in code["PRIOR_SCHEMAS"]:
        target = prior / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    target.write_text('{}')
    with pytest.raises(ValueError, match="schema differs"):
        code["validate_prior"](prior, ROOT)


def test_verified_evidence_base_normalizes_relative_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """#99: the aggregate verifier base is absolute even for relative CLI roots."""
    code = module()
    evidence = tmp_path / "qualification" / "phase7-evidence"
    evidence.mkdir(parents=True)
    (evidence / "receipt.json").write_text("{}")
    monkeypatch.chdir(tmp_path)
    base = code["verified_evidence_base"](Path("qualification/phase7-evidence"))
    assert base == evidence.resolve()
    assert base.is_absolute()


def _configure_retained_aggregate(verifier: dict, aggregate: dict, original_root: Path,
                                  evidence_base: Path) -> None:
    """Mirror verify_retained's dynamic-validator configuration for the aggregate."""
    stage = aggregate["stage"]
    stage_summary = verifier["ValidatedStageSummary"](
        stage_sha256="0" * 64, integration_lock_sha256="1" * 64, host_canary_sha256="2" * 64,
        stage_relative_path=stage["stage_relative_path"], lock_relative_path=stage["lock_relative_path"],
        canary_relative_path=stage["canary_relative_path"], _token=verifier["_VALIDATION_TOKEN"])
    receipt_summary = verifier["ValidatedReceiptSummary"](
        {"technical_qualification": "PASS"}, {"technical_qualification": "PASS"},
        _token=verifier["_VALIDATION_TOKEN"])
    verifier["validate_receipts"] = lambda: receipt_summary
    verifier["validate_stage_and_inputs"] = lambda *args: stage_summary
    verifier["EVIDENCE_BASE"] = evidence_base

    def expected_argv(name, argv, observed_stage):
        expected = verifier["_expected_command_argv"](name)
        if name == "stage-validate":
            expected[2] = str(original_root / stage["stage_relative_path"])
            expected[5] = str(original_root / stage["lock_relative_path"])
        return argv == expected
    verifier["_command_argv_matches"] = expected_argv


def _rebuild_aggregate(verifier: dict, rows: list) -> dict:
    return verifier["aggregate_verdict"](
        receipt_summary=verifier["validate_receipts"](),
        stage_summary=verifier["validate_stage_and_inputs"](),
        test_commands=rows,
        license_summary={"technical_qualification": "PASS", "release_qualification": "BLOCKED"},
        git_head="a" * 40, git_tree="b" * 40, git_worktree="c" * 64)


def test_relative_evidence_root_keeps_aggregate_binding(commands: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """#99: a relative qualification root must not unbind valid command receipts."""
    code, evidence, aggregate = commands
    monkeypatch.chdir(evidence.parent)
    relative = Path(evidence.name)
    verifier = code["load_verifier"](ROOT)
    rows, original_root = code["validate_commands"](relative, aggregate, verifier)
    _configure_retained_aggregate(verifier, aggregate, original_root,
                                  code["verified_evidence_base"](relative))
    rebuilt = _rebuild_aggregate(verifier, rows)
    assert rebuilt["technical_qualification"] == "PASS"
    assert rebuilt["evidence_bound"] is True


def test_unnormalized_evidence_base_unbinds_valid_receipts(commands: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    """Documents the #99 failure mode that verified_evidence_base prevents."""
    code, evidence, aggregate = commands
    monkeypatch.chdir(evidence.parent)
    relative = Path(evidence.name)
    verifier = code["load_verifier"](ROOT)
    rows, original_root = code["validate_commands"](relative, aggregate, verifier)
    _configure_retained_aggregate(verifier, aggregate, original_root, relative)
    rebuilt = _rebuild_aggregate(verifier, rows)
    assert rebuilt["technical_qualification"] == "BLOCKED"
    assert rebuilt["technical_blockers"] == ["command-0-receipt-unbound"]


@pytest.mark.parametrize("form", ["relative", "absolute"])
def test_cli_verify_normalizes_qualification_root(
        commands: tuple, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, form: str) -> None:
    """#99: the real verify CLI must accept the workflow's repository-relative
    --qualification-root and configure the aggregate verifier with the same
    normalized evidence base as for an absolute path.  The sentinel aborts the
    run right after the dynamic validator is fully configured."""
    code, fixture_evidence, aggregate = commands
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True)
    for relative in code["PRIOR_SCHEMAS"]:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "-c", "user.name=Evidence Test", "-c", "user.email=evidence@example.invalid",
                    "commit", "--quiet", "-m", "fixture"], cwd=source, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=source, text=True).strip()
    worktree = code["load_verifier"](source)["worktree_digest"]()

    # Mirror the workflow's candidate bundle layout exactly.
    qualification = tmp_path / "build/release/candidate-bundle/qualification"
    evidence = qualification / "phase7-evidence"
    evidence.mkdir(parents=True)
    shutil.copytree(fixture_evidence / "commands", evidence / "commands")
    prior = qualification / "prior"
    for relative in code["PRIOR_TREES"]:
        (prior / relative).mkdir(parents=True)
    for relative in code["PRIOR_SCHEMAS"]:
        target = prior / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    stage = qualification / "stage"
    stage.mkdir()
    (stage / "staged.txt").write_text("staged payload\n")
    lock = qualification / "integration-lock.json"
    lock.write_text("{}")
    canary = qualification / "host-canary.json"
    canary.write_text("{}")
    stage_summary = aggregate["stage"]
    stage_summary["stage_sha256"] = hashlib.sha256(code["canonical"](sorted(
        (path.relative_to(stage).as_posix(), code["digest"](path))
        for path in code["direct_files"](stage)))).hexdigest()
    stage_summary["integration_lock_sha256"] = code["digest"](lock)
    stage_summary["host_canary_sha256"] = code["digest"](canary)

    (evidence / ".arw-phase7-evidence").write_bytes(b"phase-7 evidence\n")
    aggregate["git_head"] = head
    aggregate["git_tree"] = tree
    aggregate["git_worktree_sha256"] = worktree
    (evidence / "phase-7-verification.json").write_bytes(code["canonical"](aggregate))
    (qualification / "phase-7-verification.json").write_bytes(code["canonical"](aggregate))

    captured = {}
    real_load = code["load_verifier"]

    def patched_load(source_root: Path) -> dict:
        namespace = real_load(source_root)
        namespace["_license_verdict"] = lambda: {
            "technical_qualification": "PASS", "release_qualification": "BLOCKED"}
        receipt_summary = namespace["ValidatedReceiptSummary"](
            {"technical_qualification": "PASS"}, {"technical_qualification": "PASS"},
            _token=namespace["_VALIDATION_TOKEN"])
        namespace["validate_receipts"] = lambda **kwargs: receipt_summary

        def capturing_aggregate(**kwargs: object) -> dict:
            captured["evidence_base"] = namespace["EVIDENCE_BASE"]
            raise ValueError("capture-sentinel")
        namespace["aggregate_verdict"] = capturing_aggregate
        return namespace

    # runpy.run_path returns a copy of the module namespace; patch the real
    # globals dict that the CLI-resolved functions close over.
    monkeypatch.setitem(code["main"].__globals__, "load_verifier", patched_load)
    monkeypatch.chdir(tmp_path)
    root_arg = ("build/release/candidate-bundle/qualification"
                if form == "relative" else str(qualification))
    monkeypatch.setattr("sys.argv", ["phase7-release-evidence", "verify",
        "--qualification-root", root_arg, "--source-commit", head,
        "--source-root", str(source)])
    with pytest.raises(ValueError, match="capture-sentinel"):
        code["main"]()
    assert captured["evidence_base"] == evidence.resolve()
    assert captured["evidence_base"].is_absolute()
