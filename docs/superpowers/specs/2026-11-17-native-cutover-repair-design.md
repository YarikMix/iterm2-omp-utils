# Native cutover repair — design addendum

Status: proposed; user authorized the additional corrective stage and its approach, not implementation before this design/plan gate. Original authority: `2026-11-16-omp-only-design.md`. This addendum changes only the runtime namespace and mixed-bootstrap migration cases below; all original safety, selected-feature, native-evidence and no-version-pin constraints remain binding.

## Intent and observed state

Finish the approved omp-only cutover without breaking existing terminal sessions or treating a retained historical path as an active omp writer. Actual native application, not a new synthetic repro, exposed both cases after source commit `245b2ea` and its successful scoped review. Documentation-only continuation is `49f5d288d8555627be5806780a216e82d53fc794`.

The authorized personal migration converted four receipt scopes and removed exact unchanged owned entries. Native status/notifications/appearance checkpoints then failed with `legacy_writer_conflict`. The sole conflicting retained address is the old `data/current` symlink, whose recorded owners include historical Codex features and shared runtime. Immutable release files were already excluded as writers. The current feature receipt has no installed native features, one transferred appearance resource, and historical cleanup debt; no native status/notification setting was written.

A mixed Codex+omp launch-bootstrap receipt was treated as wholly retired. Its owned files in both destinations were removed; the surviving empty omp directory then correctly failed the bootstrap's foreign-directory guard. The actual installation was resolved without forcing/adopting files: atomic removal of only empty package directories, then normal bootstrap. All three current omp bundles are installed and all nine files match source. The source migration must prevent this regression for future mixed receipts.

## Approaches and decision

1. **Chosen proposal: independent active omp pointer.** Publish and consume `data/current-omp`, leaving historical `data/current` and old releases untouched during this stage and normal active lifecycle. Use the same immutable-release producer, transaction engine, resource ownership, original inverses and CAS. No second installer or compatibility launch path.
2. Repoint/transfer old `current` into active ownership. Smaller superficially, but it changes the path seen by unexamined old consumers. Known retained zsh helpers pin resolved roots, but that does not prove every older/cached caller safe. Reject this risk.
3. Wait for/close existing sessions to retire all old runtime. Reject as a prerequisite for native installation: the approved cutover must not close/restart user sessions or require an empty iTerm inventory merely to configure independent omp features.

For bootstrap, preserve the selected omp copy per proven resource address rather than weakening the foreign-directory guard or checking only whether the receipt agent set contains omp. No global adoption/force option.

This is one bounded corrective implementation stage with regression evidence and one focused review, explicitly authorized after the original final wave. It is not another broad audit or an implicit extension of the closed fix loop.

## Goals, non-goals and anti-goals

Goals:
- A retained old pointer/release does not block otherwise valid independent omp checkpoints that use the new active namespace.
- Active shell, appearance discovery, identity extension and installed helper paths agree on `current-omp`.
- Selected omp files in mixed bootstrap receipts retain ownership and original inverses through migration, then refresh through the ordinary bootstrap transaction.
- All changes remain resumable, profile-scoped and guarded against changed/foreign data.

Non-goals: new features, flags, configuration system, receipt-version bump, another agent consumer, changes to model/endpoint/auth/approval policy, runtime fallback to old `current`, GUI automation, automatic installation/application permission, or another whole-branch review.

Anti-goals: deleting/repointing old `current` to get a pass; adopting a dangling/foreign active pointer; assigning ownership from directory names alone; silently deleting other-profile/wrong-bundle resources; treating configuration writes or fixtures as live acceptance.

## Active runtime namespace

