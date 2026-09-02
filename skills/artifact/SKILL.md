---
name: artifact
description: Artifact acceptance and integrity inspection under the control plane's manifest discipline.
---

# artifact

Artifacts are accepted only through the control plane's manifest discipline
(content-addressed, hash-pinned). Inspect acceptance state via:

```bash
"<installed-plugin-root>/bin/arw" status --run-root <run-root> --json
```
