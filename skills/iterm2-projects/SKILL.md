---
name: iterm2-projects
description: Use when adding, removing, renaming, moving or listing iTerm2 project-launcher button projects, or selecting their ordinary parent profile on macOS with zsh.
---

# Shell project buttons

Project buttons open **shell** tabs, never implicitly omp. Preserve project JSON,
retained profile/button GUIDs, native action27 and login-shell/cwd semantics.
Keep actual names/paths/receipts private; public examples use Project A/B.

When explicitly available, use owned MCP `list_projects` for read-only listing;
returned `id/name/path` are visible to the configured model provider. Interactive
changes use only native omp TUI `iterm2_project_edit`, with a fresh local preview
and human confirm for that exact edit. Remote/headless or missing native editor
means blocked, not permission to bypass confirmation via file/CLI writes. A
separately requested operator CLI/setup workflow remains distinct below.
Decline, stale preview or revoked ownership means preserve data; never replay.

## Read first

Use a verified public checkout/release. Choose existing Python 3.11+ with official
`iterm2`; preserve absolute `sys.executable` in `ITERM2_UTILS_PYTHON` without
resolving virtualenv symlinks. Require zsh, permitted SDK/API and the required typed
native inventory/component schema, not an exact version string. An unsupported
schema blocks launcher only; ordinary shell remains available. Do not install
packages, change permissions or bypass a denial automatically.

Read fresh `resolve_paths()` and `state.load(data/receipt.json)` locally. A current
receipt supplies `selection.omp_profile`, `parent_profile` and exact ownership;
no agent selector. Historical state requires explicit migration via iterm2-setup.
An owned source that disappeared can start from the fresh installed 0600 copy.
No receipt plus manual/foreign panel or incomplete inventory means stop, not
import/adopt. Detailed schema/commands are in [projects](references/projects.md).

## Transition

- List read-only, without recovery or printing receipts.
- Resolve by exact id, then unique name, then normalized absolute path. Ask for
  duplicate/ambiguous matches. New paths must be existing absolute directories.
- Repeated add/missing remove is a no-op. Rename/move preserves id and position.
  Remove one preserves remaining entries; remove last uninstalls only
  `project-launcher`, not folders or sessions.
- First install asks only missing parent/project/profile choices. Omp storage
  follows the shared resolver; do not turn storage selection into agent launch.

Prepare a private 0600 candidate outside the checkout, preserving profiles,
entries and order. Never directly edit installed files. Save receipt/config
fingerprints for preview and compare immediately before apply. Concurrent edit
means discard stale argv and preserve the edit, not force/retry it. Follow
plan → install dry-run → install → doctor from the reference. Only plan/install
accept the config flag; update reuses the owned installed copy.

Delete the candidate after verified success; retain it for failed/interrupted
recovery or unknown native write. Use the existing CLI journal recovery before
further mutation, never repeat an unknown native write or invent a journal.
Exact GUID ownership, reference guards and CAS outrank matching display names.
Do not retire referenced profiles, reset foreign buttons, close sessions, use
direct SDK/GUI writes or force/adoption overrides. API readback is not visual or
click acceptance; report unperformed live checks honestly.
