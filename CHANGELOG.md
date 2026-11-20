# Changelog

## Unreleased

Added explicit `close-tab --window ID --tab ID --session ID`: one native tab-only
SDK close without force/retry, guarded by exact unique single-visible-session
target inventory. `closed` requires native OK and fresh complete absence of both
tab and terminal IDs, including minimized/buried; explicit refusal is blocked,
timeout/protocol/incomplete proof is unknown. Same-Python worker supervision,
plain/JSON IDs and early dispatch avoid settings/profile/agent probes. Source
launch skill and documentation now include explicit close; no installed copy
is changed and offline checks do not establish live close acceptance.

Resume now screens literal-null ordinary shell panes only with independent scoped
SDK root/job/TTY and stable Darwin image/foreground evidence, bounded process and
TTY-holder checks (including scoped `/dev/tty` holders). Hidden/minimized/mux or
incomplete/changing SDK inventory blocks negative decisions; exact live matches
still win across pane order and moved addresses. Malformed identity remains unknown.
Duplicate preflight is bounded separately; no automatic duplicate override is added.

Launch command proof now accepts iTerm2's basename-only argv[0] only with an
otherwise exact approved argv and independent live foreground-job evidence for
the created session's integer PID and exact TTY. Repeated command/binding, birth,
foreground and canonical image checks reject changed or missing jobs; interpreter
script paths remain exact. Full-path proof and separate identity/history/ack
contracts are unchanged. Offline regression results do not establish live acceptance.

Historical runtime retirement now uses a bounded, read-only SDK session snapshot
through the invoking Python, independent of status-bar/profile schema and agent
discovery. Missing envelopes/roots or live, minimized and buried sessions defer
cleanup; receipt ownership, persisted-reference checks and locked revalidation
still apply. Keep sessions closed during authorized apply; no sessions are closed
automatically and this does not establish live migration acceptance.

Final omp-only source corrections preserve migrated appearance PNGs and guarded
original binding inverses; native config/MCP FIFO reads fail without mutation.
Resume no longer treats missing identity records as proof a dialog is closed.
Automatic window selection keeps its parent/sole provenance through SDK recheck.
Launch text exposes independent command/identity/history/ack evidence; binary
headers and login-shell-selected Bun/environment are verified without CLI PATH
substitution. Complete literal/quoted argv forms and bounded UTF-8 handoff
production retain exact content/proof. Diagnostic version failures do not erase
available executables. Native receiver delivery remains pending instead of
depending on unsupported it2-help advertisements; parser preparation uses the
supplied lifecycle Runner. Added isolated recovery, policy/UI retry, late-ack,
default installed publisher/private-PTY and platform-applicability regressions.
These source corrections do not establish live iTerm/omp/UI acceptance.

Task10 offline execution (not native/UI acceptance): initial 514-test Python
discovery exposed integration/fixture defects; affected 252-test suites and
12-test extracted-release suite now pass. Bun 16 tests and controlled zsh 25
tests pass; skill/source/export validators pass. One case-sensitive filesystem
test was skipped on the case-insensitive fixture volume.
Fixed Darwin kqueue lifetime cleanup, retained unresolved uninstall selection
and prior UI steps, kept reconciled checks cleared on unchanged updates, and
reported shared-profile failures to every affected consumer. Updated stale
native/PTY fixtures without dropping their safety assertions.
Actual private kernel/foreground/stopped-live/shell-return and temporary-config
CLI/export proofs remain distinct from real iTerm/omp acceptance. Launch skill
timeouts now distinguish per-preflight 10s, shared create/verify 30s and separate
handoff receipt 120s; observe one asynchronous job rather than retrying it.
See `docs/superpowers/validation/2026-11-16-omp-only/acceptance.md` for limits.

Removed obsolete active Codex/Claude runtime, restore tree and status vendor.
Only strict historical data decoding, transaction recovery and receipt-authorized
cleanup remain; no compatibility commands, registration transport or active
pair-selection helpers survive. Retained generic doctor/checkpoint/TTY/atomic
write/lock and real historical hook safety assertions use current fixtures.
The historical beta hook fixture now excludes executable snapshots.
The export allowlist includes the complete native import/helper/YAML closure and
all three bundles; source locks/notices cover retained shell, YAML and artwork.
Authored isolated extraction/bootstrap/shell/installed-parser coverage is queued
to Task10, not executed or evidence of standalone/native UI acceptance.

Shell launch now carries no omp profile and ignores inherited agent storage
environment entirely. Explicit/recorded native profiles reach discovery without
a second ambient resolution. Added invalid-environment real-discovery and
one-create fake-SDK shell regressions; execution remains NOT RUN until Task10.

Exposed the omp-only public CLI: `launch-omp --mode shell|new|handoff|resume`,
exact `--resume-file`/`--resume-id`, explicit preview-default `migrate-omp`, and
profile-aware independent skill bootstrap. Removed historical agent selectors
and interim launch flags without aliases. All three retained skills now separate
ordinary shell, explicit omp, exact continuation and independent evidence;
copying a bundle does not authorize settings changes. Owned-file CAS/personal
files and historical migration boundaries are retained. Isolated CLI/ownership
and structural fixtures are authored; execution and agent scenarios NOT RUN,
queued to Task10, not live acceptance.

