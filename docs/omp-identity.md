# omp identity interface

`iterm2_utils.omp_sessions` exports immutable `ResumeTarget` and `SessionBinding`,
`resolve_resume(path, expected_id, profile)`, `matches_conversation(target, actual)`,
`read_bindings(registry)` and `find_open(target, transport)`.

Saved files are explicitly addressed, absolute regular JSONL files. The reader
accepts native optional first-line `title` slots before `session` headers. The
header ID must equal the entire requested ID; filenames, titles and prefixes are
not evidence. Header cwd must exist for resume. Native headers do not encode a
profile: callers supply the selected resolved `OmpProfile` and preserve it through
launch and observation. Session-dir overrides are valid; no standard-history-path
restriction or invented profile setting is imposed.

A same-dialog match requires exact file/ID/cwd/profile or an unambiguous sibling
chain of `continuationOf == parentSession` header IDs reaching the requested
header. Each child must contain the parent's latest conversation-entry ID;
parent-only forks, substituted headers and cycles fail closed. This does not pick
a newest file: native omp performs its own continuation selection.

## Registry schema 1

Installed standalone extension:
`<selected agent_dir>/extensions/iterm2-utils-identity.ts`. A foreign collision is
refused. Its embedded installation data contains the selected profile, private
package data root and selected absolute Python/helper paths; no settings, auth,
model, endpoint or approval values are read or changed. Native extension discovery
loads the selected profile's file; no default-profile inheritance is assumed.
Disabled extension discovery leaves identity unverified, not synthesized.

`<package data>/identity/<instance UUID>-<generation UUID>.json` is a 0600 regular
file in a 0700 owned directory. Atomic no-replace hard-link publication of a
private temporary file prevents symlink/foreign overwrite. The JSON has exactly:

- `schema: 1`
- `terminal_id`, `tab_id`, `window_id`: explicit observed addresses
- `session_id`, `session_file` (absolute string or null), `cwd`
- `profile: {name: string|null, agent_dir: absolute string}`
- `pid`, `process_start` (bounded `/bin/ps -o lstart=` identity), `generation`

The own tty receives OSC 1337 `SetUserVar=iterm2_utils_omp` containing base64 JSON
of the same record. Consumers obtain decoded JSON from
`user.iterm2_utils_omp` through the official SDK, independently observing actual
session/tab/window IDs. They must not use the variable alone as liveness.

Only `mode === 'tui' && agent.kind === 'main'` can publish. Actual manager
`getSessionId/getSessionFile/getCwd` values are sampled on session_start,
session_switch and session_branch. A missing file remains null, never an inferred
filename. Every update invalidates its preceding record first. Shutdown removes
only this extension instance's current record, not another process/generation.
It deliberately does not clear user variables that might belong to a newer
process; orphan variables cannot establish identity without a matching live record.

The helper first checks explicit environment terminal-source agreement, process
controlling tty and SDK session tty device identity. Therefore a stale inherited
terminal ID cannot target another tty. Writes open the observed tty with
O_NOFOLLOW and compare its character device to process stdin again. Missing tty,
API permission or root-agent discriminator means no verified publication.

## Task 6/7 transport boundary

`find_open` takes a transport with synchronous `bindings()` (use read_bindings),
`process_start(pid)` (use runtime.terminal_identity.process_start) and
`observe(terminal_id)` methods. `observe` must merge independently scoped actual
terminal/tab/window addresses with decoded user identity; actual addresses win.
It returns the SessionBinding-shaped dictionary (schema may also be present).
No registry echo, active-tab lookup, title, jobName or PID-only result is valid.
All binding fields including generation/file/profile must match, and process
birth identity must still match. Callers bound their SDK worker operations and
keep API/create/identity/handoff evidence separate.

Retained Python helpers `terminal_id` and `terminal_from_environment` keep their
Task4 signatures. `tty_device`, `process_start`, `observe_own_terminal` are generic
additions; obsolete event normalization is not imported by appearance/identity.

No status/notification pipeline, daemon or completion inference is added.
Runtime/live acceptance and RED/GREEN execution are explicitly queued to Task10.
