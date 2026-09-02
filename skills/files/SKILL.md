---
name: files
description: Bounded read-only access to local research files (list/read/search/outline/context) via the files plane.
---

# files

Local research files are served through the files plane's bounded contract:

```bash
"<installed-plugin-root>/bin/arw" files status --control-root <control-root> --root-id <root-id>
```

Reads expose only `list_files`, `read_file`, `search_files`, `get_outline`,
and `get_context` under the configured root. Never broaden the root from an
agent query.
