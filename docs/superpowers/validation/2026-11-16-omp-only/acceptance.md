# Omp-only acceptance evidence — 2026-11-17

## Scope

The first matrix records Task10's initial isolated execution; no personal
settings/auth/API/GUI were accessed during that tranche. Later sections distinguish
the reviewed source correction from separately authorized personal preview and
partial migration. Fixtures never establish native/UI acceptance.

Every offline process began with an allowlisted private HOME, configuration,
agent, XDG, ZDOTDIR, temporary/package state and terminal environment before
imports. Native OS/preferences boundaries used fixture adapters; HOME was not
assumed to virtualize macOS preferences. Existing Python 3.13.18, Bun 1.4.4 and
system zsh were used without package installation. Private full logs and exact
commands remain in the ignored plan workspace, not the release.

## Observed matrix

| Check | Observed result | Limit |
| --- | --- | --- |
| `python3 -m unittest discover -v` | Initial 514 tests: 12 failures, 2 errors, 1 skip | First integrated RED, not a green full-suite claim |
| Affected Python modules after corrections | 252 tests, exit 0 | Covers every direct initial failure/error |
| `python3 -m unittest tests.test_export -v` after corrections | 12 tests, exit 0 | Includes extracted CLI/workflow/skill/lifecycle/payload subprocess tests |
| Isolated Bun identity/config suites | 16 pass, 105 assertions, exit 0 | Main identity and YAML protocol fixtures, not actual omp TUI |
| Controlled `zsh -f tests/test_appearance_shell.zsh` | Initial 2 failures/1 error; corrected 25 pass, exit 0 | Real private PTYs/prompt hooks with fake executables/SDK |
| Skill/source/export validators | Exit 0; 3 bundles, 96 pinned sources, 209 allowlisted files | Structural/provenance evidence only |
| Private Darwin self/PTY proof | Exit 0 | Actual shared kernel birth/executable helpers, foreground from detached helper, stopped-live birth, shell foreground return; no personal terminal |
| Temporary-config actual CLI smoke | Exit 0 harness | Bootstrap/plan/install/doctor/uninstall, migration preview/apply and all launch modes through native adapters; install/doctor correctly return 3 for pending native status |
| Public export | Build/checksum and extraction tests exit 0 | All three bootstraps, actual shell SDK child/one create/login shell, installed parser after extraction removal; no real SDK/API |

The skipped Python assertion was
`test_distinct_case_sensitive_directories_remain_distinct`: its fixture volume
is case-insensitive. No assertion was disabled or narrowed to obtain a pass.
The full discovery was not repeated unchanged: only affected checks were rerun.

## Confirmed causes and corrections

- Darwin `select.kqueue` has no context-manager protocol. Explicit `closing`
  keeps the actual command-lifetime observer alive and closes its queue.
- Changed owned values survived uninstall, but selected feature policy was
  removed from its receipt. Unresolved owners now retain selection/policy and
  pending evidence so cleanup remains retryable.
- Unchanged update regenerated an already-reconciled UI step. No-op edits now
  preserve that evidence, while changed edits may require verification again.
- A shared profile builder's early failure was tagged to only one consumer and
  filtered out by another checkpoint. Every affected consumer gets the failure.
- Stale fixture interfaces included removed Paths fields, `_empty` context,
  shell PID arguments, SDK transactions/monitors/baseline snapshots, native
  selected-profile discovery and canonical resolved receipt paths. Fixtures now
  exercise those actual interfaces rather than old wiring expectations.
- The suspend/return fixture reused an asyncio queue across independent loops;
  each synthetic invocation now owns its event queue, like the real SDK runtime.
- Prompt fixtures used a tty line editor with captured output and did not drain
  terminal output. They now run real prompt hooks without ZLE and consume their
  private PTY output; asynchronous return assertions wait for their owned helper.

Controller-observed tool-free launch actor cases L1a/L1b/L2 incorrectly applied
10 seconds to the entire CLI invocation. The launch skill now scopes 10 seconds
to each preflight/inventory operation, 30 seconds jointly to creation/command
verification, and a separate 120 seconds to handoff receipt. It explains observing
one supervised asynchronous invocation without premature cancellation or retry.
Controller completed a fresh tool-free targeted replay of L1a/L1b/L2 after that
correction; all three proposals were manually acceptable. L1a/L1b retained
correct shell/target/no-agent behavior and omitted the erroneous whole-call
10-second limit, but specified no outer timeout metadata; they do not independently
prove it. L2 explicitly chose one supervised asynchronous job, a separate
120-second receipt budget after command observation, and no second invocation
when a short tool wait ends.

Campaign evidence is **18 baseline proposals: 15 acceptable, 3 budget-instruction
failures; actual instruction correction; 3 acceptable targeted replay proposals**.
The other 15 were not rerun unchanged; this is not a fresh all-18 pass. Only the
launch SKILL was refreshed (read-text SHA256
`26925fe1ee59cf6e7b36177690bda422130953515ab8dcff46f103f3042f4103`);
references were unchanged. No actor executed CLI, SDK or UI operations. Decision
replay does not establish runtime timing, statistical reliability or live acceptance.

## Final source correction and scoped review

