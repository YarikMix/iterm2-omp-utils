---
name: iterm2-launch
description: Use when opening or explicitly closing one iTerm2 tab, starting a separate omp task, or opening an exact saved omp conversation on macOS with zsh. Not for internal subagents.
---

# One shell or omp tab; exact tab close

An ordinary or unspecified tab means **shell**, not an agent choice. An explicit
omp request selects new, handoff or exact resume. Create at most one tab per
authorized request. Creation, command, identity, history and task receipt are
separate evidence; none proves task completion.

An internal-subagent request stays internal. An explicitly unsupported Codex/Claude
request is not permission to substitute an external omp tab: report unsupported
consumer without creating anything. Only an explicit separate omp session selects
agent mode; an ordinary tab selects shell without an agent-choice menu.

## Close one explicitly authorized tab

A request to close selects `close-tab`, not launch/setup. Use a verified checkout
and existing Python 3.11+ with the official SDK; preserve absolute `sys.executable`
without resolving virtualenv symlinks. Check `close-tab --help` with that Python.
Missing SDK/API or denied permission blocks; do not install, change permissions,
use GUI/another API, or type into any terminal.

Select the authorized `(window_id, tab_id, session_id)` from a fresh complete
read-only native `iterm2.rpc.async_list_sessions` snapshot, including split-tree,
minimized and buried sessions. If the user supplied exact IDs, keep them exact.
Ambiguous intent requires clarification, not focus/title/recency or a guessed
target. The session ID is the **terminal** ID, not the omp conversation ID.
Require one visible session and no minimized panels in the target tab. Unrelated
splits/hidden sessions are accounted for, never closed. Warn that the selected
tab and its running work will be closed, then invoke once for that authorization:

```sh
"$launch_python" -m iterm2_utils close-tab --window WINDOW_ID --tab TAB_ID --session TERMINAL_ID --json
```

The CLI rechecks the exact tuple before one official native tab-only close with
`force=False`; no profile/settings/agent/Bun/history probes. No window/session/
process close, retry, force, target substitution or cleanup fallback. SDK import,
authorization and inventory are supervised (10s each); close and fresh absence
proof share 30s, and the entire worker is bounded at 60s. Preserve/observe the same
job if a host tool wait ends; never start a second invocation.

Report returned IDs and status in either plain or JSON output:
`closed`/0 requires native `OK` plus a fresh complete snapshot without **both**
target tab ID and terminal ID, including minimized/buried sessions.
`blocked`/2 means no request was sent or native `NOT_FOUND`/`USER_DECLINED` refused
it; refusal is not a successful close. `unknown`/3 includes timeout, failed worker
protocol, missing/non-OK results or retained/moved/buried target IDs after `OK`.
Inspect read-only and report uncertainty; never retry automatically. The SDK
close and snapshots are not atomic against concurrent iTerm2 changes. Copying or
updating this source skill does not install it or authorize any close.

## Prepare

Use a verified checkout/release of https://github.com/YarikMix/iterm2-omp-utils and
read its README. Choose existing Python 3.11+; save its absolute `sys.executable`
without resolving virtualenv symlinks to a different interpreter. Check import
of official `iterm2` and `launch-omp --help` with that same Python. Preserve it
across tool calls; if invocation cwd/PATH changes, recheck there, not in another
environment. Missing SDK/API blocks launch; do not automatically install it.
Each preflight/inventory operation is bounded at 10 seconds, not the whole launch
CLI invocation. Creation plus command verification share 30 seconds; handoff
receipt has a separate 120-second bound after verified command launch.
Use the host's actual permission mechanism; do not demand unsupported sandbox
tool metadata. A denial remains denied: no alternate API/automation path or
permission changes.

The CLI uses complete typed inventories and independent SDK evidence. Target
priority is explicit window, consistent unique parent terminal mapping, then the
sole window in a complete inventory. Multiple/contradictory targets require a
choice; no focus/title/recency inference. Record the selection basis. Recheck
before creation; vanished/changed targets block rather than substitute.

Select an existing ordinary login-shell profile for shell; select the dedicated
`iterm2-utils:omp` profile for omp. Preserve exact name/GUID; no startup commands
or guessed duplicate names. Prerequisite setup is a separate explicitly selected
operation using iterm2-setup, not authorization inferred from a tab request.

## Choose one mode

