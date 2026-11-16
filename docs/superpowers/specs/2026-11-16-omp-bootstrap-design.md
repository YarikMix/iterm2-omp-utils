# omp support for bootstrap-skill

Status: approved by the user on 2026-11-16.

## Intent

Allow omp users to install and update this repository's skills through the existing bootstrap command, without manual copying. Keep omp's existing iTerm2 integration unchanged.

## Approaches

1. Native omp destination (selected by the user): isolated omp installation using its profile-aware skill directory; reuse existing transactional file ownership and updates.
2. Shared `~/.agents/skills` destination (not selected): discoverable by omp, but also exposed to other agents using this directory.

This is a small installer extension, not a new terminal integration or plugin system.

## CLI and skill contract

- Add `--agent omp` to `bootstrap-skill` only. Existing feature commands continue to accept only their existing Codex/Claude consumers.
- Preserve required `--agent`, default `--skill iterm2-setup`, and `both = codex + claude`. Do not add an all-agents mode.
- Permit omp as installation host for `iterm2-setup`, `iterm2-projects`, and `iterm2-launch`.
- `iterm2-launch` installed in omp still launches/resumes Codex, not omp. Preserve the existing Claude/both launch restriction.
- Setup and projects skills hosted by omp still configure the currently supported Codex/Claude consumers; installation host does not expand feature support.

Example:

```sh
python3 -m iterm2_utils bootstrap-skill --skill iterm2-projects --agent omp --dry-run --json
python3 -m iterm2_utils bootstrap-skill --skill iterm2-projects --agent omp
```

## Destination

Match the native macOS omp directory semantics verified in installed omp 18.20.2 public source:

- Default: `HOME/.omp/agent/skills/<skill>`.
- Named profile: `HOME/.omp/profiles/<profile>/agent/skills/<skill>`.
- Respect `PI_CONFIG_DIR` as omp's config-directory-name override.
- Resolve profile from `OMP_PROFILE`, falling back to `PI_PROFILE` only when `OMP_PROFILE` is absent. Empty/whitespace or `default` selects the default profile; invalid profile names fail before writes.
- For the default profile, respect `PI_CODING_AGENT_DIR`; named profiles ignore this override, matching omp. Match omp's relative-path resolution.
- Resolve against the bootstrap command's selected HOME/environment, never the developer's personal paths. Do not inspect an existing omp process or its private settings. A profile supplied only to a separate omp invocation with `--profile` is not discoverable here: document setting `OMP_PROFILE` explicitly for the bootstrap command.
- Resolve omp-specific environment only when omp is selected, so invalid unrelated omp variables cannot break existing Codex/Claude bootstraps.

Implementation details, including where the resolved destination lives internally, remain the builder's call; avoid unnecessarily changing positional Paths constructors or widening feature-agent allowlists.

## Safety and compatibility

Reuse the existing transaction engine and per-skill bootstrap receipts. Preserve dry-run, idempotence, cumulative host ownership, foreign-file conflicts, modified-owned-file protection, symlink checks and CAS. Installing for omp must not write Codex/Claude skill destinations or their terminal settings. Bootstrap must not probe/install omp, Python SDK dependencies, or terminal features.

No native omp status, notifications, restore, launch-omp command, plugin packaging, new dependencies, or automatic migration from existing shared skills is included.

## Verification and documentation

Add isolated TemporaryDirectory HOME/environment coverage for omp destinations, profile/override precedence and invalid values, install/update/idempotence/conflicts, all three bundles and cumulative host receipts. Retain existing Codex/Claude and `both` behavior. Exercise the actual bootstrap CLI against a temporary HOME; do not touch real agent settings or launch iTerm2. Update README, relevant skill guidance, compatibility notes and changelog to distinguish the skill host from feature consumers and the Codex launch target.

Run repository-mandated unittest discovery and skill validation once after implementation. Fixture/CLI success proves installer behavior, not a live omp session refreshing discovery or accepting a launched Codex task. Report this boundary explicitly.
