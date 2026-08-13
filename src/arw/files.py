"""Parent-controlled files administration and immutable generation publication."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import subprocess
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import portalocker
from pydantic import ValidationError

from arw.canonical import canonical_json_bytes, strict_json_loads
from arw.file_contracts import (
    canonical_file_model_bytes,
    canonical_file_model_sha256,
    validate_extraction_registration,
    validate_generation_for_promotion,
)
from arw.file_models import (
    ExtractionRegistration,
    FileAdminReceipt,
    FileContractError,
    FileGenerationManifest,
    FileIdentityManifest,
    FileObservation,
    FileRoot,
    GenerationFile,
    GenerationIntegrityFailure,
    StrictFileModel,
    reconcile_file_identities,
)


class FilesAdminError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class SelectedGeneration(StrictFileModel):
    schema_version: Literal["1.0.0"]
    root_id: str
    generation_id: str
    generation_manifest_sha256: str
    selected_at: str


@dataclass(frozen=True)
class FilesQueryGeneration:
    root: FileRoot
    selected: SelectedGeneration
    identity: FileIdentityManifest
    manifest: FileGenerationManifest
    generation_path: Path
    database_path: Path
    cursor_secret: bytes


@dataclass(frozen=True)
class _ObservedFile:
    observation: FileObservation
    body_bytes: bytes


def _default_id(kind: str) -> str:
    return f"{kind}_{uuid.uuid4().hex}"


def _default_clock() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_atomic(path: Path, value: bytes) -> None:
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _load_model(path: Path, model: type[StrictFileModel]) -> StrictFileModel:
    if path.is_symlink() or not path.is_file():
        raise FilesAdminError("manifest_unsafe", f"missing or unsafe manifest: {path.name}")
    try:
        value = strict_json_loads(path.read_bytes())
        loaded = model.model_validate(value)
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise FilesAdminError("manifest_invalid", f"invalid {path.name}: {error}") from error
    return loaded


def load_selected_generation(control_root: Path, root_id: str) -> SelectedGeneration:
    path = control_root.resolve() / "roots" / root_id / "selected-generation.json"
    return _load_model(path, SelectedGeneration)  # type: ignore[return-value]


class FilesAdminService:
    def __init__(
        self,
        control_root: Path,
        *,
        native_builder: Path | None = None,
        id_factory: Callable[[str], str] = _default_id,
        clock: Callable[[], str] = _default_clock,
    ) -> None:
        self.control_root = control_root.resolve()
        self.native_builder = native_builder.resolve() if native_builder else None
        self._id_factory = id_factory
        self._clock = clock
        if self.control_root.exists() and (
            self.control_root.is_symlink() or not self.control_root.is_dir()
        ):
            raise FilesAdminError("control_root_unsafe", "control root must be a real directory")
        self.control_root.mkdir(parents=True, exist_ok=True)
        (self.control_root / "roots").mkdir(exist_ok=True)

    def root_control_path(self, root_id: str) -> Path:
        if not root_id or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in root_id):
            raise FilesAdminError("root_id_invalid", "root ID is not a stable identifier")
        return self.control_root / "roots" / root_id

    def generation_path(self, root_id: str, generation_id: str) -> Path:
        return self.root_control_path(root_id) / "generations" / generation_id

    def register_root(self, *, root_id: str, root_path: Path, policy_id: str) -> FileRoot:
        if root_path.is_symlink():
            raise FilesAdminError("root_symlink", "registered root cannot be a symlink")
        try:
            resolved = root_path.resolve(strict=True)
        except OSError as error:
            raise FilesAdminError("root_missing", f"registered root is unavailable: {error}") from error
        if not resolved.is_dir():
            raise FilesAdminError("root_not_directory", "registered root must be a directory")
        if (
            self.control_root == resolved
            or self.control_root.is_relative_to(resolved)
            or resolved.is_relative_to(self.control_root)
        ):
            raise FilesAdminError("control_inside_root", "control state cannot be stored under a research root")
        home = Path.home().resolve()
        if resolved in {Path("/"), home}:
            raise FilesAdminError("root_too_broad", "filesystem root and home directory cannot be registered")

        control = self.root_control_path(root_id)
        if control.exists():
            raise FilesAdminError("root_exists", f"root already registered: {root_id}")
        control.mkdir(parents=True)
        for child in ("generations", "receipts", "extractions"):
            (control / child).mkdir()
        cursor_key = control / "cursor.key"
        _write_atomic(cursor_key, os.urandom(32))
        cursor_key.chmod(0o600)
        _fsync_directory(control)
        root = FileRoot(
            schema_version="1.0.0",
            root_id=root_id,
            root_instance_id=self._id_factory("rootinst"),
            policy_id=policy_id,
            canonical_path=str(resolved),
            created_at=self._clock(),
        )
        _write_atomic(control / "root.json", canonical_file_model_bytes(root))
        return root

    def load_root(self, root_id: str) -> FileRoot:
        return _load_model(self.root_control_path(root_id) / "root.json", FileRoot)  # type: ignore[return-value]

    def register_extraction(
        self,
        root_id: str,
        registration: ExtractionRegistration,
        extracted_text: Path,
    ) -> Path:
        self.load_root(root_id)
        if extracted_text.is_symlink() or not extracted_text.is_file():
            raise FilesAdminError("extraction_text_unsafe", "extracted text must be a regular file")
        try:
            body = extracted_text.read_bytes()
            body.decode("utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise FilesAdminError("extraction_text_invalid", f"extracted text is not UTF-8: {error}") from error
        if hashlib.sha256(body).hexdigest() != registration.extracted_text_digest:
            raise FilesAdminError("extraction_digest_mismatch", "extracted text digest does not match registration")
        target = self.root_control_path(root_id) / "extractions" / registration.registration_id
        if target.exists():
            raise FilesAdminError("extraction_exists", "extraction registration is immutable")
        target.mkdir()
        _write_atomic(target / "registration.json", canonical_file_model_bytes(registration))
        _write_atomic(target / "text.txt", body)
        _fsync_directory(target.parent)
        return target

    def status(self, root_id: str) -> dict[str, object]:
        root = self.load_root(root_id)
        try:
            selected = load_selected_generation(self.control_root, root_id)
        except FilesAdminError:
            selected = None
        return {
            "schema_version": "1.0.0",
            "root": root.model_dump(mode="json"),
            "selected_generation": None if selected is None else selected.model_dump(mode="json"),
        }

    def rebuild(
        self,
        root_id: str,
        *,
        extractor_version: str,
        failpoint: Callable[[str], None] | None = None,
    ) -> FileAdminReceipt:
        return self.sync(root_id, extractor_version=extractor_version, failpoint=failpoint)

    repair = rebuild

    def sync(
        self,
        root_id: str,
        *,
        extractor_version: str,
        failpoint: Callable[[str], None] | None = None,
    ) -> FileAdminReceipt:
        control = self.root_control_path(root_id)
        if not control.is_dir() or control.is_symlink():
            raise FilesAdminError("root_unregistered", f"root is not registered: {root_id}")
        with portalocker.Lock(control / ".admin.lock", mode="a", timeout=2.0):
            return self._sync_locked(root_id, extractor_version, failpoint or (lambda _name: None))

    def _sync_locked(
        self,
        root_id: str,
        extractor_version: str,
        failpoint: Callable[[str], None],
    ) -> FileAdminReceipt:
        root = self.load_root(root_id)
        live_root = Path(root.canonical_path)
        if (
            live_root.is_symlink()
            or not live_root.is_dir()
            or live_root.resolve(strict=True) != live_root
        ):
            raise FilesAdminError("root_unsafe", "registered root is no longer a real canonical directory")
        control = self.root_control_path(root_id)
        generation_id = self._id_factory("generation")
        attempt_id = self._id_factory("attempt")
        started_at = self._clock()
        candidate = control / "generations" / f".building-{generation_id}"
        final = self.generation_path(root_id, generation_id)
        pointer_committed = False
        candidate.mkdir()
        previous = self._selected_or_none(root_id)
        previous_manifest = self._identity_or_none(root_id, previous)
        identity_sha: str | None = None
        try:
            observed = list(self._scan_root(Path(root.canonical_path)))
            failpoint("scan_complete")
            previous_records = [] if previous_manifest is None else previous_manifest.records
            identity = reconcile_file_identities(
                previous_records,
                [item.observation for item in observed],
                id_factory=lambda: self._id_factory("file"),
            )
            identity_manifest = FileIdentityManifest(
                schema_version="1.0.0",
                root_id=root.root_id,
                root_instance_id=root.root_instance_id,
                generation_id=generation_id,
                previous_generation_id=None if previous is None else previous.generation_id,
                created_at=started_at,
                records=identity.records,
                deleted_file_ids=identity.deleted_file_ids,
                ambiguous_digests=identity.ambiguous_digests,
            )
            identity_bytes = canonical_file_model_bytes(identity_manifest)
            identity_sha = hashlib.sha256(identity_bytes).hexdigest()
            self._write_closed(candidate / "identity-manifest.json", identity_bytes)

            files, extraction_digests = self._build_projection(
                root_id,
                candidate / "files.sqlite3",
                observed,
                identity_manifest,
                extractor_version,
            )
            failpoint("index_complete")
            self._verify_database(candidate / "files.sqlite3")
            database_sha = hashlib.sha256((candidate / "files.sqlite3").read_bytes()).hexdigest()
            contract_value = os.environ.get("ARW_FILES_CONTRACT_HEADER")
            contract_header = (
                Path(contract_value)
                if contract_value is not None
                else Path(__file__).resolve().parents[2] / "generated/file-contracts.h"
            )
            if contract_header.is_symlink() or not contract_header.is_file():
                raise FilesAdminError(
                    "file_contract_unsafe",
                    "generated file contract header is absent or unsafe",
                )
            contract_sha = hashlib.sha256(contract_header.read_bytes()).hexdigest()
            degraded_count = sum(item.index_state == "degraded" for item in files)
            manifest = FileGenerationManifest(
                schema_version="1.0.0",
                generation_id=generation_id,
                root_id=root.root_id,
                root_instance_id=root.root_instance_id,
                identity_manifest_sha256=identity_sha,
                database_sha256=database_sha,
                contract_sha256=contract_sha,
                created_at=started_at,
                closed_at=self._clock(),
                source_count=len(files),
                indexed_count=sum(item.index_state == "indexed" for item in files),
                degraded_count=degraded_count,
                verdict="degraded" if degraded_count else "complete",
                files=files,
                integrity_failures=[],
                extraction_registration_sha256=extraction_digests,
                tokenizer_id="unicode61-cjk-v1",
                ranking_version="files-rank-v1",
                parser_versions={
                    "bibtex": "deterministic-v1",
                    "latex": "deterministic-v1",
                    "markdown": "deterministic-v1",
                    "plain": "none-v1",
                    "source": "deterministic-v1",
                },
            )
            manifest_bytes = canonical_file_model_bytes(manifest)
            self._write_closed(candidate / "generation-manifest.json", manifest_bytes)
            _fsync_directory(candidate)
            self._invoke_native_builder(Path(root.canonical_path), candidate)
            failpoint("manifest_closed")
            receipt = FileAdminReceipt(
                schema_version="1.0.0",
                receipt_id=self._id_factory("receipt"),
                operation="sync",
                status=manifest.verdict,
                root_id=root_id,
                attempt_id=attempt_id,
                previous_generation_id=None if previous is None else previous.generation_id,
                candidate_generation_id=generation_id,
                selected_generation_id=generation_id,
                generation_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                identity_manifest_sha256=identity_sha,
                degraded_file_ids=[item.file_id for item in files if item.index_state == "degraded"],
                blocking_reasons=[],
                started_at=started_at,
                completed_at=self._clock(),
            )
            validate_generation_for_promotion(manifest, receipt)
            failpoint("before_promote")
            pointer = SelectedGeneration(
                schema_version="1.0.0",
                root_id=root_id,
                generation_id=generation_id,
                generation_manifest_sha256=receipt.generation_manifest_sha256,
                selected_at=self._clock(),
            )
            pointer_bytes = canonical_json_bytes(pointer.model_dump(mode="json"))
            # Stage the pointer before the generation directory is promoted so
            # the pointer rename is the single atomic commit point: a crash or
            # write failure can no longer leave an orphan generation behind
            # while a blocked receipt claims nothing was selected.
            pointer_temporary = control / f".selected-generation.{generation_id}.tmp"
            with pointer_temporary.open("xb") as handle:
                handle.write(pointer_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(candidate, final)
            _fsync_directory(final.parent)
            os.replace(pointer_temporary, control / "selected-generation.json")
            pointer_committed = True
            _fsync_directory(control)
            self._write_receipt(control, receipt)
            return receipt
        except Exception as error:
            candidate_exists = candidate.exists()
            if candidate_exists:
                shutil.rmtree(candidate)
            (control / f".selected-generation.{generation_id}.tmp").unlink(missing_ok=True)
            if not pointer_committed and final.is_dir() and not final.is_symlink():
                shutil.rmtree(final)
            code = error.code if isinstance(error, (FilesAdminError, FileContractError)) else "generation_failed"
            blocked = FileAdminReceipt(
                schema_version="1.0.0",
                receipt_id=self._id_factory("receipt"),
                operation="sync",
                status="blocked",
                root_id=root_id,
                attempt_id=attempt_id,
                previous_generation_id=None if previous is None else previous.generation_id,
                candidate_generation_id=generation_id,
                selected_generation_id=None if previous is None else previous.generation_id,
                generation_manifest_sha256=None,
                identity_manifest_sha256=identity_sha,
                degraded_file_ids=[],
                blocking_reasons=[code],
                started_at=started_at,
                completed_at=self._clock(),
            )
            self._write_receipt(control, blocked)
            if isinstance(error, FilesAdminError):
                raise
            if isinstance(error, FileContractError):
                raise FilesAdminError(error.code, str(error)) from error
            raise FilesAdminError(code, str(error)) from error

    def _selected_or_none(self, root_id: str) -> SelectedGeneration | None:
        try:
            return load_selected_generation(self.control_root, root_id)
        except FilesAdminError as error:
            if error.code == "manifest_unsafe":
                return None
            raise

    def _identity_or_none(
        self, root_id: str, selected: SelectedGeneration | None
    ) -> FileIdentityManifest | None:
        if selected is None:
            return None
        path = self.generation_path(root_id, selected.generation_id) / "identity-manifest.json"
        return _load_model(path, FileIdentityManifest)  # type: ignore[return-value]

    def _write_receipt(self, control: Path, receipt: FileAdminReceipt) -> None:
        _write_atomic(
            control / "receipts" / f"{receipt.receipt_id}.json",
            canonical_file_model_bytes(receipt),
        )

    @staticmethod
    def _write_closed(path: Path, value: bytes) -> None:
        with path.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())

    def _scan_root(self, root: Path) -> Iterator[_ObservedFile]:
        ignore_prefixes = self._ignore_prefixes(root)
        sensitive = {".git", ".ssh", ".env", "credential", "credentials", "private", "secret", "secrets"}
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        for directory, directories, filenames, descriptor in os.fwalk(
            root, topdown=True, follow_symlinks=False
        ):
            directory_path = Path(directory)
            relative_directory = directory_path.relative_to(root).as_posix()
            prefix = "" if relative_directory == "." else f"{relative_directory}/"
            kept_directories: list[str] = []
            for name in sorted(directories):
                relative = f"{prefix}{name}"
                try:
                    metadata = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                except OSError:
                    continue
                if (
                    stat.S_ISDIR(metadata.st_mode)
                    and name.lower() not in sensitive
                    and not self._ignored(relative + "/", ignore_prefixes)
                ):
                    kept_directories.append(name)
            directories[:] = kept_directories
            for name in sorted(filenames):
                relative = f"{prefix}{name}"
                if name == ".arwignore" or name.lower() in sensitive or self._ignored(relative, ignore_prefixes):
                    continue
                try:
                    before = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                    if not stat.S_ISREG(before.st_mode):
                        continue
                    file_descriptor = os.open(name, os.O_RDONLY | nofollow, dir_fd=descriptor)
                    try:
                        opened = os.fstat(file_descriptor)
                        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                            raise FilesAdminError("descriptor_changed", f"file changed before open: {relative}")
                        chunks: list[bytes] = []
                        while True:
                            chunk = os.read(file_descriptor, 1 << 20)
                            if not chunk:
                                break
                            chunks.append(chunk)
                        after = os.fstat(file_descriptor)
                    finally:
                        os.close(file_descriptor)
                except OSError as error:
                    raise FilesAdminError("descriptor_changed", f"cannot safely read {relative}: {error}") from error
                if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
                    after.st_dev,
                    after.st_ino,
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise FilesAdminError("descriptor_changed", f"file changed during read: {relative}")
                body = b"".join(chunks)
                yield _ObservedFile(
                    observation=FileObservation(
                        relative_path=relative,
                        file_type=self._file_type(relative),
                        size_bytes=len(body),
                        digest=hashlib.sha256(body).hexdigest(),
                        descriptor_fingerprint=f"{opened.st_dev}:{opened.st_ino}",
                    ),
                    body_bytes=body,
                )

    @staticmethod
    def _ignore_prefixes(root: Path) -> tuple[str, ...]:
        path = root / ".arwignore"
        if path.is_symlink() or not path.is_file():
            return ()
        prefixes = []
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if not value or value.startswith("#") or value.startswith("/") or ".." in PurePosixPath(value).parts:
                continue
            prefixes.append(value)
        return tuple(sorted(set(prefixes)))

    @staticmethod
    def _ignored(relative: str, prefixes: tuple[str, ...]) -> bool:
        return any(relative == item.rstrip("/") or relative.startswith(item.rstrip("/") + "/") for item in prefixes)

    @staticmethod
    def _file_type(relative: str) -> str:
        suffix = PurePosixPath(relative).suffix.lower()
        if suffix in {".md", ".markdown"}:
            return "markdown"
        if suffix in {".tex", ".ltx"}:
            return "latex"
        if suffix == ".bib":
            return "bibtex"
        if suffix == ".pdf":
            return "pdf"
        if suffix in {".py", ".c", ".h", ".cpp", ".rs", ".go", ".js", ".ts", ".java"}:
            return "source"
        if suffix in {".txt", ".rst", ".csv", ".json", ".yaml", ".yml"}:
            return "text"
        return "binary"

    def _load_extractions(self, root_id: str) -> dict[str, tuple[ExtractionRegistration, bytes, str]]:
        result: dict[str, tuple[ExtractionRegistration, bytes, str]] = {}
        root = self.root_control_path(root_id) / "extractions"
        for directory in sorted(root.iterdir()):
            if directory.is_symlink() or not directory.is_dir():
                raise FilesAdminError("extraction_store_unsafe", "extraction store contains an unsafe entry")
            registration = _load_model(directory / "registration.json", ExtractionRegistration)
            assert isinstance(registration, ExtractionRegistration)
            text = (directory / "text.txt").read_bytes()
            digest = hashlib.sha256(canonical_file_model_bytes(registration)).hexdigest()
            result[registration.source_file_id] = (registration, text, digest)
        return result

    def _build_projection(
        self,
        root_id: str,
        database: Path,
        observed: list[_ObservedFile],
        identity: FileIdentityManifest,
        extractor_version: str,
    ) -> tuple[list[GenerationFile], list[str]]:
        observed_by_path = {item.observation.relative_path: item for item in observed}
        extractions = self._load_extractions(root_id)
        files: list[GenerationFile] = []
        eligible_extractions: set[str] = set()
        connection = sqlite3.connect(database)
        try:
            connection.executescript(
                """
                PRAGMA journal_mode=DELETE;
                PRAGMA synchronous=FULL;
                CREATE TABLE files (
                  file_id TEXT PRIMARY KEY,
                  relative_path TEXT NOT NULL UNIQUE,
                  file_type TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL,
                  source_digest TEXT NOT NULL,
                  index_state TEXT NOT NULL,
                  degraded_reason TEXT,
                  extraction_registration_sha256 TEXT,
                  body TEXT
                );
                CREATE VIRTUAL TABLE files_fts USING fts5(
                  file_id UNINDEXED, relative_path UNINDEXED, body, tokenize='unicode61'
                );
                """
            )
            for record in identity.records:
                item = observed_by_path[record.relative_path]
                body: str | None = None
                state = "indexed"
                reason: str | None = None
                extraction_sha: str | None = None
                if record.file_type == "pdf":
                    registered = extractions.get(record.file_id)
                    if registered is None:
                        state, reason = "degraded", "extraction_missing"
                    else:
                        registration, text, extraction_sha = registered
                        try:
                            validate_extraction_registration(
                                registration,
                                source_digest=record.digest,
                                expected_extractor_version=extractor_version,
                            )
                            if hashlib.sha256(text).hexdigest() != registration.extracted_text_digest:
                                raise FileContractError("extraction_digest_mismatch", "registered text digest changed")
                            body = text.decode("utf-8")
                            eligible_extractions.add(extraction_sha)
                        except (FileContractError, UnicodeDecodeError) as error:
                            state = "degraded"
                            reason = error.code if isinstance(error, FileContractError) else "invalid_utf8"
                            extraction_sha = None
                elif record.file_type == "binary":
                    state, reason = "degraded", "unsupported_format"
                else:
                    try:
                        body = item.body_bytes.decode("utf-8")
                    except UnicodeDecodeError:
                        state, reason = "degraded", "invalid_utf8"
                generation_file = GenerationFile(
                    file_id=record.file_id,
                    relative_path=record.relative_path,
                    file_type=record.file_type,
                    size_bytes=record.size_bytes,
                    source_digest=record.digest,
                    index_state=state,
                    degraded_reason=reason,
                    extraction_registration_sha256=extraction_sha,
                )
                files.append(generation_file)
                connection.execute(
                    "INSERT INTO files VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        record.file_id,
                        record.relative_path,
                        record.file_type,
                        record.size_bytes,
                        record.digest,
                        state,
                        reason,
                        extraction_sha,
                        body,
                    ),
                )
                if body is not None:
                    connection.execute(
                        "INSERT INTO files_fts(file_id, relative_path, body) VALUES (?, ?, ?)",
                        (record.file_id, record.relative_path, body),
                    )
            connection.commit()
        finally:
            connection.close()
        with database.open("rb") as handle:
            os.fsync(handle.fileno())
        return sorted(files, key=lambda item: item.relative_path), sorted(eligible_extractions)

    @staticmethod
    def _verify_database(database: Path) -> None:
        connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
        try:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise FilesAdminError("database_integrity_failed", "SQLite integrity check failed")
        finally:
            connection.close()

    def _invoke_native_builder(self, root: Path, candidate: Path) -> None:
        if self.native_builder is None:
            return
        if self.native_builder.is_symlink() or not self.native_builder.is_file():
            raise FilesAdminError("native_builder_missing", "native generation validator is unavailable")
        completed = subprocess.run(
            [
                str(self.native_builder),
                "files-build",
                "--root",
                str(root),
                "--candidate",
                str(candidate),
            ],
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise FilesAdminError(
                "native_builder_failed",
                completed.stderr.strip() or "native generation validator rejected candidate",
            )
        try:
            result = json.loads(completed.stdout)
        except json.JSONDecodeError as error:
            raise FilesAdminError("native_builder_invalid", "native builder emitted invalid JSON") from error
        if result.get("status") != "ok" or result.get("profile") != "files-build":
            raise FilesAdminError("native_builder_invalid", "native builder did not attest files-build")


def load_query_generation(control_root: Path, root_id: str) -> FilesQueryGeneration:
    """Load and integrity-check one immutable generation without creating state."""

    if not root_id or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in root_id
    ):
        raise FilesAdminError("root_id_invalid", "root ID is not a stable identifier")
    if control_root.is_symlink() or not control_root.is_dir():
        raise FilesAdminError("control_root_unsafe", "control root must be an existing real directory")
    resolved_control = control_root.resolve(strict=True)
    root_control = resolved_control / "roots" / root_id
    if root_control.is_symlink() or not root_control.is_dir():
        raise FilesAdminError("root_unregistered", f"root is not registered: {root_id}")

    root = _load_model(root_control / "root.json", FileRoot)
    try:
        selected = _load_model(root_control / "selected-generation.json", SelectedGeneration)
    except FilesAdminError as error:
        if error.code == "manifest_unsafe":
            raise FilesAdminError(
                "selected_generation_missing", "root has no selected generation"
            ) from error
        raise
    assert isinstance(root, FileRoot)
    assert isinstance(selected, SelectedGeneration)
    if root.root_id != root_id or selected.root_id != root_id:
        raise FilesAdminError("root_binding_mismatch", "root and selected generation disagree")

    live_root = Path(root.canonical_path)
    if live_root.is_symlink() or not live_root.is_dir() or live_root.resolve(strict=True) != live_root:
        raise FilesAdminError("root_unsafe", "registered root is no longer a real canonical directory")
    generation = root_control / "generations" / selected.generation_id
    if generation.is_symlink() or not generation.is_dir():
        raise FilesAdminError("selected_generation_unsafe", "selected generation is absent or unsafe")
    identity = _load_model(generation / "identity-manifest.json", FileIdentityManifest)
    manifest = _load_model(generation / "generation-manifest.json", FileGenerationManifest)
    assert isinstance(identity, FileIdentityManifest)
    assert isinstance(manifest, FileGenerationManifest)
    if (
        manifest.root_id != root_id
        or manifest.root_instance_id != root.root_instance_id
        or identity.root_id != root_id
        or identity.root_instance_id != root.root_instance_id
        or identity.generation_id != selected.generation_id
        or manifest.generation_id != selected.generation_id
    ):
        raise FilesAdminError("generation_binding_mismatch", "selected generation bindings disagree")
    if canonical_file_model_sha256(manifest) != selected.generation_manifest_sha256:
        raise FilesAdminError("generation_manifest_digest_mismatch", "selected manifest digest changed")
    if canonical_file_model_sha256(identity) != manifest.identity_manifest_sha256:
        raise FilesAdminError("identity_manifest_digest_mismatch", "identity manifest digest changed")

    database = generation / "files.sqlite3"
    if database.is_symlink() or not database.is_file():
        raise FilesAdminError("database_unsafe", "selected database is absent or unsafe")
    if hashlib.sha256(database.read_bytes()).hexdigest() != manifest.database_sha256:
        raise FilesAdminError("database_digest_mismatch", "selected database digest changed")
    FilesAdminService._verify_database(database)

    key_path = root_control / "cursor.key"
    if key_path.is_symlink() or not key_path.is_file():
        raise FilesAdminError("cursor_key_unsafe", "cursor key is absent or unsafe")
    cursor_secret = key_path.read_bytes()
    if len(cursor_secret) != 32:
        raise FilesAdminError("cursor_key_invalid", "cursor key must contain exactly 32 bytes")
    return FilesQueryGeneration(
        root=root,
        selected=selected,
        identity=identity,
        manifest=manifest,
        generation_path=generation,
        database_path=database,
        cursor_secret=cursor_secret,
    )
