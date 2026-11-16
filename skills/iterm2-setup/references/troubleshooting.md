# Maintenance and unresolved setup

Use existing Python 3.11+ from the checkout/release. `doctor --json` is read-only;
`doctor --live --json` adds bounded selected-feature reads, never terminal typing.
No receipt does not authorize adopting files by name. Invalid receipt blocks
replacement. Output contains findings, not snapshots/settings/private stderr.

## Owned maintenance

```sh
python3 -m iterm2_utils update --dry-run --json
python3 -m iterm2_utils update --json
python3 -m iterm2_utils uninstall --features shell --dry-run --json
python3 -m iterm2_utils uninstall --features shell --json
```

Update/uninstall/doctor/reconcile retain the receipt's omp profile; an explicit
different `--omp-profile` conflicts. Plan/install resolve the requested profile
and cannot switch existing ownership. Keep the recorded parent until removed.
Use plan/install to add only explicit features. Partial uninstall retains shared
consumers. Only unchanged owned values are restored, never whole config backups.
Changed/foreign values stay conflicts; no force/adopt/coexist escape hatch.

## Migration is explicit

```sh
python3 -m iterm2_utils migrate-omp --dry-run --json
python3 -m iterm2_utils migrate-omp --apply --json
```

Preview is also the default with no apply/dry-run flag. `--restore-external`
is explicit, visible opt-in to restoring proven previously disabled external
integration, not ordinary cleanup. Historical receipt/journal/three independent
bundle receipts are processed through the migration API, with locks/recovery/CAS.
No historical executable is needed or discovered. Preserve original inverses,
changed foreign entries, referenced profile GUIDs and required old immutable
runtime for live/buried sessions. Unresolved provenance/cleanup stays retryable
and pending; transfer does not mark selected features installed. Never delete
history/config/directories wholesale or close sessions to force cleanup.

## Independent skill refresh

```sh
python3 -m iterm2_utils bootstrap-skill --skill iterm2-launch --omp-profile work --dry-run --json
python3 -m iterm2_utils bootstrap-skill --skill iterm2-launch --omp-profile work --json
```

Repeat separately for iterm2-setup or iterm2-projects. The shared native resolver
selects destination `agent_dir/skills/BUNDLE`, not an assumed default directory.
Each bundle has its own receipt. Extra personal files survive; changed owned
files and foreign paths/symlinks conflict. Historical host copies require explicit
migration, never implicit recovery/overwrite. Bootstrap selects no terminal
feature, probes no agent/SDK and authorizes no configuration. Read SKILL.md
directly until the current host refreshes discovery; no real deployment implied.

## Feature-specific blockers

- Missing selected dependency: explain it before authorized installation via the
  existing manager. No automatic SDK, agent or UI tooling installation.
- Native status/notifications: inspect receiver/capability and effective config
  separately. A version string/API-ready does not prove OSC delivery or banners;
  unsupported evidence remains pending, no hooks/daemon fallback.
- MCP: preserve other `mcpServers`/root fields. Changed collision conflicts;
  uvx/server Python >=3.12 and API authorization are separate prerequisites.
- Restore: exact file/ID/cwd/profile, continuation/history and launch command
  evidence are separate. Missing history never falls back to a fresh dialog.
- Shortcuts: resume needs explicit noncolliding key; preserve Ctrl+Q native.
  Clipboard is terminal Cmd+C, not Ctrl+C cancellation.
- Pending UI: use actual returned code and ui.md, then reconcile. Denied access
  remains denied, including when another automation tool is available.

## Appearance and project launcher

First appearance/project install requires its explicit private local JSON;
subsequent update uses the owned installed copy. Invalid rules/PNG/JSON or
changed owned data must be resolved locally, never overwritten. Keep names,
paths and contents private. Select an existing Python3.11+ with `iterm2` using
absolute `ITERM2_UTILS_PYTHON`; never run startup pip. No exact iTerm version pin:
required typed native schema gates launcher, not independent shell operation.

Ordinary cd applies most-specific physical-root color/icon; outside disables
base/light/dark use-color and hides custom icon without choosing default RGB.
Unreachable external roots are not created. Preserve foreign hooks and APS/manual
CAS. Color/icon writes require exact explicit terminal TTY; main styling also
requires main-TUI canonical identity plus live kernel foreground/birth proof.
Inherited IDs, child/subagent identity or read-only access are insufficient.
Rapid cd cancels/reaps earlier helpers; explicit launch arm and command-lifetime
observation use existing bounded runtime, no permanent service or retry.

Already running shells can retain older immutable hooks/runtime. Updating does
not retrofit/restart them; use a fresh owned test shell only when authorized.
Uninstall does not reset existing tabs or remove foreign appearance settings.
Launcher unknown writes retain existing durable journal for recovery before any
new mutation; do not immediately repeat a write. Native-reference guards block
retirement of live/buried/externally referenced GUIDs or incomplete inventories.
API readback is not visual/APS/theme/button-click acceptance; keep those pending.
