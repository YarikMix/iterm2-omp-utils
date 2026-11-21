# Exact saved omp conversation

Recover relevant history locally without printing transcripts. Resolve the
selected omp storage profile through the shared resolver and retain that
provenance; native headers do not encode a storage profile. Confirm an absolute
regular session JSONL, exact header ID and existing absolute cwd. An optional
native title record can precede the session header. Filename/title/recency alone
is not evidence. Ambiguity requires a choice; missing/substituted history blocks,
never starts a fresh conversation. Do not substitute the sender cwd.

```sh
"$launch_python" -m iterm2_utils launch-omp --mode resume --window WINDOW_ID --profile iterm2-utils:omp --cwd ABS_DIR --omp-profile work --resume-file ABS_JSONL --resume-id UUID --json
```

No handoff, prompt, ack, latest/prefix/picker/fork or `--restore`. The native
command is exact `omp --profile work --cwd ABS --resume ABS_JSONL`, including
only preflight-verified preserved literal options. Exact complete executable
argv, or the verified Bun executable plus that exact omp script, is required;
a bare omp/Bun job or extra flags is insufficient. Never evaluate command text.

Before creating, the CLI independently confirms existing candidates with actual
SDK addresses/user variables and exact kernel PID birth. Matching live dialog
returns `already_open`/0 and current window/tab/terminal IDs, zero creates.
Incomplete live identity blocks duplicates. Stale/reused PID records prove
nothing. Only explicit human duplicate authorization permits `--allow-duplicate`.
An independently verified idle shell left after omp exits is not a live dialog.
A stale variable is excluded only with strict same-pane schema, stable shell
and TTY evidence, absence from both censuses, nonmatching recorded birth and no
live binding conflict. Malformed, changing or busy evidence still blocks.
Do not clear variables or remove records. A later exact resume may create once;
the original idle prompt is not repurposed. Existing tabs are not retrofitted.

After command proof, confirm actual main-TUI identity and history. Native
continuations can change files/IDs within the same dialog: validate the chain
back to the source, `continuationOf`/`parentSession` agreement, latest-turn anchors,
profile/cwd and actual file. A fork or arbitrary different ID is not continuation.
The registry updates to the actual file, not the requested filename forever.
Without this evidence: «команда resume запущена, восстановление истории не
подтверждено». Source history alone proves selection, not restoration.
An exit after completed command proof preserves `launched` but cannot supply
missing identity/history. Foreground child image/birth/TTY proof is required
even for full-path argv; SDK root-shell or wrapper text cannot substitute.
No typing, `/status`, Enter, exit, automatic retry or fresh fallback.

## Structural JSON fixtures

Fictional values below are literal JSON (booleans are not strings), not an agent
behavior evaluation or live launch proof. Complete `expected_argv` includes
argv0. The validator checks quoting/fixture shape only; runtime continuation
acceptance is tested using real saved-file fixtures in the isolated test suite.

```json
{
  "commands": [
    {
      "commandLine": "/opt/omp --profile work --cwd '/tmp/example project' --resume /tmp/session.jsonl",
      "expected_argv": ["/opt/omp", "--profile", "work", "--cwd", "/tmp/example project", "--resume", "/tmp/session.jsonl"],
      "matches": true
    },
    {
      "commandLine": "/opt/omp --profile work --cwd '/tmp/example project' --resume /tmp/session.jsonl --continue",
      "expected_argv": ["/opt/omp", "--profile", "work", "--cwd", "/tmp/example project", "--resume", "/tmp/session.jsonl"],
      "matches": false
    }
  ],
  "continuations": [
    {"source_id":"source", "actual_id":"next", "continuationOf":"source", "parentSession":"source", "latest_turn_verified":true, "same_profile_cwd":true, "matches":true},
    {"source_id":"source", "actual_id":"fork", "continuationOf":null, "parentSession":"source", "latest_turn_verified":true, "same_profile_cwd":true, "matches":false}
  ]
}
```