Added one-tab shell/new/handoff/exact-file omp launch with capability checks,
last-owned autoResume:false overlays, independent identity/history/ack evidence
and a generic bounded terminal transport. Removed Codex launch version/config
preflight. Live ambiguous resume candidates block automatic duplicate creation;
an explicit duplicate request is separate. See docs/omp-launch.md. Execution
and live acceptance remain queued to Task10.

Added exact omp saved-header/continuation validation and main-TUI-only identity.
Profile-scoped owned standalone extensions publish private generation records
and own-TTY iTerm user variables; PID birth, scoped terminal observations and
full session/profile identity must agree. Stale inherited terminal addresses,
forks, replaced headers and orphan generations are not open-dialog evidence.
Restore and appearance share transactional identity installation, without
status/notification callbacks or model/endpoint/approval changes.
See docs/omp-identity.md; execution/live acceptance remains queued to Task10.
Process identity now shares one public Darwin libproc probe for publisher and
reader: live-state validation plus kernel birth seconds/microseconds, never
coarse ps lstart. Unreaped zombies, same-second PID reuse, partial ABI reads and
unavailable kernel probes cannot establish a live dialog.

Separated current omp receipt v2 from strict historical v1 integration data.
Added pure, shared omp profile resolution matching the existing bootstrap rules.
Generic recovery preserves historical inverses and conflicts without old-agent
commands; current lifecycle requests require explicit migration for v1 receipts.
Resource schema/CAS/native unknown-outcome safeguards and independent bootstrap
receipt locations are retained. Integrated verification is queued, not claimed.
Install/update checkpoints also derive mandatory shared consumers from the
committed receipt: retained blockers cannot be filtered away, and incomplete
shared recompositions cannot replace another selected feature's working values.

Added profile-scoped native omp setting/keybinding adapters and address-level
receipt resources. A bundled, pinned YAML document parser preserves unrelated
values/comments; Python retains private atomic writes, bytes CAS and journal
recovery. Completion/error notifications use native `on`/`off` enums. MCP now
describes one atomic `mcpServers` JSON pointer instead of agent CLI registration.
Named-profile binding conflicts and malformed/legacy storage fail without
overwrite. Bun is needed only for native YAML operations; no startup install,
agent initialization or personal-settings discovery is performed by the helper.
Runtime verification remains queued to the final integrated task.
Native YAML edits reject complete multi-document streams independently of silent
diagnostics and retain block-scalar line boundaries/header comments. The private
helper uses only bounded `{op, raw, pointer, expected?, next?}` read/patch messages;
native setting/action validation stays in the Python adapter.

Added explicit receipt-authorized omp migration with pure preview, locked
receipt/address fingerprints, journal-first apply and independent checkpoints
for all three bootstrap receipts. Exact hook/settings/MCP/skill cleanup preserves
foreign neighbours, retryable conflicts and original inverses. Compatible shared
GUIDs transfer unchanged; historical feature intent is not credited as installed
until the actual lifecycle builder commits it. Disabled external writers stay
disabled by default, outside ordinary uninstall ownership; explicit restoration
cannot activate a duplicate writer. Existing shells retain their old immutable
runtime until a safe explicit retry. Runtime cleanup also re-observes active and
transferred consumers, preserving literal shell/appearance references and sibling
files of active releases even with zero live sessions. Bootstrap now copies only to the selected
omp profile and recovers its own journal before planning an actual update.

Native omp feature builders now configure one status/notification writer, native
picker/resume, scoped MCP, terminal clipboard and explicitly selected shortcuts.
Dedicated profiles remove inherited agent key maps and never match arbitrary
Bun jobs. Ctrl+C/Ctrl+Q retain native semantics. Explicit resume keys are checked
against known defaults and inherited user bindings. Feature checkpoints preserve
notification policy, resume keys, original inverses and shared-consumer guards.
Discovery probes only selected dependencies; versions remain diagnostics.
Retained payloads use a manifest/file allowlist and preserve the YAML helper's
runtime-to-root-vendor layout. Transferred unchanged appearance/launcher settings
can be selected without falsely crediting transfer as installation. Native OSC,
keyboard, banner and identity acceptance remain unverified; all Task4 checks are
queued to the final integrated verification.
Immutable runtime JSON (including the bundled parser package metadata) is
compiled as byte-owned files, not reconstructed configuration addresses.
Clipboard/shortcut discovery also finds optional Python/SDK support for safe
dedicated-profile retirement, without adding a shell/bootstrap prerequisite.
Incremental shortcut installation preserves an existing resume key unless resume
is explicitly selected again. Native binding guards compare canonical modifier
order during both planning and staging, preserving conflicting inherited bindings.

## Historical pre-omp changes (not current product contracts)

Добавлен отдельный bootstrap-навык `iterm2-projects` для операций со списком
проектов project-launcher; его receipt независим от receipts других skill/feature,
а при `both` один receipt описывает оба выбранных host.

