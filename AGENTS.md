# Repository guidance

This public package supports macOS + zsh and Python 3.11+ (stdlib, unittest).
Read README.md and the three skills/*/SKILL.md bundles for setup, launch and projects.
No private framework, author workspace or corporate service is required.

## Development and tests

Use TemporaryDirectory HOME/Paths and fake Runner/adapters for all tests. Never
read or change the developer's real agent/iTerm2 settings, auth, .env files or
old source checkouts. Do not launch GUI or change permissions during development.
Integrated checks: `python3 -m unittest discover -s tests -t . -v`,
`bun test tests/test_omp_config.ts tests/test_omp_identity.ts`,
`/bin/zsh tests/test_appearance_shell.zsh`, and tools/check_{sources,skill,export}.py.
Build releases with `python3 tools/build_release.py --destination dist`.
During the approved omp-only plan, all execution is reserved for Task10;
authored regressions, source review and hash preparation are not passing checks.
Fixture tests and structural checks do not establish live acceptance or agent
behavior; document the actual verification matrix and unresolved UI checks.

## Product invariants

End users explicitly authorize changes to their actual selected settings through
the CLI. Ask only for missing explicit features and omp storage/iTerm parent
profile choices; there is one active consumer, omp. Bootstrap copies only the
selected bundle and selects no features. Pure builders return ChangeSet, never
write or launch GUI. Use the transaction engine, receipts and CAS for owned
values; preserve foreign changes and original inverses. Keep stdout diagnostics
bounded and free of settings bodies/secrets.
No historical agent discovery, command interception, version pin or launch alias.
Strict legacy decoding/recovery and receipt-authorized cleanup are data migration
only. Never delete by a guessed path/name or reactivate a disabled foreign writer
without explicit opt-in. Preserve live/buried referenced GUIDs and old immutable
runtime still needed by existing shells. Never close/restart user sessions.
Shell mode carries no agent profile or optional agent/Bun probes. Omp launch uses
one SDK create with complete command, bounded waits and no retry after unknown.
Status/notifications are native omp only; identity is a main-TUI/own-TTY bridge,
not a second event writer. Capability evidence gates only its selected operation;
version strings are diagnostic. MCP remains optional and pinned.
The public export is an explicit allowlist; preserve runtime/omp_config.ts to
vendor/yaml relative layout and the bundled licenses/artwork notices. No author,
checkout, private SDD, auth, receipt or live inventory paths belong in the release.
UI denials are not bypassed. Human permission/trust dialogs remain human actions.