Native whole-branch workers completed all five finder dimensions and twenty
skeptic nodes. Earlier deadline-limited output remains historical, not silently
credited with missing coverage. Confirmed issues from both execution generations
were frozen together before the single omnibus source correction.

Correction commit: `245b2eaedc2a3429bae34a07b0694f94264c2f22`.
Its one scoped re-review returned all eighteen source/test obligations addressed
and no fix-introduced breakage. Source-boundary questions are not live UI proof.

| Covering evidence after that correction | Observed result | Limit |
| --- | --- | --- |
| Affected Python tranche | 332 cases executed; initial 4 failures/3 errors across four fixture methods, all repaired methods subsequently pass | Distributed affected-case evidence, not one final all-green tranche; Linux not executed |
| Bun identity/config | Existing 16 pass; new installed default-entrypoint/private-PTY case passes after consumer calibration | 17 cases covered; no actual iTerm receiver/UI proof |
| Source/export/skill validators | All exit 0 | Structural/provenance only |

The default-entrypoint test exercises actual private own-PTY OSC publication,
device mismatch refusal and failed-publication cleanup. No personal terminal is
used. No permanent identity/process source change was needed for that proof.

## Authorized personal migration

The user separately authorized scoped read-only preview and then the displayed
migration/three-skill update. Auth files, personal dialog content and screens were
not read. Diagnostic versions observed: omp18.20.3, Bun1.4.4, iTerm2 3.7.7,
selected Python3.13.7 with official SDK2.23; no exact agent-version gate.

The initial apply converted the four receipt scopes and performed exact owned
cleanup, but left the old `current` and runtime in place; native feature
checkpoints were blocked. The later correction `c9cd416508` split the session
inventory from status-bar validation. Its focused review had no findings.

All three omp-only skill updates completed. Mixed historical launch ownership
initially left an empty directory that the bootstrap correctly refused as
foreign. Only the two verified-empty package directories were removed with
atomic nonrecursive `rmdir`, then the normal bootstrap succeeded. All nine
installed bundle files match the reviewed source byte-for-byte; extra/foreign
files were not overwritten or adopted.

After the user closed the last iTerm2 window, the SDK confirmed zero sessions.
A fresh preview identified 378 owned files and the historical `current` symlink.
The separately approved apply completed all three feature checkpoints, with no
conflicts. Readback confirmed the old files were gone, `current` pointed to the
new runtime, and no `current-omp` or pending transaction journal existed.
The default omp profile stores `terminal.programStatus=true`,
`completion.notify='on'` and `error.notify='off'`. Six disabled external records
were retained. Exit 3 means native verification remains pending, not that the
settings were rejected. The migration itself created no tabs and performed no
model turns or clipboard operations. Private evidence stays in the ignored plan
workspace.

## Live launch correction

iTerm2 reports abbreviated `argv[0]` for the tested `zsh` and `omp` jobs.
The verifier now accepts that form only with exact remaining argv and positive
kernel executable/foreground evidence bound to the job PID and session TTY.
After the scoped review, one fresh `Default` shell tab and one fresh
`iterm2-utils:omp` tab each returned `launched` (exit 0) with verified command;
the empty omp tab also returned verified live identity. Both tests used an
explicit window. No prompts, history restore, or clipboard operations.

A separately authorized fresh handoff used the default omp storage profile.
The launcher verified the command and live identity and accepted the private
receipt from that identity (`ack=received`). The only task was to read and
acknowledge the handoff. No settings, clipboard operations, or history restore.

Exact resume of the saved handoff test dialog was attempted after the user
closed its source tab. The launcher exited 2 before creation
(`launch_precreate_unverified`); no new tab or history restoration. A scoped
read of the earlier shell test tab independently reproduced a `TypeError`:
the SDK returns null for its absent omp identity and the adapter tried to
decode it as JSON. No duplicate override or retry was used.

After the resume correction, the complete native inventory agreed with the
visible panes. Shell exclusion succeeded both for a direct zsh process and for
the native Default login supervisor. One exact resume then returned `launched`
with command, identity, and saved history all verified. A read-only repeat
through the CLI with creation explicitly forbidden returned `already_open` for
the same tab and terminal, without calling creation. No model request, duplicate
override, or changes to existing tabs or persistent settings.

One separately authorized model request was sent to that restored test tab only.
An exact-session `it2 session get-status` observation saw `idle`, `working`,
then `done`. The test request and matching assistant response were appended to
the verified same dialog. The user noticed some notifications but could not
attribute or count them for this request; exactly one completion banner remains
unverified. No notification was generated by a separate test sender.

## Remaining acceptance and release gates

Persisted migration is verified; overall Task10/native UI acceptance is not.
Create only explicitly authorized bounded own test tabs and preserve all IDs.
Clipboard checks require separate temporary preserve/replace/restore permission.

Pending real surfaces: handoff with a named omp profile and with effective
autoResume enabled; native continuation into a separate file; native
blocked/error; exactly one notification
with receiver/macOS behavior; EN/RU Cmd+C/paste/Alt+Enter and unchanged Ctrl+Q;
cd/reset/APS/light-dark/appearance and project shell buttons.

A private beta archive was rebuilt from resume-correction commit `19ed636a82`.
The SHA-256 matched its checksum file, and both CLI and `launch-omp` help ran
from a fresh extraction. This verifies packaging, not native readiness. No
merge, push, or publication has occurred.
