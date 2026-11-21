#!/usr/bin/env python3
"""Validate only explicitly shipped files; never print offending content."""
import hashlib
import json
from pathlib import Path
import re
import sys

# Deliberately explicit: unknown files are never added by glob, gitignore or git.
EXPORT_FILES = (
    'AGENTS.md',
    'CHANGELOG.md',
    'LICENSE',
    'README.md',
    'THIRD_PARTY_NOTICES.md',
    'docs/compatibility.md',
    'docs/native-status-events.md',
    'docs/notification-events.md',
    'docs/omp-identity.md',
    'docs/omp-launch.md',
    'docs/repo-appearance.md',
    'docs/project-launcher.md',
    'docs/examples/project-launcher.html',
    'iterm2_utils/__init__.py',
    'iterm2_utils/__main__.py',
    'iterm2_utils/cli.py',
    'iterm2_utils/commands.py',
    'iterm2_utils/config/__init__.py',
    'iterm2_utils/config/jsonfile.py',
    'iterm2_utils/config/iterm.py',
    'iterm2_utils/config/legacy_mcp.py',
    'iterm2_utils/config/mcp.py',
    'iterm2_utils/config/preferences.py',
    'iterm2_utils/config/tomlfile.py',
    'iterm2_utils/config/zshrc.py',
    'iterm2_utils/discovery.py',
    'iterm2_utils/engine.py',
    'iterm2_utils/features/__init__.py',
    'iterm2_utils/features/appearance.py',
    'iterm2_utils/features/mcp.py',
    'iterm2_utils/features/notifications.py',
    'iterm2_utils/features/profiles.py',
    'iterm2_utils/features/project_launcher.py',
    'iterm2_utils/features/restore.py',
    'iterm2_utils/features/shell.py',
    'iterm2_utils/features/status.py',
    'iterm2_utils/lifecycle.py',
    'iterm2_utils/launch.py',
    'iterm2_utils/launch_api.py',
    'iterm2_utils/launch_checks.py',
    'iterm2_utils/migration.py',
    'iterm2_utils/legacy_state.py',
    'iterm2_utils/models.py',
    'iterm2_utils/omp_profile.py',
    'iterm2_utils/omp_sessions.py',
    'iterm2_utils/planner.py',
    'iterm2_utils/profile_api.py',
    'iterm2_utils/skill_install.py',
    'iterm2_utils/state.py',
    'iterm2_utils/terminal.py',
    'iterm2_utils/project_edits.py',
    'iterm2_utils/project_handoff.py',
    'iterm2_utils/mcp/__init__.py',
    'iterm2_utils/mcp/__main__.py',
    'iterm2_utils/mcp/binding.py',
    'iterm2_utils/mcp/connection.py',
    'iterm2_utils/mcp/cookie.py',
    'iterm2_utils/mcp/errors.py',
    'iterm2_utils/mcp/launch_tools.py',
    'iterm2_utils/mcp/launch_worker.py',
    'iterm2_utils/mcp/observe.py',
    'iterm2_utils/mcp/output_cursor.py',
    'iterm2_utils/mcp/project_worker.py',
    'iterm2_utils/mcp/server.py',
    'iterm2_utils/mcp/session.py',
    'iterm2_utils/mcp/tools/__init__.py',
    'iterm2_utils/mcp/tools/read.py',
    'iterm2_utils/mcp/tools/write.py',
    'runtime/iterm2_mcp_entry.py',
    'runtime/omp_iterm2_projects.ts',
    'vendor/mcp_server_iterm2/LICENSE',
    'tests/test_mcp_install.py',
    'tests/test_mcp_launch.py',
    'tests/test_mcp_observe.py',
    'tests/test_mcp_project_worker.py',
    'tests/test_mcp_stdio.py',
    'tests/test_project_edits.py',
    'tests/test_omp_iterm2_projects.ts',
    'runtime/assets/appearance/ios.png',
    'runtime/assets/appearance/ios.svg',
    'runtime/assets/appearance/android.png',
    'runtime/assets/appearance/android.svg',
    'runtime/assets/appearance/kotlett.png',
    'runtime/assets/appearance/kotlett.svg',
    'runtime/assets/appearance/ios-mail.png',
    'runtime/assets/appearance/ios-mail.svg',
    'runtime/assets/appearance/ios-cloud.png',
    'runtime/assets/appearance/ios-cloud.svg',
    'runtime/assets/appearance/android-mail.png',
    'runtime/assets/appearance/android-mail.svg',
    'runtime/assets/appearance/android-cloud.png',
    'runtime/assets/appearance/android-cloud.svg',
    'runtime/assets/appearance/chrome-mail.png',
    'runtime/assets/appearance/chrome-mail.svg',
    'runtime/assets/appearance/chrome-cloud.png',
    'runtime/assets/appearance/chrome-cloud.svg',
    'runtime/appearance.py',
    'runtime/appearance.zsh',
    'runtime/omp_identity.ts',
    'runtime/terminal_identity.py',
    'skills/iterm2-launch/SKILL.md',
    'skills/iterm2-launch/references/handoff.md',
    'skills/iterm2-launch/references/resume.md',
    'skills/iterm2-projects/SKILL.md',
    'skills/iterm2-projects/references/projects.md',
    'skills/iterm2-setup/SKILL.md',
    'skills/iterm2-setup/references/features.md',
    'skills/iterm2-setup/references/troubleshooting.md',
    'skills/iterm2-setup/references/ui.md',
    'sources.lock.json',
    'tests/__init__.py',
    'tests/fixtures/beta1-hooks.json',
    'tests/support.py',
    'tests/native_features_support.py',
    'tests/test_agent_workflow.py',
    'tests/test_appearance_feature.py',
    'tests/test_appearance_rules.py',
    'tests/test_appearance_runtime.py',
    'tests/test_appearance_shell.zsh',
    'tests/test_cli.py',
    'tests/test_config.py',
    'tests/test_discovery.py',
    'tests/test_engine.py',
    'tests/test_export.py',
    'tests/test_final_fixes.py',
    'tests/test_legacy_state.py',
    'tests/test_lifecycle.py',
    'tests/test_launch.py',
    'tests/test_launch_api.py',
    'tests/test_launch_checks.py',
    'tests/test_mcp.py',
    'tests/test_migration.py',
    'tests/test_native_status_migration.py',
    'tests/test_notifications_feature.py',
    'tests/test_omp_identity.ts',
    'tests/test_omp_identity_install.py',
    'tests/test_omp_profile.py',
    'tests/test_omp_sessions.py',
    'tests/test_omp_terminal_identity.py',
    'tests/test_payload.py',
    'tests/test_pending_ui.py',
    'tests/test_profiles.py',
    'tests/test_profile_api.py',
    'tests/test_project_launcher.py',
    'tests/test_restore_feature.py',
    'tests/test_selection.py',
    'tests/test_shell.py',
    'tests/test_skill_install.py',
    'tests/test_state.py',
    'tests/test_status_feature.py',
    'tests/test_terminal.py',
    'tools/build_release.py',
    'tools/check_export.py',
    'tools/check_skill.py',
    'tools/check_sources.py',
    'vendor/shell_integration/LICENSE',
    'vendor/shell_integration/iterm2_shell_integration.zsh',
    'iterm2_utils/config/omp.py',
    'runtime/omp_config.ts',
    'tests/test_omp_config.py',
    'tests/test_omp_config.ts',
    'vendor/yaml/LICENSE',
    'vendor/yaml/dist/compose/compose-collection.js',
    'vendor/yaml/dist/compose/compose-doc.js',
    'vendor/yaml/dist/compose/compose-node.js',
    'vendor/yaml/dist/compose/compose-scalar.js',
    'vendor/yaml/dist/compose/composer.js',
    'vendor/yaml/dist/compose/resolve-block-map.js',
    'vendor/yaml/dist/compose/resolve-block-scalar.js',
    'vendor/yaml/dist/compose/resolve-block-seq.js',
    'vendor/yaml/dist/compose/resolve-end.js',
    'vendor/yaml/dist/compose/resolve-flow-collection.js',
    'vendor/yaml/dist/compose/resolve-flow-scalar.js',
    'vendor/yaml/dist/compose/resolve-props.js',
    'vendor/yaml/dist/compose/util-contains-newline.js',
    'vendor/yaml/dist/compose/util-empty-scalar-position.js',
    'vendor/yaml/dist/compose/util-flow-indent-check.js',
    'vendor/yaml/dist/compose/util-map-includes.js',
    'vendor/yaml/dist/doc/Document.js',
    'vendor/yaml/dist/doc/anchors.js',
    'vendor/yaml/dist/doc/applyReviver.js',
    'vendor/yaml/dist/doc/createNode.js',
    'vendor/yaml/dist/doc/directives.js',
    'vendor/yaml/dist/errors.js',
    'vendor/yaml/dist/index.js',
    'vendor/yaml/dist/log.js',
    'vendor/yaml/dist/nodes/Alias.js',
    'vendor/yaml/dist/nodes/Collection.js',
    'vendor/yaml/dist/nodes/Node.js',
    'vendor/yaml/dist/nodes/Pair.js',
    'vendor/yaml/dist/nodes/Scalar.js',
    'vendor/yaml/dist/nodes/YAMLMap.js',
    'vendor/yaml/dist/nodes/YAMLSeq.js',
    'vendor/yaml/dist/nodes/addPairToJSMap.js',
    'vendor/yaml/dist/nodes/identity.js',
    'vendor/yaml/dist/nodes/toJS.js',
    'vendor/yaml/dist/parse/cst-scalar.js',
    'vendor/yaml/dist/parse/cst-stringify.js',
    'vendor/yaml/dist/parse/cst-visit.js',
    'vendor/yaml/dist/parse/cst.js',
    'vendor/yaml/dist/parse/lexer.js',
    'vendor/yaml/dist/parse/line-counter.js',
    'vendor/yaml/dist/parse/parser.js',
    'vendor/yaml/dist/public-api.js',
    'vendor/yaml/dist/schema/Schema.js',
    'vendor/yaml/dist/schema/common/map.js',
    'vendor/yaml/dist/schema/common/null.js',
    'vendor/yaml/dist/schema/common/seq.js',
    'vendor/yaml/dist/schema/common/string.js',
    'vendor/yaml/dist/schema/core/bool.js',
    'vendor/yaml/dist/schema/core/float.js',
    'vendor/yaml/dist/schema/core/int.js',
    'vendor/yaml/dist/schema/core/schema.js',
    'vendor/yaml/dist/schema/json/schema.js',
    'vendor/yaml/dist/schema/tags.js',
    'vendor/yaml/dist/schema/yaml-1.1/binary.js',
    'vendor/yaml/dist/schema/yaml-1.1/bool.js',
    'vendor/yaml/dist/schema/yaml-1.1/float.js',
    'vendor/yaml/dist/schema/yaml-1.1/int.js',
    'vendor/yaml/dist/schema/yaml-1.1/merge.js',
    'vendor/yaml/dist/schema/yaml-1.1/omap.js',
    'vendor/yaml/dist/schema/yaml-1.1/pairs.js',
    'vendor/yaml/dist/schema/yaml-1.1/schema.js',
    'vendor/yaml/dist/schema/yaml-1.1/set.js',
    'vendor/yaml/dist/schema/yaml-1.1/timestamp.js',
    'vendor/yaml/dist/stringify/foldFlowLines.js',
    'vendor/yaml/dist/stringify/stringify.js',
    'vendor/yaml/dist/stringify/stringifyCollection.js',
    'vendor/yaml/dist/stringify/stringifyComment.js',
    'vendor/yaml/dist/stringify/stringifyDocument.js',
    'vendor/yaml/dist/stringify/stringifyNumber.js',
    'vendor/yaml/dist/stringify/stringifyPair.js',
    'vendor/yaml/dist/stringify/stringifyString.js',
    'vendor/yaml/dist/test-events.js',
    'vendor/yaml/dist/util.js',
    'vendor/yaml/dist/visit.js',
    'vendor/yaml/package.json',
)

