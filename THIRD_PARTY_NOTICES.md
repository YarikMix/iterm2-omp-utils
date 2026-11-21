# Third-party notices

`iterm2_utils/mcp/` adapts the observe/annotation tools, session resolution,
output cursors, error types and cookie request from Rob Trame's
[`mcp-server-iterm2` v0.1.1](https://github.com/r6e/mcp-server-iterm2/tree/v0.1.1)
(Copyright © 2026 Rob Trame, MIT). The original permission and copyright text is
preserved in `vendor/mcp_server_iterm2/LICENSE`. Connection ownership and
authorization/registration were replaced locally: lazy serialized generations,
bounded teardown, no background reconnect or command replay, and sanitized errors.
The optional `iterm2` and `mcp` SDKs are runtime dependencies, not vendored code.
The public allowlist ships the adapted `iterm2_utils/mcp/` Python sources,
`runtime/iterm2_mcp_entry.py`, `runtime/omp_iterm2_projects.ts`, and the original
MIT license above. The same license and this notice ship inside immutable
installed MCP releases. `sources.lock.json` records the v0.1.1 upstream license
URL, tag and SHA-256; locally changed ownership/worker code is not represented
as unmodified upstream source. MCP SDK dependencies are probed, never downloaded
or bundled by the installer.

`vendor/shell_integration/iterm2_shell_integration.zsh` is the unmodified official
iTerm2 zsh integration from gnachman/iTerm2, tag v3.7.6, Git blob
`efb57443f879239795411bcf076f38b4d1008b0f`.
Its original GPL-2.0-or-later license header is preserved verbatim. The accompanying
`vendor/shell_integration/LICENSE` is the verbatim upstream GPL version 2 text.
This vendored component remains under its own GPL license, separate from the
package's original MIT code. Source URLs, exact bytes' SHA-256 digests, tag and
blob identities are recorded in `sources.lock.json`; run
`python3 tools/check_sources.py` to verify the vendored bytes.

The original installer, terminal/identity helpers and skill bundles are covered
by this repository's [MIT license](LICENSE). Retired agent hook, notification and
restorer implementations are not distributed. Historical migration fixtures
contain inert receipted hook definitions and inverses, not executable snapshots.

`runtime/assets/appearance/` contains nine named SVG/PNG pairs. The robot (`android`) and cutlet (`kotlett`) are original illustrations
created for this repository and distributed under its MIT license (LICENSE).
The six service/platform composites reuse the Apple mark or robot, or the official
Chrome logo, with branded Mail or Cloud artwork from these public sources:

| Artwork | Public upstream SVG | Upstream SHA256 |
| --- | --- | --- |
| Apple | https://www.apple.com/ (navigation inline SVG, extracted SVG hash) | `173a4aceb67e416738f3af19eeda9de484cac388914881915dc94e4f6ce77687` |
| Mail `@` | https://cloud.imgsmail.ru/cloud.mail.ru/hashes/img/portal-header/38ee4afd7a08350c7d70.svg | `8797246440d02769af6ae58cf3fdd90f9ce56858f02098a0dee5a8b659129897` |
| Cloud | https://cloud.imgsmail.ru/cloud.mail.ru/hashes/img/54cbc3d30f0b1da1d208.svg | `71706ae50083d481d84e172308b858abba2979b2f90dff08d6d2ee0da0ffb333` |
| Google Chrome | https://www.google.com/chrome/static/images/chrome-logo-m100.svg | `1357dd965397a99cbc937ddd2345a9897d527f7229c8b0f2aeebac97680cc66d` |

Mail and Cloud artwork and marks belong to Mail / VK; Chrome artwork and marks
belong to Google. Apple artwork and marks belong to Apple Inc.; `ios`,
`ios-mail` and `ios-cloud` derive from this third-party Apple artwork. These upstream graphics are third-party brand artwork, not
original package drawings, and are not covered by this repository's MIT grant.
No separate license grant for that artwork is asserted here.

Apple transformation: preserve the upstream path and aspect ratio, crop the
viewBox to `0 11 14 18` to remove navigation whitespace, and recolor `#E6F4FF`.
The standalone mark fits the transparent 128×128 canvas; iOS composites place it
at x=-6,y=-3,width=110,height=118 behind the existing service badges. The hash
above identifies the extracted SVG, not the full Apple HTML page.

Other transformations: only the separate `@` path from the Mail 135×30 wordmark is
used (the 0..30 area, without wordmark text), recolored white and placed on a
rounded `#0077FF` square. Cloud's rounded blue square and white contour, and
Chrome's colored paths and gradients, are scaled proportionally. Each composite
places the larger platform behind a 74×74 service badge at the bottom right
of the transparent 128×128 canvas; all paths and gradients are inline in SVG.
PNG files were rendered from the accompanying SVG with librsvg `rsvg-convert`;
the renderer is a developer tool and is not bundled or required for installation
or shell startup. No internal-repository artwork is included.

All nine named PNG/SVG pairs ship in the public archive and in immutable runtime
releases selected for appearance; installation and shell startup do not download
images. `sources.lock.json` pins their distributed bytes to repository snapshot
`cd1ffe132416f7d1beba5ca51690af0cbedf128c`; the table above identifies the
original brand sources and transformations. `LicenseRef-Third-Party-Brand-Artwork`
is an attribution label, **not** an additional license grant.

`vendor/yaml/` contains the unmodified JavaScript `dist/` distributable,
`package.json` and ISC license from Eemeli Aro's `yaml` 2.9.1 npm release
([upstream](https://github.com/eemeli/yaml/tree/v2.9.1),
[document/CST API](https://eemeli.org/yaml/)). The release identifies commit
`1440ecd3d1bff41e4ac399f8f6839e810328bd16`. Its npm archive's SHA-512 integrity
was checked before extraction; archive SHA-256, integrity, member names and each
shipped member's SHA-256 are recorded in `sources.lock.json`. The original
copyright and permission text is preserved verbatim in `vendor/yaml/LICENSE`.
No parser source was modified and no dependency installation is performed.
Only the document API is used by `runtime/omp_config.ts`: duplicate/ambiguous
documents and unsupported tags are refused; alias expansion and input/output
sizes are bounded. Selected values use source ranges where possible, with
document edits for insertion/removal. Anchored or merged owned paths are
rejected rather than changing foreign aliases or inherited content.
