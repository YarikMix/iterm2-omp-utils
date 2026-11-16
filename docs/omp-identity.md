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
- `pid`, `process_start` (`darwin-bsd:<birth seconds>:<six-digit microseconds>`), `generation`

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

`runtime.terminal_identity.process_start(pid) -> str | None` is the single
process authority for both publication and consumption. It calls public Darwin
`libproc.proc_pidinfo(PROC_PIDTBSDINFO)` through stdlib ctypes, reading
`proc_bsdinfo.pbi_start_tvsec/pbi_start_tvusec` and `pbi_status` in one kernel
snapshot. Only SRUN, SSLEEP and SSTOP establish a live birth; zombies, creation,
unknown states, wrong PID, partial results or unavailable ABI return None.
There is no ps-lstart, kill-zero or PID-only fallback. Same-second PID reuse
differs at microsecond birth precision, even if stale record and variable
generations still agree. The public ABI is defined by macOS SDK `libproc.h`,
`sys/proc_info.h`, `sys/proc.h` and `sys/param.h` (MAXCOMLEN=16);
the LP64 BSD-info structure is 136 bytes with birth fields at offset 120.

The standalone extension invokes its selected Python/helper as
`terminal_identity.py --process-start PID`; this prints the shared authority's
JSON string or null without importing the SDK. TypeScript validates that wire
value only; it has no separate process-state/birth implementation.
Consumer transports must use the same Python process_start function unchanged.
Previously formatted coarse lstart strings cannot establish current identity.

Retained Python helpers `terminal_id` and `terminal_from_environment` keep their
Task4 signatures. `tty_device`, `process_start`, `observe_own_terminal` are generic
additions; obsolete event normalization is not imported by appearance/identity.

No status/notification pipeline, daemon or completion inference is added.
Runtime/live acceptance and RED/GREEN execution are explicitly queued to Task10.

## Installed appearance consumer

`runtime.terminal_identity.read_identity_records(registry)` is the single private
schema reader; `omp_sessions.read_bindings` converts its dictionaries to the
public dataclass. `verified_identity(registry, observed)` requires an exact
record match and the same live kernel birth. The installed appearance release
imports this adjacent standalone helper, never the checkout package.

Appearance obtains terminal/tab/window addresses from its own scoped SDK tree
and merges them over decoded `user.iterm2_utils_omp` before validation. Each write
also checks the caller's actual TTY device. Shell preexec captures a baseline and
arms the bounded event observer for any command, without trusting its name;
only verified main identity reserves a launch snapshot or writes appearance.
Shell precmd cancels/reaps the old observer before the return observer; a live
new main identity prevents return writes. Native `-ilc` launch explicitly arms
the same installed callback before exec. Ordinary shell launch remains independent.
