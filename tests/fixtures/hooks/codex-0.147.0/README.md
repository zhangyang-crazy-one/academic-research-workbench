# Codex 0.147.0 host stdin capture

Captured on 2026-09-25 UTC using the official `@openai/codex@0.147.0` npm package installed under `/tmp/arw-hook-capture.TEfNwP/old-01470`; its executable reported `codex-cli 0.147.0`. A temporary local plugin saved stdin bytes from `SessionStart` and `Stop` during `codex exec --ephemeral --dangerously-bypass-hook-trust --skip-git-repo-check --sandbox read-only` with the prompt `Reply with exactly: capture complete.` The isolated `CODEX_HOME` was under the same temporary root, and CLI output reported both hooks completed.

The fixtures transcribe the captured JSON with a final newline added; the original capture bytes had no final newline. Original SHA-256: `SessionStart` `3903ef4e4b5456a890404c9c80781bb440a8b3c9b5e0ce34ee1a78f88721db1b`; `Stop` `38c399b2afbaf7972545da4d2614582c7fd8f2c56ab5a4bf9c59061b1e84dfe8`.

A second invocation with the same isolated plugin and host version used a non-ephemeral session and the prompt `Use a subagent to calculate 2 + 2. Wait for its answer, then reply with only that number.` It triggered `SubagentStop`; the captured stdin is in `SubagentStop.json` (original SHA-256 `022341b991664b4b452d0cd54a170c941bd814a4deba6375bf67e44b230b5c04`). That fixture also has a final newline added.
