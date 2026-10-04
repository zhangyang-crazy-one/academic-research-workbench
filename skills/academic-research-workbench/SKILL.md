---
name: academic-research-workbench
description: "ARW control-plane operations for an existing research run: run status, bounded local files/search, evidence and artifact admission, provenance/graph, audit replay, writing record and gates. Use for 审计台账、证据接纳、文件检索、研究图谱、运行状态、受控改写记录. For research methodology use academic-research-suite; for post-manuscript handoff use submission."
---

# Academic Research Workbench

Resolve the plugin root as the parent of this installed `skills/` directory, then run the
installed launcher from that root:

```bash
"<installed-plugin-root>/bin/arw" route --core --json
```

Return the command's JSON result unchanged. Use `core_integrity` and the
capability/provider records as selected, nonexhaustive guidance for local
research, manuscript, file, and audit operations. A missing route row does not
mean the command has no provider; the command resolves its own provider and
configuration. Read each record's `reason_code`: `module_present` reports package
presence only; `not_evaluated` may mean import, operation configuration, or
core integrity has not passed. Neither grants file access. An editable
checkout reports `UNVERIFIED` and cannot claim staged integrity. Do not infer
permission to use a missing provider or execute experiments from this route.

For the Codex execution adapter only, run `route --json` and require its strict
integration qualification before dispatch. That legacy route remains bound to
the exact Codex host and canary; it does not gate local core operations.

For concrete control-plane commands and preserved capability routes, read
[control-plane capabilities](references/control-plane-capabilities.md). For
writing proposals and source-bound review, read
[writing revisions](references/writing-revisions.md). An external database
lookup may be proposed only through an explicit ARW assignment; first read
[database lookup advisory](references/database-lookup-advisory.md).

For an ARW paper project, register and select the project narrative before
outlining or drafting, then load the current version on each handoff or resume.
Read the bundled ARS adapter file at
`skills/academic-research-suite/codex/references/project_narrative_protocol.md`
for selection, status, handoff, and structure rules.
General non-paper tasks do not need a paper narrative.

The modified Academic Research Suite is bundled at
`<installed-plugin-root>/skills/academic-research-suite/`; use that exact router and
its workflow files for ARS tasks. Do not substitute an external ARS installation.

This installed skill is the canonical model-invocable route. Plugin-native custom-agent
distribution is unproven; for qualified Codex delegation, use native Codex subagents
with immutable assignment-injected ARS role instructions. The companion hook is
observational only, may be skipped until trusted, and is never an authorization or
canonical-state boundary. Only future explicit control-plane mutation commands may write
accepted state; `route` is read-only.

For local research files, the installed MCP receives one parent-supplied root
capability and exposes only `list_files`, `read_file`, `search_files`,
`get_outline`, and `get_context`. Treat stale metadata as a request for an
explicit parent sync; never infer permission to crawl, extract, rebuild, repair,
or broaden the configured root from an agent query.

## Optional deep research (STORM)

When the user explicitly asks for an experiment-planning pass, deep thinking, or a
survey-style literature synthesis, you may offer the opt-in STORM pipeline:

Choose the model provider explicitly. Set its key in the named environment
variable before running STORM; the CLI reads the key through `--api-key-env NAME`.
The model ID must match the provider (`openai/` for OpenAI or an
OpenAI-compatible endpoint, `gemini/` for Gemini). For example:

```bash
"<installed-plugin-root>/bin/arw" storm --topic "My topic" --output-dir ./build/storm --provider openai --model openai/YOUR_MODEL --api-key-env OPENAI_API_KEY
"<installed-plugin-root>/bin/arw" storm --topic "My topic" --output-dir ./build/storm --provider gemini --model gemini/YOUR_MODEL --api-key-env GEMINI_API_KEY
"<installed-plugin-root>/bin/arw" storm --topic "My topic" --output-dir ./build/storm --provider openai-compatible --model openai/MODEL --api-base https://models.example.test/v1 --api-key-env COMPATIBLE_API_KEY
```

Use `--api-base` only with `--provider openai-compatible`, and choose a public
HTTPS endpoint. The current agent's authentication is not reused. Retrieval
defaults to Tavily and separately needs `TAVILY_API_KEY`; use
`--retriever duckduckgo` for the keyless retrieval fallback.

STORM performs retrieval-grounded multi-perspective research and writes a
citation-backed draft article plus an `arw-storm-receipt.json` audit receipt into
`<output-dir>/<topic>/`. It is never part of the default route and does not touch
the run ledger. Run it only when the user consents; treat its output as
pre-writing research material, never as canonical experiment evidence.
