"""Fresh, bounded task transports under the existing parent scheduler.

External drivers return a protocol envelope, never transcript-derived state.
Only this parent adapter can install proposal/artifact bytes into the run.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import signal
import stat
import sys
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.execution.execution import (
    DispatchSpec,
    HostResult,
    PermissionDenied,
    ProcessFailure,
    StaleAttempt,
)
from arw.kernel.execution.harness_config import (
    HarnessConfigError,
    HarnessConfiguration,
    HarnessEntry,
    runtime_credentials,
)
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.manifests import (
    load_artifact_manifest,
    load_assignment_manifest,
)
from arw.kernel.state.models import RunManifest
from arw.kernel.state.orchestration_models import (
    AttemptDescriptor,
    HostIdentityReceiptV2,
    canonical_orchestration_model_bytes,
    validate_worker_proposal_bytes,
)

MAX_REQUEST_BYTES = 2_097_152
MAX_ENVELOPE_BYTES = 8_388_608
SYSTEM_ROOTS = ("/usr", "/bin", "/lib", "/lib64")
SYSTEM_FILES = (
    "/etc/resolv.conf",
    "/etc/hosts",
    "/etc/nsswitch.conf",
    "/etc/ssl",
    "/etc/pki",
)


def _regular_bytes(path: Path, max_bytes: int) -> bytes:
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size > max_bytes:
                raise StaleAttempt("harness input is not a bounded regular file")
            raw = handle.read(max_bytes + 1)
            after = os.fstat(handle.fileno())
            if len(raw) > max_bytes or before.st_size != after.st_size:
                raise StaleAttempt("harness input changed or exceeds limit")
            return raw
    except OSError:
        raise StaleAttempt("harness input is not a bounded regular file") from None


def _request(spec: DispatchSpec, host_id: str) -> tuple[object, dict[str, object]]:
    root = spec.assignment_path.parent.parent
    assignment = load_assignment_manifest(root, spec.assignment_id)
    if assignment.execution_mode != "assignment_injected_subagent":
        raise PermissionDenied(
            "configured harness requires assignment_injected_subagent mode"
        )
    if not spec.proposal_nonce:
        raise StaleAttempt("configured harness requires a parent-frozen nonce")
    snapshot = _regular_bytes(spec.attempt_root / "assignment.json", MAX_REQUEST_BYTES)
    if snapshot != canonical_orchestration_model_bytes(assignment):
        raise StaleAttempt("attempt assignment snapshot drifted")
    replayed = replay_run(root)
    manifest = RunManifest.model_validate(
        strict_json_loads(_regular_bytes(root / "run-manifest.json", MAX_REQUEST_BYTES))
    )
    modes = [
        event.payload
        for event in replayed.events
        if event.event_type == "execution.mode_selected"
    ]
    if len(modes) != 1:
        raise StaleAttempt("canonical preparation context is unavailable")
    context = {
        "immutable_input": manifest.immutable_input.model_dump(mode="json"),
        "preparation_intent_sha256": modes[0].dag_sha256,
        "role_catalog_sha256": modes[0].role_catalog_sha256,
    }
    if assignment.narrative_snapshot is not None:
        context["narrative_snapshot"] = assignment.narrative_snapshot.model_dump(
            mode="json"
        )
    if sha256_hex(canonical_json_bytes(context)) != assignment.context_manifest_sha256:
        raise StaleAttempt("canonical preparation context digest drifted")
    inputs = []
    total = 0
    for digest in assignment.input_sha256:
        paths = []
        if digest == manifest.immutable_input.sha256:
            paths.append(manifest.immutable_input.path)
        for event in replayed.events:
            if (
                event.event_type in {"artifact.accepted", "research_artifact_accepted"}
                and event.payload.artifact_sha256 == digest
            ):
                paths.append(
                    load_artifact_manifest(
                        root, event.payload.manifest_sha256
                    ).content_path
                )
        if len(paths) != 1:
            raise StaleAttempt(
                "assignment input has zero or ambiguous canonical sources"
            )
        candidate = root / paths[0]
        if not candidate.resolve(strict=True).is_relative_to(root.resolve()):
            raise StaleAttempt("assignment input escapes canonical root")
        for parent in (candidate, *candidate.parents):
            if parent == root:
                break
            if parent.is_symlink():
                raise StaleAttempt("assignment input has a symlink ancestor")
        raw = _regular_bytes(candidate, MAX_REQUEST_BYTES - total)
        if sha256_hex(raw) != digest:
            raise StaleAttempt("assignment input digest drifted")
        total += len(raw)
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeError:
            raise StaleAttempt(
                "configured harness requires explicit text extraction for binary input"
            ) from None
        inputs.append({"sha256": digest, "text": text})
    template = {
        "schema_version": "arw.worker-proposal.v1",
        "protocol_version": "1.0.0",
        **{
            name: getattr(assignment, name)
            for name in (
                "run_id",
                "assignment_id",
                "role_id",
                "worker_identity_id",
                "execution_mode",
                "execution_provenance",
                "independence_eligible",
                "context_manifest_sha256",
                "policy_sha256",
                "base_revision",
                "input_sha256",
            )
        },
        "assignment_sha256": assignment.canonical_sha256(),
        "attempt_id": spec.attempt_id,
        "host_agent_id": host_id,
        "proposal_nonce": spec.proposal_nonce,
        "status": "blocked",
        "result_provenance_mode": "executed",
        "requested_next_action": "none",
        "artifacts": [],
        "evidence_sha256": [],
        "summary": "Replace with actual result",
        "unresolved": [],
    }
    return assignment, {
        "schema_version": "arw.harness-request.v1",
        "assignment": assignment.model_dump(mode="json"),
        "context": context,
        "inputs": inputs,
        "proposal_template": template,
        "output_contract": {
            "schema_version": "arw.harness-output.v1",
            "proposal_max_bytes": spec.effective_proposal_max_bytes,
            "envelope_max_bytes": MAX_ENVELOPE_BYTES,
            "artifacts": "map of direct filenames to UTF-8 text",
        },
    }


class ConfiguredHarnessAdapter:
    def __init__(
        self,
        entry: HarnessEntry,
        *,
        config_sha256: str,
        config_base: Path,
        environment: dict[str, str] | None = None,
        config_snapshot: bytes | None = None,
    ):
        if entry.kind not in {"command", "api"}:
            raise HarnessConfigError("built-in adapter requires command or API kind")
        self.entry = HarnessEntry.model_validate_json(entry.model_dump_json())
        self._entry_sha256 = sha256_hex(
            canonical_json_bytes(self.entry.model_dump(mode="json"))
        )
        self.config_sha256 = config_sha256
        self.config_snapshot = config_snapshot
        self.config_base = config_base.resolve()
        self.environment = environment
        self._processes: dict[str, asyncio.subprocess.Process] = {}

    def preflight(self, run_root: Path) -> None:
        if self.config_snapshot is None:
            raise HarnessConfigError(
                "configured dispatch requires a retained public configuration snapshot"
            )
        try:
            configuration = HarnessConfiguration.model_validate_json(
                self.config_snapshot
            )
            if (
                configuration.config_sha256 != self.config_sha256
                or canonical_json_bytes(configuration.model_dump(mode="json"))
                != self.config_snapshot
            ):
                raise ValueError("digest mismatch")
        except ValueError:
            raise HarnessConfigError(
                "configured harness snapshot digest or schema invalid"
            ) from None
        if (
            sha256_hex(canonical_json_bytes(self.entry.model_dump(mode="json")))
            != self._entry_sha256
        ):
            raise PermissionDenied("harness configuration changed after selection")
        if sys.platform != "linux" or not shutil.which("bwrap"):
            raise PermissionDenied(
                "configured harness needs Linux bubblewrap task isolation"
            )
        secrets = runtime_credentials(self.entry, self.config_base, self.environment)
        if any(value.encode() in self.config_snapshot for value in secrets.values()):
            raise HarnessConfigError(
                "runtime credential appears in public harness configuration"
            )
        self._runtime_roots(run_root)

    def _runtime_roots(self, run_root: Path) -> tuple[Path, ...]:
        selected = []
        for name in self.entry.runtime_roots:
            path = Path(name)
            if not path.is_absolute():
                path = self.config_base / path
            path = path.resolve(strict=True)
            if not (path.is_file() or path.is_dir()) or any(
                path.is_relative_to(root)
                for root in (Path("/proc"), Path("/sys"), Path("/dev"))
            ):
                raise PermissionDenied(
                    "runtime root must contain regular executable inputs"
                )
            # Never mount a canonical run, peer tasks, a whole home or broad temp roots.
            if (
                path == Path.home()
                or path in {Path("/"), Path("/home"), Path("/tmp"), Path("/var/tmp")}
                or path == run_root.resolve()
                or path.is_relative_to(run_root.resolve())
                or run_root.resolve().is_relative_to(path)
            ):
                raise PermissionDenied("runtime root exposes canonical or peer state")
            selected.append(path)
        return tuple(selected)

    def _argv(self, task: Path, run_root: Path, probe: bool = False) -> tuple[str, ...]:
        command = [
            shutil.which("bwrap") or "bwrap",
            "--unshare-all",
            "--share-net",
            "--die-with-parent",
            "--new-session",
            "--cap-drop",
            "ALL",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
        ]
        for path in (*SYSTEM_ROOTS, *SYSTEM_FILES):
            if Path(path).exists():
                command.extend(("--ro-bind", path, path))
        for path in self._runtime_roots(run_root):
            command.extend(("--ro-bind", str(path), str(path)))
        if self.entry.kind == "api":
            worker = Path(__file__).with_name("api_worker.py").resolve()
            command.extend(("--ro-bind", str(worker), "/api_worker.py"))
            # Use a system interpreter: the worker deliberately has no third-party imports.
            interpreter = shutil.which("python3", path="/usr/bin:/bin")
            if not interpreter:
                raise PermissionDenied("API worker system Python is unavailable")
            inner = (interpreter, "-I", "-S", "/api_worker.py")
        else:
            inner = self.entry.command
        command.extend(
            (
                "--bind",
                str(task),
                "/work",
                "--chdir",
                "/work",
                "--setenv",
                "HOME",
                "/work/home",
                "--setenv",
                "TMPDIR",
                "/tmp",
            )
        )
        if probe:
            # Both mount confinement and fresh home are exercised, without a model call.
            inner = (
                "/bin/sh",
                "-c",
                (
                    'test ! -e "$1" && test ! -e "$2" && test -d /work/home && '
                    "touch /work/probe && ! touch /usr/arw-isolation-probe 2>/dev/null"
                ),
                "probe",
                str(run_root.resolve()),
                str(Path.home() / ".codex/auth.json"),
            )
        command.extend(("--", *inner))
        return tuple(command)

    def _runtime_digest(self, run_root: Path) -> str:
        """Bind selected executable/driver bytes, not a claimed provider version."""
        if self.entry.kind == "api":
            executable = Path(shutil.which("python3", path="/usr/bin:/bin"))
            roots = (Path(__file__).with_name("api_worker.py"),)
        else:
            executable = Path(
                shutil.which(self.entry.command[0], path="/usr/bin:/bin")
                or self.entry.command[0]
            )
            roots = self._runtime_roots(run_root)
        files = {executable.resolve(strict=True)}
        topology = []
        entries = 0
        for root in roots:
            if root.is_file():
                files.add(root.resolve())
            else:
                topology.append({"root": str(root), "path": ".", "type": "directory"})
                for path in root.rglob("*"):
                    entries += 1
                    if path.is_symlink():
                        try:
                            resolved = path.resolve(strict=True)
                        except (OSError, RuntimeError):
                            raise PermissionDenied(
                                "selected runtime symlink is dangling or cyclic"
                            ) from None
                        if not resolved.is_relative_to(root):
                            raise PermissionDenied(
                                "selected runtime symlink escapes its root"
                            )
                        topology.append(
                            {
                                "root": str(root),
                                "path": path.relative_to(root).as_posix(),
                                "type": "symlink",
                                "target": os.readlink(path),
                                "resolved": resolved.relative_to(root).as_posix(),
                            }
                        )
                    elif path.is_file():
                        files.add(path)
                    elif path.is_dir():
                        topology.append(
                            {
                                "root": str(root),
                                "path": path.relative_to(root).as_posix(),
                                "type": "directory",
                            }
                        )
                    else:
                        raise PermissionDenied(
                            "selected runtime contains a special file"
                        )
                    if entries > 16384:
                        raise PermissionDenied("runtime inventory exceeds file bound")
        digest = hashlib.sha256(canonical_json_bytes({"command": self.entry.command}))
        for row in sorted(topology, key=lambda row: (row["root"], row["path"])):
            digest.update(canonical_json_bytes(row))
        total = 0
        for path in sorted(files):
            status = path.stat()
            total += status.st_size
            if not stat.S_ISREG(status.st_mode) or total > 1_073_741_824:
                raise PermissionDenied("selected runtime executable is unavailable")
            content = hashlib.sha256()
            with path.open("rb") as handle:
                while chunk := handle.read(1_048_576):
                    content.update(chunk)
            digest.update(
                canonical_json_bytes({"path": str(path), "sha256": content.hexdigest()})
            )
        return digest.hexdigest()

    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        run_root = spec.assignment_path.parent.parent.resolve()
        self.preflight(run_root)
        runtime_sha256 = await asyncio.to_thread(self._runtime_digest, run_root)
        secrets = runtime_credentials(self.entry, self.config_base, self.environment)
        accepted_assignment = load_assignment_manifest(run_root, spec.assignment_id)
        configuration = HarnessConfiguration.model_validate_json(self.config_snapshot)
        selected = configuration.select(
            spec.assignment_id, accepted_assignment.role_id
        )[1]
        if (
            sha256_hex(canonical_json_bytes(selected.model_dump(mode="json")))
            != self._entry_sha256
        ):
            raise PermissionDenied(
                "selected harness does not match frozen assignment routing"
            )
        host_id = (
            "host.harness-"
            + sha256_hex(
                canonical_json_bytes(
                    {
                        "config_sha256": self.config_sha256,
                        "worker_identity_id": accepted_assignment.worker_identity_id,
                    }
                )
            )[:32]
        )
        assignment, request = _request(spec, host_id)
        if self.entry.kind == "command":
            request["harness_parameters"] = self.entry.parameters
        if self.entry.kind == "api":
            request["api"] = {
                **{
                    name: getattr(self.entry, name)
                    for name in (
                        "endpoint",
                        "model",
                        "protocol",
                        "api_key_env",
                        "max_output_tokens",
                        "reasoning_effort",
                        "parameters",
                    )
                },
                "timeout_seconds": spec.effective_timeout_seconds,
                "response_max_bytes": MAX_ENVELOPE_BYTES,
            }
        raw = canonical_json_bytes(request)
        if len(raw) > MAX_REQUEST_BYTES:
            raise StaleAttempt("harness request exceeds bound")
        if any(value.encode() in raw for value in secrets.values()):
            raise PermissionDenied("runtime credential appears in model input")
        wire = {}
        task_parent = spec.attempt_root / "scratch"
        if task_parent.is_symlink() or not task_parent.is_dir():
            raise StaleAttempt("parent-frozen attempt scratch is unavailable")
        with tempfile.TemporaryDirectory(
            prefix="harness-", dir=task_parent
        ) as temporary:
            task = Path(temporary)
            (task / "home").mkdir(mode=0o700)
            env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", **secrets}
            probe = await asyncio.create_subprocess_exec(
                *self._argv(task, run_root, probe=True),
                env={"PATH": "/usr/bin:/bin"},
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                await asyncio.wait_for(probe.wait(), timeout=5)
            except BaseException:
                self._signal(probe, signal.SIGKILL)
                await probe.wait()
                raise
            if probe.returncode:
                raise PermissionDenied("actual task namespace isolation probe failed")
            process = await asyncio.create_subprocess_exec(
                *self._argv(task, run_root),
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            self._processes[spec.attempt_id] = process
            try:
                output, _error = await self._communicate(process, raw)
                if process.returncode == 77:
                    raise PermissionDenied(
                        "configured harness authentication or permission denied"
                    )
                if process.returncode == 65:
                    raise StaleAttempt("configured harness output contract rejected")
                if process.returncode != 0:
                    raise ProcessFailure("configured harness process failed")
                if any(value.encode() in output for value in secrets.values()):
                    raise PermissionDenied(
                        "runtime credential appeared in worker output"
                    )
                if self.entry.kind == "api":
                    for name, limit in (
                        ("wire-request.json", 4_194_304),
                        ("wire-response.json", MAX_ENVELOPE_BYTES),
                    ):
                        data = _regular_bytes(task / name, limit)
                        if any(value.encode() in data for value in secrets.values()):
                            raise PermissionDenied(
                                "runtime credential appeared in API wire content"
                            )
                        wire[name] = data
                try:
                    current_runtime = await asyncio.to_thread(
                        self._runtime_digest, run_root
                    )
                except (PermissionDenied, OSError, RuntimeError):
                    raise StaleAttempt(
                        "selected harness runtime became unavailable during execution"
                    ) from None
                if current_runtime != runtime_sha256:
                    raise StaleAttempt(
                        "selected harness runtime bytes changed during execution"
                    )
                proposal_path = self._install_output(spec, assignment, host_id, output)
            finally:
                self._signal(process, signal.SIGKILL)
                self._processes.pop(spec.attempt_id, None)
                await process.wait()
        for name, data in wire.items():
            with (spec.attempt_root / "observations" / name).open("xb") as handle:
                handle.write(data)
        retained = {
            "harness-config.json": self.config_snapshot,
            "harness-entry.json": canonical_json_bytes(
                self.entry.model_dump(mode="json")
            ),
            "harness-request.json": raw,
            "harness-output.json": output,
        }
        for name, data in retained.items():
            with (spec.attempt_root / "observations" / name).open("xb") as handle:
                handle.write(data)
        observation = {
            "schema_version": "arw.harness-observation.v1",
            "attempt_id": spec.attempt_id,
            "assignment_id": spec.assignment_id,
            "role_id": assignment.role_id,
            "worker_identity_id": assignment.worker_identity_id,
            "host_agent_id": host_id,
            "harness_kind": self.entry.kind,
            "harness_config_sha256": self.config_sha256,
            "entry_sha256": self._entry_sha256,
            "runtime_sha256": runtime_sha256,
            "request_sha256": sha256_hex(raw),
            "response_sha256": sha256_hex(output),
            "process_id": process.pid,
            "namespace_instance_id": uuid.uuid4().hex,
            "returncode": process.returncode,
            "assignment_mapping_proven": True,
            "isolation_proven": True,
            "peer_isolation_proven": True,
            "credential_isolation_proven": True,
            "isolation_scope": "local task namespace and stateless request; provider internals unobserved",
            "remote_cancellation_proven": False,
            **(
                {
                    "wire_request_sha256": sha256_hex(wire["wire-request.json"]),
                    "wire_response_sha256": sha256_hex(wire["wire-response.json"]),
                }
                if wire
                else {}
            ),
            "observed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        observed_raw = canonical_json_bytes(observation)
        observation_path = (
            spec.attempt_root / "observations" / "harness-observation.json"
        )
        with observation_path.open("xb") as handle:
            handle.write(observed_raw)
        return HostResult(
            attempt_id=spec.attempt_id,
            host_agent_id=host_id,
            proposal_path=proposal_path,
            observation_path=observation_path,
            observation_sha256=sha256_hex(observed_raw),
            output_bytes=len(output),
            execution_mode="assignment_injected_subagent",
            formal_independence=True,
            assignment_mapping_proven=True,
            isolation_proven=True,
            process_id=process.pid,
            returncode=process.returncode,
            transport=f"isolated_{self.entry.kind}_worker",
            worker_identity_id=assignment.worker_identity_id,
            runtime_version="arw.harness-worker.v1",
            runtime_sha256=runtime_sha256,
            profile_digest=self.config_sha256,
        )

    async def _communicate(self, process, raw: bytes) -> tuple[bytes, bytes]:
        async def capture(reader):
            data = bytearray()
            exceeded = False
            while chunk := await reader.read(65536):
                if not exceeded:
                    data.extend(chunk)
                if len(data) > MAX_ENVELOPE_BYTES and not exceeded:
                    exceeded = True
                    self._signal(process, signal.SIGKILL)
            if exceeded:
                raise StaleAttempt("harness output exceeds frozen envelope bound")
            return bytes(data)

        async def send():
            process.stdin.write(raw)
            await process.stdin.drain()
            process.stdin.close()
            await process.stdin.wait_closed()

        tasks = [
            asyncio.create_task(capture(process.stdout)),
            asyncio.create_task(capture(process.stderr)),
            asyncio.create_task(send()),
        ]
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            await process.wait()
            for result in results:
                if isinstance(result, StaleAttempt):
                    raise result
                if isinstance(result, BaseException):
                    raise ProcessFailure(
                        "configured harness input/output failed"
                    ) from None
            return results[0], results[1]
        except asyncio.CancelledError:
            self._signal(process, signal.SIGKILL)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

            # Reap with pipes drained even if cancellation interrupted a paused reader.
            async def drain(reader):
                while await reader.read(65536):
                    pass

            await asyncio.gather(drain(process.stdout), drain(process.stderr))
            await process.wait()
            raise
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    @staticmethod
    def _install_output(spec, assignment, host_id, output: bytes) -> Path:
        try:
            envelope = strict_json_loads(output)
            if (
                not isinstance(envelope, dict)
                or set(envelope) != {"schema_version", "proposal", "artifacts"}
                or envelope["schema_version"] != "arw.harness-output.v1"
            ):
                raise ValueError("invalid harness envelope")
            proposal_raw = canonical_json_bytes(envelope["proposal"])
            if len(proposal_raw) > min(
                spec.effective_proposal_max_bytes, assignment.output_policy.max_bytes
            ):
                raise ValueError("proposal exceeds bound")
            attempt = AttemptDescriptor(
                schema_version="arw.attempt-descriptor.v1",
                assignment_id=spec.assignment_id,
                attempt_id=spec.attempt_id,
                attempt_number=spec.attempt_number,
                proposal_nonce=spec.proposal_nonce,
                status="completed",
                retry_reason=None,
                retry_eligible=False,
                continuation_count=0,
                host_agent_id=host_id,
                cancellation_deadline_at=None,
            )
            proposal, _ = validate_worker_proposal_bytes(
                proposal_raw, assignment=assignment, attempt=attempt
            )
            contents = envelope["artifacts"]
            if not isinstance(contents, dict) or set(contents) != {
                a.relative_path for a in proposal.artifacts
            }:
                raise ValueError("artifact inventory differs from proposal")
            if len(proposal.artifacts) > assignment.output_policy.max_artifacts:
                raise ValueError("artifact count exceeds policy")
            artifacts = []
            for artifact in proposal.artifacts:
                text = contents[artifact.relative_path]
                if artifact.relative_path == "proposal.json" or not isinstance(
                    text, str
                ):
                    raise ValueError("invalid artifact content")
                data = text.encode("utf-8")
                if (
                    len(data) != artifact.byte_count
                    or sha256_hex(data) != artifact.sha256
                ):
                    raise ValueError("artifact digest or byte count differs")
                artifacts.append((artifact.relative_path, data))
        except (ValueError, TypeError, KeyError, UnicodeError):
            # Never retain untrusted validation text (which may echo credentials).
            raise StaleAttempt(
                "harness envelope identity, digest, path or bound invalid"
            ) from None
        result = spec.attempt_root / "result"
        if result.is_symlink() or not result.is_dir():
            raise StaleAttempt("parent-frozen result directory is unavailable")
        targets = [result / name for name, _ in artifacts] + [result / "proposal.json"]
        if any(path.exists() or path.is_symlink() for path in targets):
            raise StaleAttempt("harness cannot replace an existing result")
        for name, data in (*artifacts, ("proposal.json", proposal_raw)):
            with (result / name).open("xb") as handle:
                handle.write(data)
        return result / "proposal.json"

    @staticmethod
    def _signal(process, sig):
        if process.returncode is None:
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                pass

    async def request_cancel(self, spec: DispatchSpec) -> None:
        if process := self._processes.get(spec.attempt_id):
            self._signal(process, signal.SIGTERM)

    async def force_terminate(self, spec: DispatchSpec) -> None:
        if process := self._processes.get(spec.attempt_id):
            self._signal(process, signal.SIGKILL)
            await process.wait()


def identity_receipt_from_observation(
    path: Path, *, receipt_id: str, evidence_sha256: tuple[str, ...]
) -> HostIdentityReceiptV2:
    raw = _regular_bytes(path, 65536)
    observed = strict_json_loads(raw)
    if (
        observed.get("schema_version") != "arw.harness-observation.v1"
        or canonical_json_bytes(observed) != raw
        or observed.get("returncode") != 0
    ):
        raise StaleAttempt("successful canonical harness observation is unavailable")
    for name, key, limit in (
        ("harness-config.json", "harness_config_sha256", MAX_REQUEST_BYTES),
        ("harness-entry.json", "entry_sha256", MAX_REQUEST_BYTES),
        ("harness-request.json", "request_sha256", MAX_REQUEST_BYTES),
        ("harness-output.json", "response_sha256", MAX_ENVELOPE_BYTES),
    ):
        if sha256_hex(_regular_bytes(path.parent / name, limit)) != observed[key]:
            raise StaleAttempt("retained harness observation content digest drifted")
    if observed["harness_kind"] == "api":
        for name, key, limit in (
            ("wire-request.json", "wire_request_sha256", 4_194_304),
            ("wire-response.json", "wire_response_sha256", MAX_ENVELOPE_BYTES),
        ):
            if sha256_hex(_regular_bytes(path.parent / name, limit)) != observed[key]:
                raise StaleAttempt("retained API wire content digest drifted")
    return HostIdentityReceiptV2(
        schema_version="arw.host-identity-receipt.v2",
        receipt_id=receipt_id,
        transport=f"isolated_{observed['harness_kind']}_worker",
        observation_sha256=sha256_hex(raw),
        evidence_sha256=evidence_sha256,
        **{
            name: observed[name]
            for name in (
                "assignment_id",
                "attempt_id",
                "role_id",
                "worker_identity_id",
                "host_agent_id",
                "harness_kind",
                "harness_config_sha256",
                "runtime_sha256",
                "request_sha256",
                "assignment_mapping_proven",
                "isolation_proven",
                "peer_isolation_proven",
                "credential_isolation_proven",
                "observed_at",
            )
        },
    )
