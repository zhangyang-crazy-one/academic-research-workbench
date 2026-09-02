---
name: audit
description: Audit replay and qualification evidence — the append-only ledger is the only authority.
---

# audit

The append-only ledger is the sole canonical record; every projection is
rebuildable from it. Replay and inspect via the stable contracts:

```bash
"<installed-plugin-root>/bin/arw" replay --run-root <run-root>
"<installed-plugin-root>/bin/arw" status --run-root <run-root> --json
```
