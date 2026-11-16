# Pending UI and native acceptance

Use the actual `ui` codes returned by CLI. Installed files, an available UI
binary or the user's “done” do not clear a checkpoint. A connected permitted UI
tool may navigate ordinary controls; absent/disconnected/denied access requires
manual instructions. Never install tooling, change TCC, automate system dialogs
or try another API/automation path after denial.

Python API: iTerm2 → Settings… (Настройки…) → General (Основные) → Magic →
Enable Python API (Включить Python API). The label may remain English. The human
handles authorization. For the returned code run
`python3 -m iterm2_utils reconcile --step CODE --json` and
`python3 -m iterm2_utils doctor --live --json`; failed proof stays pending.

For appearance the API code is `appearance_api`; reconcile from an explicit
consistent local iTerm2 session outside tmux. This probe does not change
color/icon and is not rendered acceptance. For MCP use the returned
`mcp_authorize` code; SDK readiness alone is not a server connection.

Native omp status (`terminal.programStatus`, OSC7501), notifications (OSC9),
resume and shortcuts require their actual effective/event/keyboard acceptance.
Storage writes or status reads never establish working/blocked/done/error,
one completion banner or EN/RU key delivery. No competing hooks/daemon/menu
integration is installed to fill a missing capability. Ctrl+Q remains native;
Cmd+C copies terminal selection, Ctrl+C is clear/cancel.

A new profile can be opened from Profiles (Профили). Applying selected settings
to an existing tab is Session (Сеанс) → Edit Session… (Изменить сеанс…) → Use
Selected Settings (Использовать выбранные настройки), only when the user asks.
Never switch/restart another tab automatically. A fresh session may be needed
to load changed runtime/MCP; the human starts it.

Before authorized own temporary tabs, warn that they appear. Verify shell and
explicit omp launch/return/resume, main-vs-child foreground identity and APS.
Ordinary cd into each registered root/subdirectory applies its exact pair;
switching roots changes both; outside resets base/light/dark use-color=false,
Icon=0 and empty path without default RGB. Include rapid A→B→outside, no-match,
manual settings and actual themes/readability. Do not create missing roots,
disconnect disks, change neighbouring tabs/Default, or close user processes.
Close only your own authorized test tabs and undo temporary settings you changed.

Project launcher acceptance separately checks chosen profiles, Bottom position,
button order, same-window new active login-shell tabs and cwd. Repeated clicks
create more tabs; missing folders warn/fall back home. Narrow window Profiles
is a fallback. Typed API readback and fixtures do not prove rendering/clicks.
Report actual checks, unperformed checks and permission blockers independently.
