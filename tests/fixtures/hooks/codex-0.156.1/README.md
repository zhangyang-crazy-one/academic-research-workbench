# Codex 0.156.1 host stdin capture

Captured on 2026-09-25 UTC from `codex-cli 0.156.1` using a temporary local plugin with `SessionStart` and `Stop` hooks. The isolated invocation used `codex exec --ephemeral --dangerously-bypass-hook-trust --skip-git-repo-check --sandbox read-only -m gpt-6-luna` and the prompt `Reply with exactly: capture complete.` Its `CODEX_HOME` was under `/tmp/arw-hook-capture.TEfNwP`; no user Codex configuration was changed. The test hook saved stdin bytes before returning `{"continue":true}`. The CLI output reported both hooks completed.

These fixtures transcribe the captured JSON with a final newline added. The original capture bytes had no final newline and the following SHA-256 digests:

| Event | Original stdin SHA-256 |
| --- | --- |
| SessionStart | `f48e58d15ed987bc6c955c035e568135ddb384209e419c900ff5fde1232c33ec` |
| Stop | `a414e152ead24ce09b65d3485b0a47b782fdee89341371abd9eea72b83bd4653` |
| SubagentStop | `96067957c847979f2b4d8f715cef764e7b793863060fa47953d634244295c066` |

A second invocation with the same isolated plugin and host version used a non-ephemeral session and the prompt `Use a subagent to calculate 2 + 2. Wait for its answer, then reply with only that number.` It triggered `SubagentStop`; the captured stdin is in `SubagentStop.json` (original SHA-256 `96067957c847979f2b4d8f715cef764e7b793863060fa47953d634244295c066`). That fixture also has a final newline added. Older-version `SubagentStop` host captures remain a separate evidence target.
