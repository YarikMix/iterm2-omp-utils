# Project launcher reference

## Candidate and schema

Use Python3.11+ with official SDK, zsh and authorized API. Require typed launcher
inventory/component capability, not an exact iTerm version. Keep the selected
absolute interpreter in `ITERM2_UTILS_PYTHON`; no automatic install/permissions.
Read fresh `resolve_paths()` and current `state.load(data/receipt.json)` locally.

```json
{"profiles":["Profile A"],"projects":[{"id":"project-a","name":"Project A","path":"/tmp/project-a"}]}
```

Fictional example; actual paths are existing absolute directories. Both lists
are nonempty; unique profile names/ids/names/physical paths, correct types and
no unknown/duplicate fields or controls. Keep profile list, ids, ordering and
receipt parent unless explicitly changed. Missing-record removal/repeated add
is a no-op; resolve exact id, unique name, then normalized path. Ambiguity needs
a choice. Rename/path change retains id/position and therefore retained GUIDs.

No receipt plus manual/foreign panel or incomplete inventory blocks first
install; no import/adoption. With ownership, start from the fresh installed
0600 config if original source disappeared. Write a new private0600 candidate,
not the installed file. Save receipt/config fingerprints, compare before apply;
concurrent change invalidates the preview and stale argv, not the user's edit.

## Commands

Use the receipt/request omp storage and parent, not an agent selector. Resolve
storage with the shared native resolver, respecting explicit profile and its
environment/directory overrides. Replace NAME/CONFIG with separately quoted argv.

```sh
"$ITERM2_UTILS_PYTHON" -m iterm2_utils plan --features project-launcher --omp-profile work --parent-profile NAME --project-launcher-config CONFIG --json
"$ITERM2_UTILS_PYTHON" -m iterm2_utils install --features project-launcher --omp-profile work --parent-profile NAME --project-launcher-config CONFIG --dry-run --json
"$ITERM2_UTILS_PYTHON" -m iterm2_utils install --features project-launcher --omp-profile work --parent-profile NAME --project-launcher-config CONFIG --json
"$ITERM2_UTILS_PYTHON" -m iterm2_utils doctor --json
```

Remove the last project by uninstalling only this feature, no empty config:

```sh
"$ITERM2_UTILS_PYTHON" -m iterm2_utils uninstall --features project-launcher --dry-run --json
"$ITERM2_UTILS_PYTHON" -m iterm2_utils uninstall --features project-launcher --json
```

For one removal preserve all other projects in the candidate. `update` has no
config flag; it reuses owned copy. Unrelated features and shared dependencies
remain. Buttons use action27/version2 and ordinary login shell, never implicitly
launch omp. Explicit agent launch is a separate authorized operation.

## Safety and evidence

A failed dry-run/doctor blocks that operation. Exact GUID ownership outranks
matching display names. Preserve foreign components/advanced fields, original
inverses, default/surviving references and live/buried session references.
Incomplete inventory is not zero references. Do not retire referenced profiles,
close sessions/folders, force overwrite, adopt foreign panels or use direct GUI/
SDK mutation. An unknown native write retains durable CLI journal; recover that
existing journal before any further mutation, never immediately retry it.

Delete temporary candidate only after verified success; retain for unknown
first native write, interrupted/failed recovery, or conflict requiring resolution.
Report only its path, not its contents. Native readback is not visual/click
acceptance: actual Bottom/order/same-window active shell/cwd tests remain separate.
Missing folders later cause native warning/home; Profiles works in narrow windows.
