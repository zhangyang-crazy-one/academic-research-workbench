"""Parent admission of resource-checked binary metadata transformations."""

import base64

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService

from .binary import invoke


def sanitize_binary(service, root, relative, *, run_root, request, selection, strip):
    from .inspection import MAX_INPUT_BYTES
    from .service import (
        MAX_BUNDLE_BYTES,
        ArtifactOperationError,
        _publish,
        _read,
        _root_descriptor,
        _verify_root,
    )

    if not selection or len(selection) > 4 or len(set(selection)) != len(selection):
        raise ArtifactOperationError("explicit_metadata_selection_required")
    with _root_descriptor(root) as source_fd, _root_descriptor(run_root) as run_fd:
        original, identity = _read(source_fd, relative, MAX_INPUT_BYTES)
        result = invoke(original, selection, strip)
        if result["status"] != "ok":
            raise ArtifactOperationError(result["reason"])
        derived = base64.b64decode(result.pop("derived_base64"), validate=True)
        stem = "arw-sanitize-" + sha256_hex(request.command_id.encode())
        bundle_path = stem + ".receipt.json"
        export_path = stem + "." + result["format"]
        bundle = {
            "schema_version": "arw.binary-sanitization-bundle.v1",
            "provider_version": "format-presence.v1",
            "policy_version": "selected-metadata.v1",
            "request_identity": request.model_dump(
                mode="json",
                exclude={
                    "artifact_kind",
                    "media_type",
                    "content_path",
                    "content_sha256",
                },
            ),
            "source": {
                "relative_path": relative,
                "sha256": sha256_hex(original),
                "base64": base64.b64encode(original).decode(),
            },
            "derived": {
                "relative_path": export_path,
                "sha256": sha256_hex(derived),
                "base64": base64.b64encode(derived).decode(),
            },
            "authorization": {
                "privacy": True,
                "strip_provenance": strip,
                "selected_metadata": list(selection),
                "actor_id": request.actor_id,
            },
            "verification": result,
        }
        body = canonical_json_bytes(bundle)
        if len(body) > MAX_BUNDLE_BYTES:
            raise ArtifactOperationError("bundle_too_large")
        canonical = request.model_copy(
            update={
                "artifact_kind": "binary-sanitization-receipt",
                "media_type": "application/json",
                "content_path": bundle_path,
                "content_sha256": sha256_hex(body),
            }
        )
        _read(run_fd, "run-manifest.json", 65536)
        current, _ = _read(source_fd, relative, MAX_INPUT_BYTES)
        if current != original:
            raise ArtifactOperationError("unstable_input")
        _verify_root(root, source_fd)
        _verify_root(run_root, run_fd)
        already = service._accepted_retry(run_root, canonical, run_fd)
        _publish(run_fd, bundle_path, body, identity)
        _publish(run_fd, export_path, derived, identity)
        response = {
            "schema_version": "arw.binary-sanitize-result.v1",
            "accepted": False,
            "bundle_path": bundle_path,
            "bundle_sha256": sha256_hex(body),
            "export_path": export_path,
            "source_sha256": sha256_hex(original),
            "derived_sha256": sha256_hex(derived),
            "verification": result,
        }
        if already:
            response.update(accepted=True, status="already_accepted", event_id=already)
        else:
            try:
                outcome = RuntimeCommandService(run_root).accept_artifact(canonical)
            except (RuntimeError, OSError) as error:
                raise ArtifactOperationError(
                    "acceptance_interrupted_retry_required"
                ) from error
            if outcome.accepted:
                response.update(
                    accepted=True, status="accepted", event_id=outcome.event.event_id
                )
            else:
                response.update(status="rejected", reason_code=outcome.rejection.code)
        _verify_root(root, source_fd)
        _verify_root(run_root, run_fd)
        for fd, path, expected, limit in (
            (source_fd, relative, original, MAX_INPUT_BYTES),
            (run_fd, export_path, derived, MAX_INPUT_BYTES),
            (run_fd, bundle_path, body, MAX_BUNDLE_BYTES),
        ):
            actual, _ = _read(fd, path, limit)
            if actual != expected:
                raise ArtifactOperationError("post_acceptance_verification_failed")
        return response
