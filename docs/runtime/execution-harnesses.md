# Configurable execution harnesses

ARW can select a named harness by assignment, then role, then default. The built-in
kinds are `codex`, `command`, and `api`. Command drivers have no platform or
provider brand whitelist. Applications may register additional factories through
`HarnessRegistry` and `build_configured_dispatch_adapter`; configuration never
imports executable Python. No backend is selected as an automatic fallback.

## Configuration

Create a local JSON configuration and supply it explicitly to dispatch:

```json
{
  "schema_version": "arw.harness-config.v1",
  "default": "native",
  "harnesses": {
    "native": {"kind": "codex"},
    "platform-driver": {
      "kind": "command",
      "command": ["/usr/bin/python3", "/opt/research/driver.py"],
      "runtime_roots": ["/opt/research/driver.py"]
    },
    "configured-api": {
      "kind": "api",
      "protocol": "responses",
      "endpoint": "https://api.example.org/v1/responses",
      "model": "your-explicit-platform-model",
      "api_key_env": "ARW_MODEL_TOKEN",
      "env_file": ".env",
      "max_output_tokens": 4096
    }
  },
  "roles": {"domain_reviewer": "platform-driver"},
  "assignments": {"assignment.example": "configured-api"}
}
```

```bash
./bin/arw orchestration-dispatch --run-root /path/to/run \
  --request /path/to/parent-request.json --harness-config /path/to/harnesses.json
```

`--harness-config-sha256` optionally binds the expected canonical configuration
digest. An unknown assignment selector or unregistered kind blocks dispatch.
Non-Codex tasks must have been prepared as `assignment_injected_subagent`.
The default parent execution policy permits at most two attempts; each API
attempt makes one HTTP request, without transport retries or redirect following.
Application callers can freeze a one-attempt `ExecutionPolicySnapshot` before
preparation. Dispatch cannot change that frozen policy.

Registered factories receive the selected entry, configuration digest, canonical
public configuration snapshot and base path. They must provide `preflight(run_root)`
and the scheduler adapter operations. Dispatch rejects a missing mapping/isolation
proof or a result mode different from the frozen assignment.

Native `codex` retains the existing exact integration-lock and assignment-specific
host-evidence requirements. Its selected assignment set must match that evidence.
Other transports require no Codex installation, version or authentication file.
Codex development/qualification remains `gpt-6.1-sol/high`. Other platforms use
their own explicitly configured models and existing authentication mechanisms.

API keys come only from the named variable or the explicitly selected `.env`;
existing environment values take precedence. The `.env` parser performs no shell
execution or interpolation. Keep `.env` out of commits. Do not place credentials
in endpoint URLs, parameters, argv or input documents. Native Codex OAuth login
is not API authentication. ARW does not read that login for API requests.
Command drivers receive only explicitly selected `credential_env` variables;
provide native platform authentication using a user-owned wrapper and narrowly
selected runtime/authentication inputs. ARW does not force a different platform's
CLI onto an OpenAI model or sign it out.

## External driver contract

Linux command/API workers require usable `bubblewrap`. Each invocation has a
fresh home and task directory. System runtime paths and selected command runtime
roots are read-only; canonical run directories and peer tasks are not mounted.
A real namespace probe runs before the driver. Missing isolation fails closed.
The command runs with a positive environment allowlist and receives one bounded
`arw.harness-request.v1` JSON object on stdin. It includes the frozen assignment,
reconstructed digest-verified preparation context, exact UTF-8 input bytes, and
the nonce/identity-bound `proposal_template`. Binary inputs require an explicit
text extraction upstream. Missing or ambiguous canonical sources block requests.
Command `parameters` are delivered as `harness_parameters` for the user-owned
driver to interpret, including platform-specific model options.

The driver writes one JSON envelope to stdout:

```json
{
  "schema_version": "arw.harness-output.v1",
  "proposal": {"schema_version": "arw.worker-proposal.v1"},
  "artifacts": {"report.txt": "actual UTF-8 report content"}
}
```

The abbreviated proposal above must be completed using `proposal_template` and
the existing worker proposal schema. Its declared artifact inventory, byte counts
and SHA-256 digests must match `artifacts` exactly. Filenames are direct result
children. Drivers cannot write canonical results themselves: the parent validates
identity, nonce, assignment/context/policy hashes, inventory, sizes and paths
before installing bytes. Existing scheduler acceptance and ledger admission run
afterwards. Stdout/stderr are bounded; diagnostics do not retain their content.
Exit `65` means a non-retryable output contract violation, `77` permission or
authentication denial; other nonzero exits use the parent's process-failure policy.

The assembled request is limited to 2 MiB, API wire requests to 4 MiB, HTTP replies
and each captured stream to 8 MiB. Proposal limits also obey the frozen assignment
and scheduler bounds. A deadline first requests local cancellation and then
terminates the local process group. Fresh task directories are removed afterwards.
This does not establish cancellation of remote provider inference or billing.

## Built-in APIs and evidence

`responses` sends stateless Responses requests and reads message `output_text`
blocks. `chat_completions` sends system/user messages and reads one stopped
completion. Both set `store=false`, `stream=false`, explicit model and token bounds.
No tools, conversation IDs, previous response IDs or implicit history are supplied.
The worker executes no response content. Refusal, incomplete output, model tool
requests, redirects and malformed/bounded-output violations fail closed. HTTPS
is required except loopback HTTP or explicitly enabled `allow_http`.
Other API protocols use a command driver or application-registered adapter.

Successful observations bind exact configuration, selected runtime/driver bytes,
request/response digests, logical worker mapping and actual task namespace.
The parent retains public configuration, input/output envelopes and exact API wire
bodies without authentication headers; v2 replay rechecks those retained hashes.
Selected command runtime inventories are bounded to 16,384 entries and 1 GiB.
Their fingerprints include directory topology and internal symlink paths, raw
targets and resolved targets. Dangling, cyclic and escaping links are rejected.
A differing or unavailable runtime at the post-dispatch check makes its result
stale before admission; these checks do not continuously attest the live filesystem.
The logical host identity is stable for the configured worker; namespace instances
remain distinct. `HostIdentityReceiptV2` is platform-neutral and has no fabricated
Codex version. To accept it, the parent requires an exact retained observation
for an already accepted task and known canonical evidence. Panels consume that
accepted receipt; setting a backend name alone proves nothing. These receipts
attest local isolation and stateless request construction. Provider-internal
history, isolation and identity remain unobserved. Original v1 receipts and
their canonical hashes remain readable.

Validation covers actual local command execution and both protocols against a
loopback synthetic server, mixed CLI selection, strict parent acceptance, output
and deadline limits, hostile envelopes, credentials and legacy replay. It does
not qualify a live third-party service or CLI model. Deployment-specific runtime
availability and authentication still require actual host qualification.
