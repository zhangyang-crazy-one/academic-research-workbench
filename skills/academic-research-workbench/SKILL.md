---
name: academic-research-workbench
description: "ARW control-plane operations for an existing research run: run status, bounded local files/search, evidence and artifact admission, provenance/graph, audit replay, writing record and gates. Use for 审计台账、证据接纳、文件检索、研究图谱、运行状态、受控改写记录. For research methodology use academic-research-suite; for post-manuscript handoff use submission."
---

# Academic Research Workbench

Resolve the plugin root as the parent of this installed `skills/` directory, then run the
installed launcher from that root:

```bash
"<installed-plugin-root>/bin/arw" route --json
```

Return the command's JSON result unchanged. It must declare the ARS workflow family,
execution mode, source adapter version, and disabled experiment status. Do not infer a
different family, mode, domain ontology, or experiment permission outside that result.

For concrete control-plane commands and preserved capability routes, read
[control-plane capabilities](references/control-plane-capabilities.md). For
writing proposals and source-bound review, read
[writing revisions](references/writing-revisions.md). An external database
lookup may be proposed only through an explicit ARW assignment; first read
[database lookup advisory](references/database-lookup-advisory.md).

The modified Academic Research Suite is bundled at
`<installed-plugin-root>/skills/academic-research-suite/`; use that exact router and
its workflow files for ARS tasks. Do not substitute an external ARS installation.

This installed skill is the canonical model-invocable route. Plugin-native custom-agent
distribution is unproven; when delegation is later requested, use native Codex subagents
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
