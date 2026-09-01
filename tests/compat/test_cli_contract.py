"""v2 compatibility baseline: CLI surface and golden command contracts.

Pins the v1 `arw` CLI command tree (commands, flags, exit codes, output
structure) so every v2 refactor PR proves it did not change the contract.
See openspec/changes/v2-contract-freeze/design.md.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import pytest

from arw.cli import build_parser

from .normalize import normalize_text, path_replacements, read_golden_json

pytestmark = pytest.mark.v2_compat

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEED = REPOSITORY_ROOT / "tests" / "fixtures" / "recovery" / "seed"
CONTRACT_PATH = Path(__file__).parent / "cli_contract.json"
GOLDEN_DIR = Path(__file__).parent / "golden" / "cli"


def _describe_parser(parser: argparse.ArgumentParser) -> dict:
    """Introspect an argparse parser into a stable, JSON-able command tree.

    Must stay in sync with the generator recorded in the change artifacts;
    the frozen snapshot in cli_contract.json is the authority.
    """
    entry: dict = {"options": [], "positionals": [], "subcommands": {}}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            entry["subparsers_meta"] = {
                "dest": action.dest,
                "required": bool(action.required),
            }
            # Help text is prose, not structure (docs/v2-invariants.md): a
            # help-only edit must not fail the gate, so it is not recorded.
            for name, sub in sorted(action.choices.items()):
                entry["subcommands"][name] = _describe_parser(sub)
            continue
        if isinstance(action, argparse._HelpAction):
            continue
        record: dict = {
            "dest": action.dest,
            "action": type(action).__name__,
            "required": bool(action.required),
        }
        if action.nargs is not None:
            record["nargs"] = action.nargs
        if action.option_strings:
            record["flags"] = list(action.option_strings)
        if action.choices is not None:
            record["choices"] = sorted(str(choice) for choice in action.choices)
        if action.metavar is not None:
            record["metavar"] = (
                action.metavar
                if isinstance(action.metavar, str)
                else list(action.metavar)
            )
        if (
            action.default is not argparse.SUPPRESS
            and action.default is not None
            and action.option_strings
        ):
            default = action.default
            record["default"] = str(default) if isinstance(default, Path) else default
        if action.type is not None:
            record["type"] = getattr(action.type, "__name__", str(action.type))
        (entry["options"] if action.option_strings else entry["positionals"]).append(
            record
        )
    if not entry["subcommands"]:
        entry.pop("subcommands")
    if not entry["positionals"]:
        entry.pop("positionals")
    return entry
def _option_key(record: dict) -> str:
    return ",".join(record.get("flags") or [record["dest"]])


def _assert_frozen_options_subset(
    frozen_records: list, live_records: list, path: str
) -> None:
    """Every frozen option record must appear identically in the live list.

    Additive v2 flags on existing commands are permitted; removal or change
    of a frozen flag is not.
    """
    for record in frozen_records:
        frozen_flags = set(record.get("flags") or [record["dest"]])
        # Aliases are additive (I3): a live action may carry EXTRA flags, but
        # every frozen flag must still resolve to an action whose other
        # frozen attributes are unchanged.
        matches = [
            live
            for live in live_records
            if frozen_flags <= set(live.get("flags") or [live["dest"]])
        ]
        assert matches, f"{path}: v1 option {sorted(frozen_flags)!r} was removed"
        assert len(matches) == 1, f"{path}: ambiguous live options for {sorted(frozen_flags)!r}"
        live = matches[0]
        # Bidirectional field compare: frozen fields must match, AND the live
        # record must not gain contract-significant fields (e.g. a new
        # default or choices) beyond the permitted extra flag aliases.
        for field, value in record.items():
            if field == "flags":
                continue  # alias superset allowed
            assert live.get(field) == value, (
                f"{path}: option {sorted(frozen_flags)!r} field {field!r} drifted"
            )
        extra_fields = set(live) - set(record) - {"flags"}
        assert not extra_fields, (
            f"{path}: option {sorted(frozen_flags)!r} gained contract-significant "
            f"fields {sorted(extra_fields)}"
        )
    # A NEW required option on a frozen command breaks every v1 invocation;
    # additive OPTIONAL flags remain permitted (I3).
    frozen_flag_union = set()
    for record in frozen_records:
        frozen_flag_union |= set(record.get("flags") or [record["dest"]])
    for live in live_records:
        live_flags = set(live.get("flags") or [live["dest"]])
        if live_flags & frozen_flag_union:
            continue  # matched a frozen option (checked above)
        assert not live.get("required"), (
            f"{path}: new required option {sorted(live_flags)!r} breaks v1 invocations"
        )


def _assert_frozen_subcommand_subset(frozen: dict, live: dict, path: str) -> None:
    """Every frozen v1 entry must exist identically in the live tree.

    Additive v2 commands/flags are explicitly permitted (docs/v2-invariants.md
    I3): extra live entries are ignored, but no frozen entry may change or
    disappear. Positionals are pinned exactly (adding one changes parsing).
    """
    frozen_subs = frozen.get("subcommands", {})
    live_subs = live.get("subcommands", {})
    for name, frozen_entry in frozen_subs.items():
        assert name in live_subs, f"{path}: v1 command {name!r} was removed"
        live_entry = live_subs[name]
        _assert_frozen_options_subset(
            frozen_entry.get("options", []), live_entry.get("options", []), f"{path}/{name}"
        )
        assert frozen_entry.get("positionals", []) == live_entry.get("positionals", []), (
            f"{path}/{name}: positionals drifted from the frozen v1 contract"
        )
        assert frozen_entry.get("subparsers_meta") == live_entry.get("subparsers_meta"), (
            f"{path}/{name}: subparser requiredness/dest drifted"
        )
        _assert_frozen_subcommand_subset(frozen_entry, live_entry, f"{path}/{name}")
    _assert_frozen_options_subset(
        frozen.get("options", []), live.get("options", []), path
    )
    assert frozen.get("subparsers_meta") == live.get("subparsers_meta"), (
        f"{path}: subparser requiredness/dest drifted"
    )
    assert frozen.get("positionals", []) == live.get("positionals", []), (
        f"{path}: positionals drifted from the frozen v1 contract"
    )


def test_cli_surface_matches_frozen_contract() -> None:
    """Every v1 command, flag, choice set, and default is pinned.

    Additive v2 commands are permitted (docs/v2-invariants.md I3); the frozen
    v1 surface is a required subset with exact per-entry equality.
    """
    parser = build_parser()
    live = {
        "schema_version": "1.0.0",
        "prog": parser.prog,
        "tree": _describe_parser(parser),
    }
    frozen = read_golden_json(CONTRACT_PATH)
    assert live["schema_version"] == frozen["schema_version"]
    assert live["prog"] == frozen["prog"]
    _assert_frozen_subcommand_subset(frozen["tree"], live["tree"], "arw")


def _seed_run_root(tmp_path: Path) -> Path:
    run_root = tmp_path / "run"
    (run_root / "input").mkdir(parents=True)
    shutil.copyfile(SEED / "input" / "source.txt", run_root / "input" / "source.txt")
    return run_root


class _CliResult(NamedTuple):
    exit_code: int
    stdout: str
    stderr: str


def _invoke(argv: list[str]) -> _CliResult:
    """Run through the public entry point: python -m arw.cli.

    In-process main() calls would keep passing even if module execution or
    exit propagation broke; the compatibility gate must cross the real CLI
    boundary (docs/v2-invariants.md I3).
    """
    # Strip host-integration variables so goldens (e.g. route's BLOCKED
    # reason) do not depend on the caller's Codex qualification environment.
    clean_env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("ARW_CODEX_", "ARW_HOST_", "ARW_INTEGRATION_", "ARW_PLUGIN_ROOT", "ARW_BUILD_IDENTITY", "ARW_SCHEMA_ROOT"))
    }
    clean_env.update({"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1"})
    completed = subprocess.run(
        [sys.executable, "-m", "arw.cli", *argv],
        cwd=REPOSITORY_ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    return _CliResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def _json_or_text(value: str) -> object:
    """Parse JSON output so key order/whitespace stay cosmetic (structure is
    pinned, serializer cosmetics are not); non-JSON text compares exactly."""
    try:
        return json.loads(value)
    except ValueError:
        return value


def _assert_golden(
    name: str, actual: _CliResult, replacements: dict[str, str]
) -> None:
    normalized = {
        "exit_code": actual.exit_code,
        "stdout": _json_or_text(normalize_text(actual.stdout, replacements=replacements)),
        "stderr": normalize_text(actual.stderr, replacements=replacements),
    }
    golden = read_golden_json(GOLDEN_DIR / name)
    golden_structural = {
        "exit_code": golden["exit_code"],
        "stdout": _json_or_text(golden["stdout"]),
        "stderr": golden["stderr"],
    }
    assert normalized == golden_structural, f"golden mismatch for {name}"


def test_run_lifecycle_commands_match_golden(tmp_path: Path) -> None:
    """init -> append -> replay -> status on the recovery seed, pinned."""
    run_root = _seed_run_root(tmp_path)
    replacements = path_replacements(run_root=run_root, seed=SEED, tmp_path=tmp_path)

    _assert_golden(
        "init.json",
        _invoke(
            [
                "init",
                "--run-root",
                str(run_root),
                "--request",
                str(SEED / "init-request.json"),
            ],
        ),
        replacements,
    )
    _assert_golden(
        "append.json",
        _invoke(
            [
                "append",
                "--run-root",
                str(run_root),
                "--request",
                str(SEED / "append-request.json"),
            ],
        ),
        replacements,
    )
    _assert_golden(
        "replay.json",
        _invoke(["replay", "--run-root", str(run_root)]),
        replacements,
    )
    _assert_golden(
        "status.json",
        _invoke(
            [
                "status",
                "--run-root",
                str(run_root),
                "--json",
                "--at",
                "2026-07-13T00:00:02Z",
            ],
        ),
        replacements,
    )
    # The seeded event bytes themselves are the strongest pin: init must
    # reproduce the checked-in expected event byte-for-byte.
    expected_event = (SEED / "expected-initial-event.jsonl").read_bytes()
    journal_lines = (run_root / "events.jsonl").read_bytes().splitlines()
    assert journal_lines[0] + b"\n" == expected_event


def test_no_args_and_unknown_command_exit_codes() -> None:
    """Argparse usage errors keep their v1 exit codes (2) and stderr routing."""
    no_args = _invoke([])
    assert no_args.exit_code == 2
    unknown = _invoke(["not-a-command"])
    assert unknown.exit_code == 2
    assert no_args.stdout == "" and unknown.stdout == ""
    assert "usage:" in no_args.stderr and "usage:" in unknown.stderr


# Every command that takes --request must keep its v1 failure envelope when
# the request file is missing: exit code 65 and the "arw: ..." stderr prefix.
# This pins handler wiring (argparse -> request loading -> CLIInputError) for
# the full command surface, not just the four lifecycle golden transcripts.
REQUEST_COMMANDS = [
    "append",
    "artifact-accept",
    "attempt-close",
    "attempt-start",
    "checkpoint",
    "decision-request",
    "decision-resolve",
    "init",
    "orchestration-dispatch",
    "orchestration-gate",
    "orchestration-hook",
    "orchestration-panel",
    "orchestration-prepare",
    "orchestration-recover",
    "recover",
    "resume",
    "transition",
]


@pytest.mark.parametrize("command", REQUEST_COMMANDS)
def test_request_commands_missing_request_envelope(
    tmp_path: Path, command: str
) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    argv = [
        command,
        "--run-root",
        str(run_root),
        "--request",
        str(tmp_path / "missing-request.json"),
    ]
    extra_required = {
        "orchestration-prepare": "--assignments",
        "orchestration-panel": "--panel",
        "orchestration-gate": "--gate",
        "orchestration-hook": "--observation",
    }
    if command in extra_required:
        # Supplemental inputs are VALID canonical bytes, so the missing
        # --request file is provably the first failure point.
        supplemental = tmp_path / "supplemental.json"
        supplemental.write_bytes(b"[]" if command == "orchestration-prepare" else b"{}")
        argv += [extra_required[command], str(supplemental)]
    result = _invoke(argv)
    assert result.exit_code == 65, f"{command}: expected exit 65, got {result.exit_code}"
    assert result.stdout == ""
    normalized = normalize_text(
        result.stderr, replacements=path_replacements(tmp_path=tmp_path, run_root=run_root)
    )
    # Exact per-command envelope pin, not just the shared prefix.
    envelopes = read_golden_json(GOLDEN_DIR / "request_error_envelopes.json")
    assert normalized == envelopes[command], f"{command}: error envelope drifted"


def test_files_extraction_register_missing_request_envelope(tmp_path: Path) -> None:
    """The nested `files extraction register` command keeps its v1 envelope."""
    result = _invoke(
        [
            "files",
            "extraction",
            "register",
            "--control-root",
            str(tmp_path / "control"),
            "--root-id",
            "research-root",
            "--request",
            str(tmp_path / "missing-request.json"),
            "--text",
            str(tmp_path / "missing-text.txt"),
        ]
    )
    assert result.exit_code == 65
    assert result.stdout == ""
    normalized = normalize_text(
        result.stderr, replacements=path_replacements(tmp_path=tmp_path)
    )
    envelopes = read_golden_json(GOLDEN_DIR / "request_error_envelopes.json")
    assert normalized == envelopes["files extraction register"], (
        "nested files extraction register error envelope drifted"
    )


def test_installed_launcher_allowlist_matches_golden() -> None:
    """The installed bin/arw launcher's command allowlist is frozen (I3).

    The launcher forwards or rejects commands before Python ever runs; a
    removed allowlist entry or broken forwarding would regress the installed
    contract while build_parser() stays unchanged.
    """
    launcher = REPOSITORY_ROOT / "bin" / "arw"
    try:
        source = launcher.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise AssertionError(f"launcher unreadable: {error}") from error
    match = re.search(r'case "\$COMMAND" in\n\s+([a-z0-9_|-]+)\) ;;\n', source)
    assert match is not None, "launcher allowlist case statement not found"
    commands = set(match.group(1).split("|"))
    golden = read_golden_json(GOLDEN_DIR / "launcher_allowlist.json")
    # Subset semantics: additive v2 commands are permitted (I3); dropping a
    # frozen v1 command is not.
    missing = set(golden["commands"]) - commands
    assert not missing, f"bin/arw dropped frozen v1 launcher commands: {sorted(missing)}"


def test_installed_launcher_execution_envelopes() -> None:
    """Execute bin/arw for the two install-independent paths (I3).

    No-args prints usage; an unknown command is rejected with the v1 shell
    error envelope. Both paths run before any plugin-root resolution, so they
    work from a plain source checkout. Full `health`/`route` behavior is
    pinned by the staged-plugin suites (tests/staged).
    """
    launcher = REPOSITORY_ROOT / "bin" / "arw"
    golden = read_golden_json(GOLDEN_DIR / "launcher_envelopes.json")

    no_args = subprocess.run(
        ["bash", str(launcher)], capture_output=True, text=True, check=False
    )
    assert no_args.returncode == golden["no_args"]["exit_code"]
    assert no_args.stdout == golden["no_args"]["stdout"]
    assert no_args.stderr == golden["no_args"]["stderr"]

    bogus = subprocess.run(
        ["bash", str(launcher), "not-a-command"], capture_output=True, text=True, check=False
    )
    assert bogus.returncode == golden["bogus_command"]["exit_code"]
    assert bogus.stdout == golden["bogus_command"]["stdout"]
    assert bogus.stderr == golden["bogus_command"]["stderr"]


# Volatile files-admin fields: per-run instance ids, generation ids, wall
# clock, and machine paths. Content-addressed digests and status fields are
# pinned exactly.
FILES_ADMIN_SCRUB_KEYS = {
    "attempt_id",
    "candidate_generation_id",
    "canonical_path",
    "completed_at",
    "created_at",
    # CLI default id factory is random and generation manifests embed it, so
    # downstream content digests are volatile too; deterministic digests are
    # pinned separately via the fixed-clock service in test_mcp_contract.py.
    "generation_id",
    "generation_manifest_sha256",
    "identity_manifest_sha256",
    "previous_generation_id",
    "receipt_id",
    "root_instance_id",
    "selected_at",
    "selected_generation_id",
    "started_at",
}


def _scrub_admin(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: ("<SCRUBBED>" if key in FILES_ADMIN_SCRUB_KEYS else _scrub_admin(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_scrub_admin(item) for item in value]
    return value


def test_files_admin_handler_goldens(tmp_path: Path) -> None:
    """files root register / sync / status succeed with pinned output shape.

    Parser introspection cannot catch a broken handler dispatch; these
    invocations exercise the real handler branches end-to-end (I3).
    """
    root = tmp_path / "root"
    (root / "notes").mkdir(parents=True)
    (root / "notes" / "a.txt").write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    control = tmp_path / "control"

    register = _invoke(
        [
            "files", "root", "register",
            "--control-root", str(control),
            "--root-id", "research-root",
            "--root-path", str(root),
            "--policy-id", "research-files-v1",
        ]
    )
    sync = _invoke(
        [
            "files", "sync",
            "--control-root", str(control),
            "--root-id", "research-root",
            "--extractor-version", "1.0.0",
        ]
    )
    status = _invoke(
        ["files", "status", "--control-root", str(control), "--root-id", "research-root"]
    )

    golden = read_golden_json(GOLDEN_DIR / "files_admin.json")
    for label, result in (("register", register), ("sync", sync), ("status", status)):
        assert result.exit_code == 0, f"{label}: {result.stderr}"
        payload = json.loads(result.stdout)
        expected = golden[label]
        assert _scrub_admin(payload) == _scrub_admin(expected["payload"]), (
            f"files {label}: output structure drifted"
        )


def test_remaining_command_success_and_error_goldens(tmp_path: Path) -> None:
    """Pin the remaining deterministic command paths (I3).

    `route --json` succeeds with the checkout's BLOCKED route contract;
    `version --json` fails deterministically without packaged build identity;
    `passport-pointer-rebuild` on the legacy seed run fails deterministically
    (no accepted passport). Each pins exit code + full envelope.
    """
    golden = read_golden_json(GOLDEN_DIR / "misc_commands.json")

    route = _invoke(["route", "--json"])
    assert route.exit_code == golden["route"]["exit_code"]
    assert json.loads(route.stdout) == golden["route"]["stdout"]

    version = _invoke(["version", "--json"])
    assert version.exit_code == golden["version"]["exit_code"]
    assert version.stdout == golden["version"]["stdout"]
    assert version.stderr.startswith(golden["version"]["stderr_prefix"])

    run_root = _seed_run_root(tmp_path)
    _invoke(["init", "--run-root", str(run_root), "--request", str(SEED / "init-request.json")])
    rebuild = _invoke(["passport-pointer-rebuild", "--run-root", str(run_root)])
    assert rebuild.exit_code == golden["pointer_rebuild"]["exit_code"]
    assert normalize_text(
        rebuild.stderr, replacements=path_replacements(run_root=run_root)
    ) == golden["pointer_rebuild"]["stderr"]
