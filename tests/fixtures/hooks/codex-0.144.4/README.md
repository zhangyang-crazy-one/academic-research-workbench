# Codex 0.144.4 host stdin capture

Captured on 2026-09-25 UTC using the official `@openai/codex@0.144.4` npm package installed under `/tmp/arw-hook-capture.TEfNwP/old-01444`; its executable reported `codex-cli 0.144.4`. A temporary local plugin saved stdin bytes from `SessionStart` and `Stop` during `codex exec --ephemeral --dangerously-bypass-hook-trust --skip-git-repo-check --sandbox read-only` with the prompt `Reply with exactly: capture complete.` The isolated `CODEX_HOME` was under the same temporary root, and CLI output reported both hooks completed.

The fixtures transcribe the captured JSON with a final newline added; the original capture bytes had no final newline. Original SHA-256: `SessionStart` `6d5fda9fb7529c65bfc6a796d348227aeb647e0968db3221a47ab7ecd82e9ae7`; `Stop` `ddf1de5d1d4df0369007997fe3be52a27a31a0f29d1352acb171cdba7fe41dfd`.

A second invocation with the same isolated plugin and host version used a non-ephemeral session and the prompt `Use a subagent to calculate 2 + 2. Wait for its answer, then reply with only that number.` It triggered `SubagentStop`; the captured stdin is in `SubagentStop.json` (original SHA-256 `6682c52c92a29bfe9c8805bcf52e15c4a8354e116f2b8892a309d1cb61ac9acb`). That fixture also has a final newline added.
