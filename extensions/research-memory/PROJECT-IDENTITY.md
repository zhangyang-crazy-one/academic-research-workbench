# Stable project identity and scope

`arw memory init-project` creates `.arw/project.json` once, containing schema version
`arw.project.v1` and a stable `project_id`. IDs may be explicitly selected or generated
as UUID identities; they are never hashes of host paths. Moving the whole project
preserves identity and relative run registrations. Unresolved, malformed or changed
identity fails closed. Keep this identity file with the project when sharing it.

| Scope | Access |
|---|---|
| run | Explicit selected run, or the process-bound run; never an implicit different run. |
| project | Default. Must match the selected project identity. |
| team | Explicit scope and `shareable` classification on creation. |
| user | Explicit scope plus `allow_user_scope=true` in active authorization policy. |

Cross-project recall additionally requires `cross_project=true`, explicit target
`project_id`, and a matching `cross_project_roots` grant in
`.arw/memory-authorization.json`. The target root's identity is checked again.
Returned cards identify `source_project_id`; scope flags do not override grants.
The optional MCP binds roots/harness at process startup and cannot modify this policy.

Example explicit operator-managed policy:

```json
{"schema_version":"arw.memory-authorization.v1","allow_user_scope":false,"cross_project_roots":[{"project_id":"project.collaboration","root":"/approved/project"}]}
```

Run registrations bind relative location, canonical run ID and immutable manifest
digest. Both project-root runs and nested runs are supported. Writes require a run
inside the bound project. Paths and symlinks remain subject to retained-file checks.