The active runtime link basename is **`current-omp`** (builder's choice). There is currently no `Paths.current` field/property: do not expand the shared Paths constructor merely to rename the link. Follow the existing construction pattern and migrate every actual producer/consumer.

Known reach:
- `features/shell.py`: immutable payload publication, generated shell sourcing, and the installed profile identity extension's Python-helper path.
- `discovery.live_appearance`: helper invocation through the active link.
- Installed-helper, shell, lifecycle, payload, identity and extraction fixtures; current-product layout docs.

Keep package-relative `config/omp.py` parser lookup, generic symlink/CAS engine behavior, unrelated variables named current, and historical data/fixtures unchanged. Release content addressing/collision refusal, selected Python, exact TTY/process proof, original inverses and same-device safety remain intact. No source/package fallback through legacy `current` if the active helper is missing.

An unowned, changed or dangling `current-omp` remains a conflict under existing ownership rules. Existing native-v2 resources unexpectedly owning the old stable path must not silently acquire cleanup/repoint authority: preserve them and fail closed if a safe existing transition cannot be proved. The actual authorized installation has no such active runtime resource. Do not invent a new v2 migration schema or a compatibility shim for an unproved layout.

## Historical runtime boundary

Continue recognizing `data/current` and historical release addresses as historical data. During the corrective stage and active install/update/uninstall, preserve their bytes, link target, original inverses and retryable cleanup metadata. Their existence alone is not evidence of an active competing writer once the active product uses a disjoint pointer. Actual remaining historical hooks/zsh/config writers must still block their conflicting features; do not blanket-ignore legacy debt.

This does **not** cancel the original separately authorized explicit cleanup contract. A later explicit migration may retire historical runtime only after the original reference/detachment/inventory guards prove it safe. Do not weaken those guards or reinterpret journal addresses. Normal active lifecycle must not gain deletion authority over old runtime merely because it now uses `current-omp`.

## Per-resource mixed-bootstrap preservation

Retain independent scopes for iterm2-setup, iterm2-launch and iterm2-projects. Before transferring a resource, preserve existing path-provenance validation, unchanged installed-value check and original inverse.

The selected omp destination is the **specific scope's bundle** under resolved `OmpProfile.agent_dir/skills/BUNDLE`; broad membership under all skills is insufficient. Preserve unchanged historical files only with provable omp bootstrap ownership and an allowed bundle-relative target. Bare `bootstrap-skill` plus a compatible recorded agent/destination relationship, or supported omp-qualified ownership, must be handled without discarding the original before/installed values. Current bootstrap lookup requires the canonical bare owner; normalize only proven supported omp ownership.

Recognized exact Codex/Claude copies follow the existing unchanged-address inverse cleanup. Other omp profiles, contradictory qualified owners, wrong bundles, ambiguous destinations and foreign resources remain unresolved/retryable rather than being inferred retired or adopted. Selection alone cannot classify every resource: recovery envelopes can retain owners outside their remaining selection. When legacy schema lacks destination provenance, preserve the conflict, not guessed deletion.

Changed selected omp files keep their original historical record. After explicit user resolution, retry transfers ownership without deleting/recreating the directory. Keep `skill_install.build` foreign-directory, symlink, changed-file and profile-change guards. Do not make empty directories globally adoptable. Preserve independent recovery journals, fingerprint revalidation, source intent and original uninstall behavior.

## Observable verification

No unchanged failed personal apply is rerun to confirm it. Add isolated regressions using actual observed state shapes, not source-text checks:
- Legacy current plus retained release data survives corrective migration and native install/update/uninstall; new active deployment uses only current-omp. Old hooks/other true writers still block appropriately; cleanup is not silently completed.
- Active dangling/foreign pointer refuses adoption. Generated shell and installed default identity/helper layout agree. Extracted install remains usable after extracted sources are removed.
- Mixed bootstrap for all three bundles preserves the selected omp copy and its nonempty original inverse, removes only proven retired copies, and can immediately perform normal bootstrap without manual directory cleanup.
- Bare/qualified ownership, changed-file retry, selected named profile, wrong-bundle/other-profile/ambiguous targets and independent receipt/journal cases preserve their safety contracts.

Run only concretely affected Python/Bun/zsh/validator/extraction checks after the complete patch, under the existing private pre-import environment. Exact commands, timing and evidence belong in the implementation plan. No real settings/auth/API/GUI during development checks. Preserve actual RED/GREEN and distributed rerun accounting; do not re-run unrelated green suites.

After focused source review, show a fresh exact personal preview and request permission for any changed application target. Notification storage must be described accurately as `completion.notify='on'` / `error.notify='off'`, not literal booleans. Test tabs, model turns, clipboard and actual native surfaces still need their own scoped authorization. Rebuild the release from final accepted source; the earlier archive is historical.

## Left to the builder

Choose the smallest existing-pattern implementation, exact internal placement of pointer construction/classification and the affected test module subset from the verified reach map. Do not introduce new abstractions or remove uncertainty by assuming legacy provenance. Escalate a real source/contract contradiction rather than weakening a guard. Preserve the original full Task10 acceptance obligations and explicitly report every unperformed native check.
