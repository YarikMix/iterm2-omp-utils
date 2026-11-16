# Feature choices and dependencies

| Feature | Result and boundary | Additional dependency |
| --- | --- | --- |
| `clipboard` | Terminal selection and native Cmd+C; only selected `CopySelection=false` | Existing selected parent profile |
| `status` | omp native `terminal.programStatus: true`, OSC 7501, no second writer | omp, Bun for native YAML; receiver evidence, live acceptance |
| `notifications` | Native completion-on/error-off; errors only by explicit opt-in | omp, Bun for native YAML; OSC 9 receiver evidence |
| `restore` | Native picker / exact-file resume, never latest/fork fallback | omp with `--resume`; identity/history acceptance separately |
| `mcp` | One owned `mcpServers.iterm2-observe` in the selected omp `mcp.json` | uvx; server Python >=3.12; authorized iTerm2 API |
| `shell` | Official zsh command marks/navigation, no agent wrapper | zsh and iTerm2 only |
| `shortcuts` | Selected RU paste and Alt+Enter newline; native resume binding | Parent profile; Bun for selected native binding edits (not Ctrl+Q preservation) |
| `project-launcher` | Project buttons create shell tabs, never implicitly start omp | Private JSON, supported native schema, Python >=3.11 with SDK/API |
| `appearance` | Repository color/icon, ordinary cd/reset and explicit terminal guards | Selected Python >=3.11 with SDK/API; retained identity payload |

All nine features remain explicit. Bootstrap selects none and probes no agent.
One omp profile is selected independently of the iTerm2 parent profile. Native
YAML edits retain neighbours and comments with receipt/address/file CAS.
No native `config get/list` read probe starts initialization or migrations.
Version strings are diagnostic; capability/schema evidence governs each feature.

The dedicated `iterm2-utils:omp` profile inherits the chosen parent appearance,
but explicitly replaces the parent keyboard map and startup command. It has no
automatic `&bun` or agent-name matching: select it explicitly when launching omp.
Clipboard never sends Cmd+C as Ctrl+C; Ctrl+C remains omp clear/cancel. Only the
clipboard feature changes shared `CopySelection`; shortcuts alone leave it alone.
Clipboard/shortcut discovery also detects the optional selected Python/SDK used
to prove profiles unreferenced before retirement. Missing inventory support
prevents unsafe deletion, not ordinary shell/bootstrap or clipboard installation.

`alt-enter` sends LF/Ctrl+J, never ESC+CR. `ctrl-v-ru` normalizes only the physical
RU paste key to native Ctrl+V. `ctrl-q` explicitly retains native follow-up/tool
approval; no double-Ctrl+C mapping is installed. `resume` requires an explicit
`--resume-key`, checks known native/default and inherited user-binding collisions,
and edits literal `app.session.resume`, never injecting `/resume` text. New
upstream default bindings and effective overlays still require live acceptance.
Adding another shortcut preserves a recorded resume key unless resume itself is
explicitly selected again. Binding collisions ignore modifier order and case in
both planning and the transactional staging recheck.

Selected newline/paste normalizations preserve inherited native alternatives and
add only the required Ctrl+J/Ctrl+V action binding. Cross-action collisions block
the shortcut instead of delivering a different native action.

MCP pins `uvx --with 'mcp<2' mcp-server-iterm2==0.1.1`. uvx may fetch its separate
Python >=3.12 runtime. Preserve other servers/root fields and foreign identical
entries without adoption; mismatched collisions block that feature only.

Native status/notification/keyboard/restore checkpoints remain pending after
storage writes. API connectivity is not effective omp config, native OSC
delivery, banner or keyboard acceptance. Unknown receiver evidence never falls
back to hooks. Migration retains unresolved historical writers as blockers;
only explicitly selected independent features can commit.

Transferred unchanged appearance/launcher configurations can be reused from
their exact resources without an original external JSON. Transfer alone does
not mark a feature installed. Existing sessions and referenced GUIDs retain
the original safety guards and are never closed by installation.


## Repository appearance (opt-in feature)

Only select `appearance` when requested; bootstrap selects none. First plan/install
requires `--appearance-config /path/to/rules.json`, with this strict schema:

```json
{"projects": [{"root": "/path/to/repo", "color": "#65A85A", "icon": "android-mail"}]}
```

Only `projects` at the top level; a nonempty list of objects containing exactly
`root`, `color`, `icon`. Root is absolute, color is `#RRGGBB`, icon is one of
`ios`, `android`, `kotlett`, `ios-mail`, `ios-cloud`, `android-mail`, `android-cloud`,
`chrome-mail`, `chrome-cloud` (nine builtins), or an absolute custom `.png` path. PNG limits: 16 MiB source, 4096 pixels per side,
128 MiB decoded data. No URLs or evaluated shell text. Most specific physical
root wins; duplicate physical roots are rejected. Unavailable external targets
are not created/scanned and do not apply. Never publish personal roots/rules.

