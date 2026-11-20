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
name/GUID; SDK creation rechecks them and the original explicit/parent/sole-window
selection basis. A moved parent or a new second window invalidates automatic
selection even if the old window survives; there is no retarget or retry.
This is a fresh recheck, not atomicity against later SDK/window changes.
Creation supplies the full command, once. No terminal typing, restart, close,
or retry is used. Shell launch needs neither omp, Bun, identity installation nor agent/config probing.
It does not resolve or validate omp storage/profile environment. The internal
`LaunchRequest.omp_profile` is `None` for shell and required for all omp modes;
preflight rejects a shell request carrying agent storage rather than inventing
a placeholder profile. Explicit/recorded selections passed to feature discovery
remain authoritative through its `omp_profile` keyword; only standalone discovery
without a supplied selection resolves ambient profile variables.

omp preflight inspects (never executes) the login-shell function/alias. A single
`command omp [literal options] "$@"` passthrough is accepted; literal profile,
model, provider, thinking and config options and zero to two literal `--no-daemon`
flags are preserved. Other wrappers,
aliases, injected continue/resume/goal/approval/session-dir/mode/unknown options
are refused, including unquoted tilde/glob/brace expansion; quoted literal
characters remain literal. Preflight runs startup in the requested cwd.
The actual child login shell rechecks function, alias and executable and invokes
the same pure omp profile resolver against its current HOME/PI_CONFIG_DIR/
PI_CODING_AGENT_DIR before exec; directory drift refuses launch. It retains its
normal environment (including endpoint and
credentials); no settings bodies are read. The selected absolute executable is
used. An env-Bun shebang permits only that selected script's complete argv with
the Bun executable resolved from the same verified login-shell environment.
Capability probes use that environment too; the child rechecks its interpreter
before exec. CLI PATH cannot substitute another Bun. Native binary headers are
inspected as bounded bytes, not decoded as UTF-8. Exact literal-space-joined or
safely tokenized shell-quoted complete argv observations are accepted; extra
arguments, wrong paths and malformed quoted alternatives are refused, never evaluated.
When iTerm2 abbreviates only argv[0] to its basename, every remaining argument
must still match an approved argv exactly (including the absolute script for
an interpreter prefix). This alternative also requires the created session's
positive integer `session.jobPid`, exact `tty`, live kernel process birth,
foreground ownership of that TTY and canonical executable image to agree.
Repeated command/PID/TTY observations bracket repeated kernel samples; changed,
missing or departed jobs remain unverified. No PATH lookup, name-only proof or
process-group search substitutes for that evidence. Full-path proof is unchanged.
Public selected source was inspected at the installed `@oh-my-pi/pi-coding-agent/dist/cli.js`: Bun
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
The complete encoded file, including JSON metadata and instructions, is limited
to 65536 UTF-8 bytes, matching its private reader. Oversized tasks are rejected
without truncating content or retaining an unusable task directory.

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
incomplete live candidates block creation instead of silently duplicating. Positive
matches win regardless of earlier ambiguous unrelated panes. An empty/missing registry
is not negative evidence. Literal null identity may exclude an ordinary local shell
only with independent same-pane SDK addresses, positive root/job PIDs and canonical
`/dev/ttysN`, stable job birth, foreground association and selected system zsh image.
Root and job must agree except for the positively verified native login form: an
unstopped UID-0 SDK root with exact raw kernel `/usr/bin/login` path, directly parenting
the same own-UID foreground zsh job on that TTY. Repeated parent/census/path samples
and scoped rechecks reject restart/reparent/exec changes. Protected login's unavailable
birth is not required or invented; the job still requires birth-qualified kernel proof.
The raw path helper grants no liveness authority and existing image callers retain
their birth-qualified contract. Malformed, missing or encoded-null identity stays unknown.
Two bounded process/TTY samples reject other stopped/traced or foreign-UID processes,
other concrete TTY holders and unavailable/diagnostic output. Same-UID prompt workers
without TTY access are allowed; scoped `/dev/tty` holders additionally require stable
birth and the same canonical system zsh image. No helper-name or foreground-only
heuristic is used. `lsof -t +w` preserves warnings, which block exclusion.
Negative decisions also require independent raw SDK inventories before and after
the scan to match the visible typed window/tab/pane sets. Buried, minimized, mux,
malformed or changing inventory blocks rather than guessing. This conservative
tradeoff can refuse resume in busy or unsupported terminals. Observations are not
atomic against a process/session starting afterward. New/handoff/shell remain
independent; duplicate opt-in still requires explicit human authorization.

Exit 2 / blocked precedes creation. Exit 3 / created_unverified or unknown keeps
all known SDK IDs without filling missing IDs from inventory. Exit 0 / launched
requires exact window, single-session tab, profile and complete supported process
argv. Already-open is exit 0 with its current addresses, without creation.
`command`, `identity`, `history`, `ack` are separate evidence fields. Command
success is not history success: history=unverified means **resume command launched,
history restoration unconfirmed**. Ack=unconfirmed means **task receipt unconfirmed**.
No raw argv, prompt, terminal screen, settings or private subprocess exceptions
are serialized. The returned session_id is the terminal ID, not omp dialog ID.
Plain text output includes all four proof states and known addresses just as
JSON does; command success retains its independent exit semantics.
Identity transport uses the contract in omp-identity.md, never a registry echo.

External reads are at most 10 seconds. Standard resume duplicate preflight has a
separate 30-second bound restored before creation; SDK create plus launch observations
share 30 seconds from creation, ack separately 120. Offline regression results do
not establish live iTerm2/omp acceptance.
