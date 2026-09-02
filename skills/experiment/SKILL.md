---
name: experiment
description: Experiment planning/provenance and the opt-in STORM deep-research pipeline (user consent required).
---

# experiment

Experiment provenance is recorded through the control plane's ledger; the
opt-in STORM survey pipeline is invoked only on explicit user request:

```bash
"<installed-plugin-root>/bin/arw" storm --topic "<topic>" --output-dir <dir>
```

STORM writes a draft plus an `arw-storm-receipt.json` audit receipt; its output
is pre-writing research material, never canonical experiment evidence.
