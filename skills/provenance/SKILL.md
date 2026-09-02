---
name: provenance
description: Assertion-level provenance — every accepted graph edge traces to its accepting ledger event.
---

# provenance

Provenance binds every accepted graph assertion to its source artifact and
the canonical ledger event that admitted it. Unbound rows surface as audit
faults, never silent data. Read the run state via:

```bash
"<installed-plugin-root>/bin/arw" status --run-root <run-root> --json
```
