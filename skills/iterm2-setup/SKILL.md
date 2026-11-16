---
name: iterm2-setup
description: Use when setting up, diagnosing, migrating, updating or removing selective omp iTerm2 integrations on macOS with zsh, including native status, notifications, clipboard, shortcuts, MCP, shell, appearance and project buttons.
---

# Selective omp setup

Use https://github.com/YarikMix/iterm2-utils from a verified checkout/release;
read README there. This skill can be read directly before discovery refresh.
Copying a skill authorizes **no settings changes** and selects no features.

1. Choose existing Python 3.11+. Run `python3 -m iterm2_utils doctor --json`
   read-only. Ask only for missing choices: selected omp storage profile,
   [features](references/features.md) and ordinary iTerm parent profile. Preserve
   explicit choices; “setup” does not mean all nine features.
2. Resolve omp storage using the shared `resolve_omp_profile`: explicit
   `--omp-profile`, then `OMP_PROFILE`, then `PI_PROFILE`; respect `PI_CONFIG_DIR`
   and default-only `PI_CODING_AGENT_DIR`. Never guess the default directory over
   a named/effective profile. Parent iTerm profile is a separate selection.
3. Explain only selected missing dependencies. Installing packages/settings
   needs authorization, not permission inferred from copying this bundle.
   Preserve model, credentials, endpoint and approval settings. Capability/schema
   evidence governs compatibility, not exact version strings. Missing capability
   blocks its feature, not shell or other independent features.
4. Preview exact selected changes, then matching dry-run/install when authorized:

   ```sh
   python3 -m iterm2_utils plan --features status,notifications --omp-profile work --json
   python3 -m iterm2_utils install --features status,notifications --omp-profile work --dry-run --json
   python3 -m iterm2_utils install --features status,notifications --omp-profile work --json
   ```

   For shortcuts supply `--shortcuts CSV`; selecting `resume` requires explicit
   `--resume-key`. `--notify-errors` is explicit notification error opt-in.
   Appearance/project-launcher first install needs its selected local JSON via
   `--appearance-config` / `--project-launcher-config`. Preserve the same path
   for preview/apply; never print private roots/config bodies. Native status and
   notifications have no hook/daemon fallback; clipboard uses Cmd+C, not Ctrl+C.
5. Historical receipt/journal? Stop normal install/update and preview
   `python3 -m iterm2_utils migrate-omp --json`. Only explicit `--apply` mutates.
   `--restore-external` is a separate visible choice to reactivate proven old
   external values, never default. Recovery/CAS and exact receipt ownership
   protect user edits, referenced profiles and old live sessions. Unresolved
   cleanup/source intent stays pending; transfer alone is not feature installation.
6. Run doctor after install. Preserve actual completed/blocked/pending results;
   follow [UI verification](references/ui.md) and reconcile actual codes. Human
   “done”, SDK readback and saved settings do not prove native events or banners.
   Missing/denied UI access means manual instructions and pending state; no
   alternate automation, TCC changes or auto-install. System dialogs remain human.

For maintenance and independent bundle copies read
[troubleshooting](references/troubleshooting.md). Extra personal skill files,
foreign settings and changed owned files remain intact; no recursive deletion or
force/adoption shortcut. Do not close/restart existing sessions or type commands
into running agents. For an ordinary tab use iterm2-launch shell mode; for project
list changes use iterm2-projects. Report unperformed live acceptance separately
from structural validation and isolated agent decision scenarios.