Launcher preflight now removes inherited terminal IDs only from its private
login-shell environment, preserving parent appearance and snapshots in both
handoff/resume modes. Appearance independently matches the calling shell's tty
device to the explicitly selected iTerm2 session before any profile or snapshot
mutation, including observer cleanup. Missing/mismatched tty safely skips;
supervisor pipes and nested interactive shells on their own terminal still work.
Update both runtime helpers together and open a fresh shell: already running
shells retain their loaded hook and may still reference an older runtime without
this protection. An old caller invoking the new Python helper without tty safely
skips; updating does not retrofit running shells.
No public options or project-rule schema changes. Fixture acceptance does not
establish live iTerm2 behavior.

Added opt-in `project-launcher` and `--project-launcher-config` for plan/install:
ordered native project buttons open a fresh login-shell tab in the same window.
Local strict JSON selects existing target profiles and project directories;
stable GUIDs, owned 0600 config, whole-file Dynamic Profiles CAS and shared
feature×agent receipts support repeat/update without the source and selective
uninstall. Fresh native reference/session checks guard every target deletion,
including rollback/recovery; typed grouped panel conflicts preserve later edits.
Requires iTerm2 3.7.6 and a selected Python 3.11+ with SDK/API authorization.
Fictional docs/HTML ship offline; new CLI live installation/rendering is unverified.

Added explicit Codex-only `appearance`: repository JSON rules choose a session
color and one of nine bundled PNGs or an owned copy of a custom PNG.
Applies at interactive shell start, ordinary cd and Codex start (including
resume/fork/restore). Leaving registered roots disables base/light/dark Tab Color
and hides the custom icon without choosing a default RGB. A once-only native zsh
chpwd hook preserves foreign hooks and targets its owning interactive shell;
API failures do not fail cd. This updates existing appearance without a new flag
or JSON schema. Unavailable roots never match or get created. Uses the shared
installer/dispatcher and selected Python 3.11+ with the official iterm2 SDK.
Update works without original JSON/PNG; selective uninstall preserves foreign
changes and other runtime consumers. API authorization stays pending until the
explicit-session read-only reconcile succeeds. Existing `ios-mail`, `ios-cloud`,
`android-mail`, `android-cloud` names now use branded Mail/Cloud artwork;
`chrome-mail` and `chrome-cloud` add the official Chrome mark. The platform stays
larger with the service badge at bottom right (variant B). `ios`, `ios-mail` and
`ios-cloud` now use light Apple `#E6F4FF` with its leaf and bite, preserving the
existing service badges; `android`, `kotlett` and the other pairs are unchanged. Transparent 128×128 PNGs and matching SVGs ship
offline in runtime/export. Public-source provenance, transformations and brand
ownership are recorded in THIRD_PARTY_NOTICES.md; third-party artwork is separate
from the package's MIT code/original illustrations. Fixture delivery and lifecycle
checks do not establish live APS transitions, icon readability or API permission.

Added `launch-codex` and the separately installed Codex-only `iterm2-launch`
skill: one new tab in an explicit window/profile, preserved login-zsh wrapper,
unique handoff/receipt instructions and bounded observations without automatic
retry. Launch requires source-verified Codex 0.166.0 and compatible existing
clipboard settings; effective config initialization may write normal Codex
state/log databases. Default bootstrap still installs only `iterm2-setup`.
Release fixtures cover launch through the bundled transport without restore
installation and installed restore after source/archive removal. Both skills
are structurally checked; model behavior and live clipboard remain unverified.

Codex status uses the native cc-status backend from a compatible iTerm2 3.7.6+
bundle, including native done and background-task handling. Owned beta.1 status
migrates through update; external legacy remains reused until explicit
`--adopt-legacy`. External complete native hooks are reused without ownership.
Notifications and restore remain independent; notification transition code stays
as a dependency, without writing visible status.

Read-only doctor separates backend, native capability, API connectivity and the
error-event source. Codex 0.163.0 has no StopFailure event, so automatic API-error
display is unsupported; unknown versions remain unverified. Fixture and source
checks do not establish live Codex delivery, renderer behavior or new CI results.

## v0.1.0-beta.1 — 2026-10-23

First public beta for macOS + zsh, Python 3.11+. Explicit selection of clipboard,
status, notifications, Codex restore, read-only MCP, shell integration and hotkeys.
Includes ownership-aware install/update/uninstall, dry-run, UI checkpoints and a
portable setup skill. Runtime and pinned sources are bundled; archive export uses
an explicit file allowlist and includes all source/license notices.

Automated checks use isolated fixtures. Live macOS/iTerm2/agent acceptance and
fresh-model skill behavior remain unverified; see [compatibility](docs/compatibility.md).

Final beta integration corrections: independent per-agent feature/shortcut
receipts and selective removal; owned hook replacement after interpreter changes;
read-only resource/dependency doctor and selected live probes; Python 3.11+ runtime
and complete notification prerequisites; explicit foreign-notification coexistence;
standalone daemon-command classification; materialized evaluation fixtures and
strict provenance metadata. Live/model acceptance remains unverified.
