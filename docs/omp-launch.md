# One-tab omp launch

`python3 -m iterm2_utils launch-omp --mode MODE --profile NAME --cwd ABS`
requires `MODE` to be `shell`, `new`, `handoff` or `resume`. Handoff requires
`--handoff ABS`; resume requires both `--resume-file ABS_JSONL` and `--resume-id ID`.
Shell/new accept neither handoff nor resume inputs. `--allow-duplicate` is resume-only.
`--omp-profile NAME` selects omp storage independently of the iTerm profile.
`--window ID` is optional only when consistent parent bindings or a complete
sole-window inventory resolve it. There is no focus selection, interim selector
flag or legacy launch alias.

The selected iTerm profile must have no startup command. Preflight checks exact
name/GUID; SDK creation rechecks them and the window. Creation supplies the full
command, once. No terminal typing, restart, close, or retry is used. Shell launch
needs neither omp, Bun, identity installation nor agent/config probing.

omp preflight inspects (never executes) the login-shell function/alias. A single
`command omp [literal options] "$@"` passthrough is accepted; literal profile,
model, provider, thinking and config options are preserved. Other wrappers,
aliases, injected continue/resume/goal/approval/session-dir/mode/unknown options
are refused, including unquoted tilde/glob/brace expansion; quoted literal
characters remain literal. Preflight runs startup in the requested cwd.
The actual child login shell rechecks function, alias and executable and invokes
the same pure omp profile resolver against its current HOME/PI_CONFIG_DIR/
PI_CODING_AGENT_DIR before exec; directory drift refuses launch. It retains its
normal environment (including endpoint and
credentials); no settings bodies are read. The selected absolute executable is
used. An env-Bun shebang permits only that selected script's complete argv with
the resolved Bun executable, never an arbitrary Bun job. Public selected source
was inspected at the installed `@oh-my-pi/pi-coding-agent/dist/cli.js`: Bun
shebang, literal profile passthrough generator and repeated config parser. Version
is informational, not pinned. Required CLI flags are checked per operation.

New and handoff launches retain a unique private temporary `fresh.json` overlay
containing only `{"autoResume":false}`. It is the last `--config`, without
custom session storage or persistent config changes. Resume uses exact absolute
`--resume FILE`, not restore/continue/prefix/latest, and never falls back to new.

## Task8 Python handoff API

`prepare_handoff(cwd: Path, task: str) -> Handoff` creates a retained unique
0700 temporary directory containing 0600 `handoff.md` and an absent `ack.json`.
`Handoff` exposes `path`, `request_id` (UUID nonce), `ack_path`, and canonical
`cwd`. The Markdown's **first line is JSON** with request_id/ack_path/cwd;
following sections are task/context/instructions. Pass `artifact.path` as the
LaunchRequest.handoff. Do not reuse paths or erase receipts. Callers include
scope, first step, authorization and unresolved questions in task text.

Receiving omp writes the existing reference's five fields: request_id,
thread_id (actual omp session ID), cwd (actual verified cwd), accepted_task,
first_step. All are nonempty strings, atomically written as private ordinary
UTF-8 JSON at ack_path. `valid_ack` rejects links, changing/oversized/nonprivate
files, wrong nonce/actual identity/cwd and timestamps before launch or in the
future. Receipt means read, not task completion or additional authorization.
`read_handoff` consumes this exact convention; arbitrary legacy text is not an
implicit handoff. The CLI performs up to 120 seconds of independent identity/ack
observation after command proof, without resending anything.

## Results and duplicates

LaunchRequest has window_id/profile/cwd/omp_profile/mode/handoff/resume plus
`allow_duplicate: bool = False`. Task8 must set it only for an explicit human
request (`--allow-duplicate`), never an automated retry. Before resume, matching
live candidates require independent SDK/user-variable identity and shared kernel
process birth evidence. Moved addresses are returned as currently observed;
incomplete live candidates block creation instead of silently duplicating.

Exit 2 / blocked precedes creation. Exit 3 / created_unverified or unknown keeps
all known SDK IDs without filling missing IDs from inventory. Exit 0 / launched
requires exact window, single-session tab, profile and complete supported process
argv. Already-open is exit 0 with its current addresses, without creation.
`command`, `identity`, `history`, `ack` are separate evidence fields. Command
success is not history success: history=unverified means **resume command launched,
history restoration unconfirmed**. Ack=unconfirmed means **task receipt unconfirmed**.
No raw argv, prompt, terminal screen, settings or private subprocess exceptions
are serialized. The returned session_id is the terminal ID, not omp dialog ID.
Identity transport uses the contract in omp-identity.md, never a registry echo.

External reads are at most 10 seconds, SDK create plus launch observations share
30 seconds from creation, ack separately 120. All execution/RED/GREEN and live
acceptance are queued to Task10; no runtime success is claimed here.