Plan/dry-run validate files and the selected interpreter's `iterm2` import without
calling the API. Maintain an absolute `ITERM2_UTILS_PYTHON` override on subsequent
setup commands when choosing a nondefault existing Python. No startup pip or
image download. Install copies normalized rules and content-addressed custom PNGs
outside immutable runtime; all nine builtins ship offline as transparent 128×128
PNGs with matching SVG sources. The six Mail/Cloud composites use variant B:
larger platform, square service badge at bottom right. Mail is white @ on blue,
Cloud is the branded white contour on blue, and web pairs use official full-color
Chrome. The ios mark is now light Apple #E6F4FF with its leaf and bite; ios-mail
and ios-cloud retain their existing service badges. Android/kotlett and the other
pairs are unchanged; four mobile pair names are retained. There is no standalone chrome builtin. THIRD_PARTY_NOTICES.md records
public sources, transformations and brand ownership separately from MIT code and
original package illustrations. Runtime survives removal of checkout/original JSON/PNG. Install
without a new JSON reuses owned rules; explicit new JSON replaces the owned set.
Update needs no original source. Changed/foreign values remain conflicts.

Use the ordinary plan/install/doctor/update/uninstall CLI workflow. Read pending
`appearance_api` and follow ui.md; successful read-only API access does not prove
color/icon rendering. Reconcile alone clears its API checkpoint. No status,
notifications, MCP or command marks are enabled implicitly.

The physical calling shell cwd determines startup and ordinary cd appearance.
Main-session identity integration is distinct from configuration installation.
Registered roots/subdirectories apply their pair; cd outside all rules
disables base/light/dark use-color and hides the custom icon (Icon=0, empty path)
without a default RGB. This updates existing appearance without a flag/schema.
The native zsh chpwd hook registers once, preserves foreign hooks/function and
targets only its owning interactive iTerm2 shell. Model subprocesses and
noninteractive shells cannot recolor the tab. Rapid cd cancels earlier helpers;
API failure cannot fail a successful cd. Service commands do not apply a pair.
Only session tab color/use-color and custom icon/mode change; background,
Default/profile/title stay intact. A bounded observer handles APS for
launch/return; no daemon, polling or permanent observer is added. New cd/reset,
APS/theme transitions and readability remain live pending. tmux is unsupported;
SSH has no new acceptance claim.
Uninstall removes only unchanged owned appearance resources, keeps shared
consumers, and does not reset/restart open tabs. Old custom hash copies remain
owned until uninstall; an empty config object may remain after removal. New
generated startup omits appearance source; running shells are not changed remotely.

Apple-image acceptance was verified on 2026-11-02 for both iOS service pairs in a
normal-size native dark-theme tabbar, ordinary cd into roots/subdirectories and
outside reset. Selected installation preserved all seven rules. Standalone ios
was checked in asset tests/contact sheets; unchanged pairs retain their historical
acceptance. Actual theme switching and fresh Codex/APS/restore runs were not repeated
for this artwork change; see docs/compatibility.md for the precise scope.


## Project launcher (ninth opt-in feature)

Only select `project-launcher` explicitly. First plan/install requires
`--project-launcher-config /path/to/projects.json`. Never publish real project
names, paths, inventory or local JSON. Fictional example:

```json
{"profiles":["Default"],"projects":[{"id":"project-a","name":"Project A","path":"/path/to/project-a"},{"id":"project-b","name":"Project B","path":"/path/to/project-b"}]}
```

Both lists are nonempty. Existing target profile names, project ids and button
names must be unique; paths are existing absolute directories, never commands.
Unknown/duplicate fields, control characters and wrong types block writes.
`--parent-profile Default` chooses an existing ordinary shell parent by verified
GUID; project profiles override inherited custom commands with login shell.
Buttons use native action27 and open a new active tab in the same window on
every click. Existing foreign layout components/advanced settings are preserved.

Use macOS/zsh, a supported native schema and an existing Python3.11+ with official
`iterm2`, selected with ITERM2_UTILS_PYTHON where needed. Enable/authorize Python
API manually. No SDK installation or app launch happens automatically.
Bootstrap selects none. To add/change projects, edit the private source and
repeat plan/install with the flag; stable ids preserve GUIDs. Update/repeat
without a flag reads an owned0600 copy even after source removal. Plan/dry-run
write nothing; installed files and grouped native panel fields use CAS.

Shared consumers are explicit feature names. Partial uninstall preserves
another consumer. Full uninstall restores only confirmed installed bar fields
before deleting profile targets. Late edits, external/hidden references,
live/buried profile sessions or unavailable inventory retain resources/receipt;
do not erase foreign buttons or close processes automatically. Resolve the
local conflict and retry. An uncertain native write retains durable recovery
intent without immediate retry.

Native readback and fixtures do not establish visual acceptance. The new CLI
live install/update/uninstall and actual clicks remain unverified. If a folder
later disappears iTerm2 warns and opens home. Narrow windows may hide buttons;
Profiles is the fallback. No browser/localhost is needed. Full package guide:
`docs/project-launcher.md` in the checkout/release (not copied by skill bootstrap).
