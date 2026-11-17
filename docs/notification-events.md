# Native omp notification policy

`notifications` is independent of `status`. The package configures only
`completion.notify: on` and `error.notify: off` in the selected omp profile.
Explicit `notify_errors` changes the latter to `on`. These are native **string**
enums, not booleans. No terminal-notifier, daemon, hook, duplicate lifecycle
callback, custom deduplication cache or notification click dispatcher is installed.
omp's native OSC 9 implementation controls delivery.

Address-owned changes preserve local presence/value inverses and foreign
settings/comments. Matching foreign values are reused without ownership.
Changed owned values remain conflicts during update/uninstall. An independent
later feature install preserves the recorded notification policy.

The required receiver is feature-specific: missing OSC 9 evidence does not
block status, ordinary shell or unrelated checkpoints. Versions are diagnostic,
not exact-version rejection rules. No old executable or `config get/list`
probe is used. Bun is required only to parse/transform selected native YAML
addresses, never to open an ordinary shell.

`native_notifications` remains pending until real native completion/error
behavior is verified in a fresh selected-profile main TUI. Local YAML and a
successful terminal API/MCP probe do not establish effective project/provider/
overlay settings, one visible banner, OS notification permission or foreground
policy. Fixtures do not establish live acceptance. All execution and real
banner/keyboard/receiver acceptance remain NOT RUN until Task10.