_PRIVATE = re.compile(
    rb"/(?:Users|home)/[A-Za-z0-9_.-]+|~/(?:\.paiw|\.ai)/|"
    rb"(?<![A-Za-z0-9.-])(?:[A-Za-z0-9_-]+\.)*(?:vk\.team|devmail\.ru|corp\.mail\.ru|codegb\.rustore\.ru)(?=[:/\s\"']|$)",
    re.I,
)
_SHA = re.compile(r"[0-9a-f]{64}")


def check(repo: Path) -> list[str]:
    repo = Path(repo).resolve()
    errors = []
    contents = {}
    seen_paths = set()
    for name in EXPORT_FILES:
        if name in seen_paths:
            errors.append('Duplicate export path: '+name)
            continue
        seen_paths.add(name)
        path = repo/name
        # Reject links in any component, even links pointing back into the tree.
        if any(p.is_symlink() for p in (path, *path.parents) if p != repo.parent):
            errors.append('Symlink in export: '+name)
            continue
        if not path.is_file():
            errors.append('Missing export file: '+name)
            continue
        try:
            content = path.read_bytes()
        except OSError:
            errors.append('Unreadable export file: '+name)
            continue
        contents[name] = content
        if _PRIVATE.search(content):
            errors.append('Private reference in export: '+name)
    try:
        lock = json.loads(contents['sources.lock.json'])
        entries = lock['sources']
        if not isinstance(entries, list) or not entries:
            raise ValueError()
        seen = set()
        for entry in entries:
            name, digest, ref = entry['path'], entry['sha256'], entry['ref']
            if name not in contents or name in seen or not _SHA.fullmatch(digest):
                raise ValueError()
            seen.add(name)
            if not (re.fullmatch(r'[0-9a-f]{40}', ref) or re.fullmatch(r'v[0-9]+(?:\.[0-9]+)+(?:[-.][A-Za-z0-9]+)*', ref)):
                raise ValueError()
            if hashlib.sha256(contents[name]).hexdigest() != digest:
                errors.append('Source digest mismatch: '+name)
            from urllib.parse import urlparse
            if 'url' in entry:
                url = urlparse(entry['url'])
                if url.scheme != 'https' or not url.hostname or url.username or url.password:
                    raise ValueError()
            elif not all(isinstance(entry.get(k), str) and entry[k].strip() for k in ('source','author')):
                raise ValueError()
            if not isinstance(entry.get('license'), str) or not entry['license'].strip():
                raise ValueError()
            if entry.get('license_file') not in contents or entry.get('attribution_file') != 'THIRD_PARTY_NOTICES.md':
                raise ValueError()
            if 'source' in entry and entry.get('license_scope') != 'bundled-port-only':
                raise ValueError()
            if entry.get('transformation') not in (None, 'none') and not any(k in entry for k in ('upstream_sha256','local_snapshot_sha256')):
                raise ValueError()
            if 'source' in entry and 'upstream_sha256' not in entry:
                raise ValueError()
            for field in ('upstream_sha256', 'local_snapshot_sha256'):
                if field in entry and not _SHA.fullmatch(entry[field]):
                    raise ValueError()
        required = {n for n in contents if n.startswith(('vendor/', 'runtime/assets/appearance/'))}
        if not required <= seen:
            errors.append('Missing source provenance')
    except (KeyError, TypeError, ValueError, AttributeError):
        errors.append('Invalid or missing source lock metadata')
    for name in ('LICENSE','THIRD_PARTY_NOTICES.md','vendor/yaml/LICENSE','vendor/shell_integration/LICENSE'):
        if not contents.get(name, b'').strip():
            errors.append('Missing license or attribution: '+name)
    return errors


if __name__ == '__main__':
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    errors = check(root)
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print(f'{len(EXPORT_FILES)} allowlisted files verified; provenance/licenses/private-reference checks passed.')
    raise SystemExit(bool(errors))