| User intent | Mode and evidence |
| --- | --- |
| Ordinary tab | `--mode shell`; no agent command, omp/Bun/config/history probe or handoff |
| Empty fresh omp | `--mode new`; no handoff or resume inputs |
| New omp task | `--mode handoff --handoff ABS`; prepare private [handoff/ack](references/handoff.md) |
| Exact saved dialog | `--mode resume --resume-file ABS --resume-id UUID`; follow [resume](references/resume.md) |

Resolve storage with the existing `resolve_omp_profile(home, env, explicit)`:
explicit `--omp-profile` wins over `OMP_PROFILE`, then `PI_PROFILE`; respect
`PI_CONFIG_DIR` and default-only `PI_CODING_AGENT_DIR`. The iTerm profile is not
the omp storage profile. Carry that provenance through history and evidence.

Warn that a tab will appear. Invoke the saved absolute Python once; pass each
value as one argv element (or correctly shell-quote it):

```sh
"$launch_python" -m iterm2_utils launch-omp --mode shell --window WINDOW_ID --profile SHELL_PROFILE --cwd ABS_DIR --json
"$launch_python" -m iterm2_utils launch-omp --mode new --window WINDOW_ID --profile iterm2-utils:omp --cwd ABS_DIR --omp-profile work --json
"$launch_python" -m iterm2_utils launch-omp --mode handoff --window WINDOW_ID --profile iterm2-utils:omp --cwd ABS_DIR --handoff ABS_FILE --omp-profile work --json
"$launch_python" -m iterm2_utils launch-omp --mode resume --window WINDOW_ID --profile iterm2-utils:omp --cwd ABS_DIR --resume-file ABS_JSONL --resume-id UUID --omp-profile work --json
```
Run that single CLI invocation as one supervised asynchronous job when the host's
foreground wait is shorter than its phases. Observe the same job to its structured
result: sequential preflight/inventory time comes before the shared 30-second
create/verify budget and, for handoff, up to another 120 seconds for receipt.
A 10-second tool wait is not a kill deadline; neither 10 nor 30 seconds is a valid
whole-invocation timeout for handoff. If the host cannot preserve/observe that job
for these phases, report the execution limit before creation. Never start a second
invocation because a tool wait ended.


The SDK supplies the full command at creation, never typing into a terminal.
New/handoff use a private final `--config` overlay with `autoResume:false`, leaving
persistent settings/history unchanged. Literal supported wrapper options survive;
opaque wrappers block. Preserve model, endpoint, credentials and approvals.
Version strings are informational, required capabilities are not. Do not add
continue/restore/session-dir/approval flags or weaken protections.
New/handoff/resume leave the same PTY at an interactive zsh prompt in the launch
cwd after omp exits, including nonzero exit. Per-call overrides stay on omp;
login-only scripts are not rerun. Existing tabs and profile settings are not
retrofitted. Explicit shell exit/close-tab still closes normally.
Command proof requires the foreground child's exact supported argv and repeated
independent image/birth/TTY evidence, not wrapper text or equality to root PID.
If live SDK child evidence is unavailable, report uncertainty, never weaken proof.

## Report actual evidence

| Status / exit | Action |
| --- | --- |
| `blocked` / 2 | No creation; report missing prerequisite |
| `created_unverified` or `unknown` / 3 | Keep known IDs/artifacts and uncertainty; observe only that target |
| `launched` / 0 | Exact single-session tab/window/profile/process/full argv verified |
| `already_open` / 0 | Exact live dialog found; report current addresses, zero creates |

JSON `session_id` is the terminal ID, not the omp dialog ID. Report `command`,
`identity`, `history`, `ack` independently. A valid ack means task received, not
completed. Without verified resume history say: «команда resume запущена,
восстановление истории не подтверждено». Do not expose prompts, raw argv,
settings, transcripts or screens. Creation/command proof share 30 seconds; ack
has a separate 120-second bound. Never retry, resend, close/restart a user tab,
kill a process or press Enter after uncertainty. Missing history never falls
back to fresh. Duplicates require explicit human authorization, not convenience.
`launched` records completed command observation, not perpetual liveness.
A later exit does not revoke it or verify missing identity/history. Automated
PTY checks alone are not live iTerm2 acceptance.

Appearance is separate: exact shell TTY and main-TUI identity/foreground proof
are required; inherited IDs or read-only access do not authorize recoloring.
Updating runtime does not retrofit running shells; do not restart them. Fixtures
and structural checks are not live/agent-behavior acceptance.
