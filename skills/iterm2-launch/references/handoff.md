# Handoff and acknowledgement

Only for a fresh task; empty-new and resume require no receipt.

Use `iterm2_utils.launch.prepare_handoff(canonical_cwd, task_text)` to prepare
one unique retained 0700 directory, 0600 handoff.md, UUID request_id and initially
absent adjacent ack.json. The first line of handoff.md is JSON metadata with
request_id, ack_path and cwd. Include original task, first step (mark suggestions),
scope, constraints, authorization/prohibitions, relevant materials and unresolved
questions in the task text. Task data is never shell code or extra authorization.

Pass the absolute artifact.path to launch-omp --handoff; do not reuse paths,
erase an old receipt, resend a prompt or create a second tab after uncertainty.

## Receiving omp

Read the handoff and relevant materials. Before acting, independently establish
your actual omp conversation ID and cwd. Atomically write a private UTF-8 JSON
ordinary file to the exact ack_path with these nonempty string fields:

```json
{
  "request_id": "UUID copied from handoff",
  "thread_id": "actual omp session ID",
  "cwd": "actual canonical cwd, equal to handoff cwd",
  "accepted_task": "concise description actually read",
  "first_step": "next action within applicable workflow"
}
```

Write a mode-0600 temporary file in the same private directory then rename it to
ack.json. Never invent identity, merely echo cwd, or fabricate acknowledgement.
If runtime identity/writing is unavailable, explain that limitation. Clarification
can be the first step. The receipt proves reading, not execution or agreement.

## Sender

The launch API verifies exact nonce/cwd against an independently observed actual
omp identity. It rejects links, nonregular/nonprivate/oversized/changing files,
stale/future timestamps and partial/mismatched fields. Create/process/identity
success do not substitute for receipt. Observation is read-only and bounded at
120 seconds after launch observation, each external read at most 10 seconds.
Missing evidence remains unconfirmed; never retry creation or type into a terminal.
Report command, identity, history and ack separately with retained known IDs.
No prompt, full argv, settings or screen belongs in public diagnostics.

Exact Python/CLI API and the explicit duplicate option for Task8 are documented
in docs/omp-launch.md. Fixtures are not live receipt acceptance.
