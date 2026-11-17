# Omp-only acceptance evidence — 2026-11-17

## Scope

Task10 offline execution only. No personal settings/auth, actual iTerm API,
GUI, installation/migration or user test tab was read, changed or created.
Fixtures do not establish native/UI acceptance. Earlier authoring-stage NOT RUN
statements remain historical; this matrix records the first integrated execution.

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

## Pending selected preview and live acceptance

No overall Task10 completion or installed/native feature claim is made.
Before reading any real selected settings/inventory for preview, obtain scoped
read-only authorization and the material choices: selected features, omp storage
profile, existing iTerm parent/shell profiles, shortcut subset/resume chord,
notification error opt-in, appearance/project configuration if selected, and
whether any explicitly identified external integration may be restored.
Bootstrap alone grants none of these settings permissions.

Show the actual selected migration/install preview (including owned addresses,
conflicts, retained old runtimes/profiles and external-reactivation choice), then
obtain separate apply authorization. Keep foreign/conflicting values and live
references; old running shells may continue using retained old runtime and must
not be restarted automatically.

Live prerequisites also include an existing chosen Python/official SDK and
explicit iTerm API/trust permission, an unambiguous allowed window, exact selected
profiles/cwd/history and bounded owned test-tab budget including project buttons.
Any missing SDK installation or trust action remains a separate human decision.
Clipboard tests require explicit temporary preservation/replacement/restoration
permission without printing contents; otherwise leave them unverified.

Pending real surfaces: ordinary shell; empty fresh omp; named-profile handoff
with actual new ID and fresh ack under autoResume; exact resume/continuation and
no duplicate-open; native idle/working/blocked/done/error; exactly one notification
with receiver/macOS behavior; EN/RU Cmd+C/paste/Alt+Enter and unchanged Ctrl+Q;
cd/reset/APS/light-dark/appearance and project shell buttons. Preserve every
actual created ID and clean up only fixture-owned resources. No personal tabs
were used during offline execution. Controller retains scoped authorization,
fresh task review and the native whole-branch review.
