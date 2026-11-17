"""Public beta export is allowlisted, provenance checked and independently usable."""
import hashlib
import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools import build_release, check_export

ROOT = Path(__file__).resolve().parents[1]

IMPORT_AND_BOOTSTRAP = r"""
import contextlib, importlib, io, json, pathlib, socket, sys
from iterm2_utils import cli, state
from iterm2_utils.discovery import resolve_paths
from iterm2_utils.skill_install import _context
from iterm2_utils.models import Context

root = pathlib.Path.cwd().resolve()
home = pathlib.Path.home()
sys.modules['iterm2'] = None  # An unselected SDK must not be imported.
def no_network(*args, **kwargs): raise AssertionError('Unexpected network access')
socket.socket.connect = no_network
for folder in ('iterm2_utils', 'runtime'):
    for path in (root/folder).rglob('*.py'):
        if path.name != '__main__.py':
            module = importlib.import_module('.'.join(path.relative_to(root).with_suffix('').parts))
            assert pathlib.Path(module.__file__).resolve().is_relative_to(root)
for skill in ('iterm2-setup', 'iterm2-launch', 'iterm2-projects'):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = cli.main(['bootstrap-skill', '--skill', skill, '--omp-profile', 'work', '--json'])
    assert code == 0, output.getvalue()
    source = root/'skills'/skill
    target = home/'.omp/profiles/work/agent/skills'/skill
    assert {p.relative_to(target):p.read_bytes() for p in target.rglob('*') if p.is_file()} == {
        p.relative_to(source):p.read_bytes() for p in source.rglob('*') if p.is_file()}
    paths = resolve_paths()
    isolated = _context(Context(paths, {}, {}, frozenset(), {}, {}), skill)
    receipt = state.load(isolated.paths.data/'receipt.json')
    assert receipt.selection.omp_profile.name == 'work'
    assert receipt.selection.features == {'bootstrap-skill'}
assert not (resolve_paths().data/'receipt.json').exists()
assert not any((home/name).exists() for name in ('.codex', '.claude'))
"""

SHELL_INSTALL = r"""
import contextlib, io, json, os, pathlib, plistlib, shutil, socket, subprocess, sys
from unittest.mock import patch
from iterm2_utils import cli, state
from iterm2_utils.discovery import resolve_paths
home = pathlib.Path.home()
root = pathlib.Path.cwd()
sys.modules['iterm2'] = None
def no_network(*args, **kwargs): raise AssertionError('Unexpected network access')
socket.socket.connect = no_network
app = home/'iTerm.app'
(app/'Contents/MacOS').mkdir(parents=True)
(app/'Contents/Info.plist').write_bytes(plistlib.dumps({
    'CFBundleIdentifier':'com.googlecode.iterm2', 'CFBundleExecutable':'iTerm2',
    'CFBundleShortVersionString':'99.0.0'}))
binary = app/'Contents/MacOS/iTerm2'
binary.write_text('#!/bin/sh\nexit 97\n')
binary.chmod(0o700)
os.environ['ITERM2_APP'] = str(app)
calls = []
class Runner:
    def run(self, argv, **kwargs):
        calls.append(argv)
        assert argv == [shutil.which('zsh'), '--version'], argv
        return subprocess.CompletedProcess(argv, 0, 'zsh 5.9', '')
with patch('iterm2_utils.discovery.platform.system', return_value='Darwin'), patch.object(cli, 'Runner', Runner):
    for command in ('plan', 'install', 'doctor'):
        output = io.StringIO()
        args = [command, '--json']
        if command != 'doctor': args += ['--features', 'shell', '--omp-profile', 'work']
        with contextlib.redirect_stdout(output):
            code = cli.main(args)
        assert code == 0, output.getvalue()
paths = resolve_paths()
receipt = state.load(paths.data/'receipt.json')
assert receipt.selection.features == {'shell'}
assert receipt.selection.omp_profile.name == 'work'
assert not (home/'.omp/profiles/work/agent/config.yml').exists()
assert calls and all(pathlib.Path(c[0]).name == 'zsh' for c in calls)
current = paths.data/'current'
assert (current/'vendor/shell_integration/LICENSE').is_file()
assert not (home/'forbidden-probe').exists()
"""

SHELL_LAUNCH = r"""
import contextlib, io, json, os, pathlib, plistlib, shlex, shutil, subprocess, sys
from unittest.mock import patch
from iterm2_utils import cli
home = pathlib.Path.home()
root = pathlib.Path.cwd()
app = home/'iTerm.app'
(app/'Contents/MacOS').mkdir(parents=True)
(app/'Contents/Resources/utilities').mkdir(parents=True)
(app/'Contents/Info.plist').write_bytes(plistlib.dumps({
    'CFBundleIdentifier':'com.googlecode.iterm2', 'CFBundleExecutable':'iTerm2'}))
binary = app/'Contents/MacOS/iTerm2'; binary.write_text('#!/bin/sh\nexit 97\n'); binary.chmod(0o700)
os.environ.update(ITERM2_APP=str(app), OMP_PROFILE='INVALID!', PI_PROFILE='INVALID!')
sdk = home/'sdk'; sdk.mkdir()
log = home/'sdk-log.jsonl'
(sdk/'iterm2.py').write_text('''
import json, os
from types import SimpleNamespace
async def close(): pass
async def connect(): return SimpleNamespace(websocket=SimpleNamespace(close=close))
async def profiles(connection): return [SimpleNamespace(name="Shell",guid="shell-guid")]
class Window:
    window_id = "W"
    async def async_create_tab(self, **kwargs):
        with open(os.environ["SDK_LOG"], "a") as out: out.write(json.dumps(kwargs)+"\\n")
        return SimpleNamespace(tab_id="T", all_sessions=[SimpleNamespace(session_id="S")])
async def async_get_app(connection):
    return SimpleNamespace(get_window_by_id=lambda wid: Window() if wid=="W" else None)
Connection = SimpleNamespace(async_create=connect)
Profile = SimpleNamespace(async_get=profiles)
''')
zsh = shutil.which('zsh')
it2 = app/'Contents/Resources/utilities/it2'
it2.write_text('#!'+sys.executable+'\n'+'''
import json, sys
kind, operation = sys.argv[1:3]
if operation=="list":
    value = {"window":[{"id":"W"}], "tab":[{"id":"T","window_id":"W","index":0}],
             "session":[{"id":"S","tab_id":"T","window_id":"W"}],
             "profile":[{"name":"Shell","guid":"shell-guid"}]}[kind]
elif kind=="profile":
    value = {"name":"Shell","guid":"shell-guid","command":""}
else:
    value = {"session.profileName":"Shell","session.jobName":"zsh",
             "session.commandLine":SHELL_LINE}[sys.argv[3]]
print(json.dumps(value))
'''.replace('SHELL_LINE', repr(shlex.join([zsh, '-il']))))
it2.chmod(0o700)
os.environ.update(PYTHONPATH=str(sdk)+os.pathsep+str(root), SDK_LOG=str(log))
output = io.StringIO()
with patch('iterm2_utils.launch_checks.platform.system', return_value='Darwin'), contextlib.redirect_stdout(output):
    code = cli.main(['launch-omp', '--mode', 'shell', '--window', 'W', '--profile', 'Shell',
                     '--cwd', str(home), '--json'])
assert code == 0, output.getvalue()
result = json.loads(output.getvalue())
assert (result['status'], result['command'], result['identity'], result['ack']) == (
    'launched', 'verified', 'unverified', 'not_requested'), result
creates = [json.loads(line) for line in log.read_text().splitlines()]
assert len(creates) == 1 and creates[0]['profile'] == 'Shell' and creates[0]['select'] is True, creates
assert shlex.split(creates[0]['command']) == [
    '/bin/sh', '-c', 'cd -- '+shlex.quote(str(home))+' && exec '+shlex.join([zsh, '-il'])]
# Execute the actual selected login-shell command, not a command-text assertion.
(home/'.zshrc').write_text('print -r -- shell-started > "$HOME/shell-proof"\n')
shell = subprocess.run(shlex.split(creates[0]['command']), input='exit\n',
    cwd=home, env=dict(os.environ, ZDOTDIR=str(home)), text=True, capture_output=True, timeout=10)
assert shell.returncode == 0, shell.stderr
assert (home/'shell-proof').read_text().strip() == 'shell-started'
assert not (home/'.omp').exists()
assert not (home/'forbidden-probe').exists()
"""


class ExportTests(unittest.TestCase):
    def test_export_requires_unique_current_contract_paths(self):
        required = {
            'iterm2_utils/config/legacy_mcp.py', 'iterm2_utils/legacy_state.py',
            'iterm2_utils/omp_profile.py', 'iterm2_utils/omp_sessions.py', 'iterm2_utils/terminal.py',
            'runtime/terminal_identity.py', 'runtime/omp_config.ts', 'runtime/omp_identity.ts',
            'vendor/yaml/LICENSE', 'vendor/yaml/package.json', 'vendor/yaml/dist/index.js',
            'tests/native_features_support.py', 'tests/test_omp_identity.ts',
            'tests/test_native_status_migration.py', 'docs/omp-launch.md', 'docs/omp-identity.md'}
        self.assertTrue(required <= set(check_export.EXPORT_FILES))
        retired = ('runtime/codex', 'runtime/hook.py', 'runtime/native_status.py',
                   'runtime/events.py', 'runtime/notifier.py', 'runtime/focus.py',
                   'runtime/claude_notifications.py', 'vendor/codex_status/', 'tests/restore/')
        self.assertFalse(any(name.startswith(retired) for name in check_export.EXPORT_FILES))
        self.assertEqual(len(check_export.EXPORT_FILES), len(set(check_export.EXPORT_FILES)))
        with patch.object(check_export, 'EXPORT_FILES',
                          (*check_export.EXPORT_FILES, 'runtime/terminal_identity.py')):
            self.assertIn('Duplicate export path: runtime/terminal_identity.py', check_export.check(ROOT))

    def test_appearance_delivery_contract(self):
        names = {'ios', 'android', 'kotlett', 'ios-mail', 'ios-cloud', 'android-mail', 'android-cloud',
                 'chrome-mail', 'chrome-cloud'}
        assets = {f'runtime/assets/appearance/{name}.{ext}' for name in names for ext in ('png', 'svg')}
        self.assertEqual({p for p in check_export.EXPORT_FILES if p.startswith('runtime/assets/appearance/')}, assets)
        self.assertTrue({'runtime/appearance.py', 'runtime/appearance.zsh', 'iterm2_utils/features/appearance.py',
                         'docs/repo-appearance.md', 'tests/test_appearance_shell.zsh',
                         'tests/test_appearance_rules.py', 'tests/test_appearance_runtime.py',
                         'tests/test_appearance_feature.py'} <= set(check_export.EXPORT_FILES))
        with TemporaryDirectory() as tmp:
            root = Path(tmp); repo = self.fixture(root)
            target = repo/'runtime/assets/appearance/ios.png'
            target.unlink()
            with self.assertRaises(ValueError): build_release.build(repo, root/'missing')
            target.symlink_to(ROOT/'runtime/assets/appearance/ios.png')
            with self.assertRaises(ValueError): build_release.build(repo, root/'symlink')

    def fixture(self, folder):
        repo = folder/'repo'
        for name in check_export.EXPORT_FILES:
            target = repo/name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/name, target)
        return repo

    def test_export_excludes_state_and_secret_fixtures(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); repo = self.fixture(root)
            for name in ('.env', '.env.production', '.git/config', 'tests/fixtures/private.json',
                         'runtime/.env.py', 'runtime/receipt.json', 'runtime/backup.py',
                         'logs/transcript.jsonl', 'auth/token', 'runtime/__pycache__/secret.pyc',
                         'docs/superpowers/validation/private.md', 'memory/private.md',
                         'docs/superpowers/plans/private-plan.md', '.superpowers/sdd/private-report.md',
                         'runtime/raw-event.json', 'runtime/cc-status', 'runtime/it2',
                         'runtime/assets/appearance/foreign.png', 'source-rules.json', 'config/appearance.json',
                         'data/receipt.json',
                         'Applications/iTerm.app/Contents/Resources/utilities/cc-status',
                         'Applications/iTerm.app/Contents/Resources/utilities/it2'):
                path = repo/name; path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((b'PRIVATE_' + b'FIXTURE_MARKER'))
            archive = build_release.build(repo, root/'dist')
            self.assertNotIn((b'PRIVATE_' + b'FIXTURE_MARKER'), archive.read_bytes())
            with tarfile.open(archive) as tar:
                members = tar.getmembers()
                self.assertEqual(len(members), len(check_export.EXPORT_FILES))
                names = {m.name.split('/', 1)[1] for m in members if '/' in m.name}
                self.assertEqual(len(names), len(members))
                self.assertIn('skills/iterm2-setup/SKILL.md', names)
                self.assertIn('vendor/yaml/LICENSE', names)
                self.assertIn('runtime/assets/appearance/android-mail.png', names)
                self.assertIn('runtime/appearance.py', names)
                self.assertIn('runtime/appearance.zsh', names)
                self.assertFalse(any(name.startswith(('.superpowers/', 'docs/superpowers/plans/')) for name in names))
                for member in members:
                    self.assertTrue(member.isfile())
                    content = tar.extractfile(member).read()
                    self.assertNotIn((b'PRIVATE_' + b'FIXTURE_MARKER'), content)
                    self.assertNotIn(str(root).encode(), content)
                    self.assertNotIn(str(ROOT).encode(), content)
                    relative = member.name.split('/', 1)[1]
                    if relative in {'runtime/appearance.py', 'runtime/appearance.zsh', 'iterm2_utils/launch_checks.py'}:
                        self.assertEqual(content, (ROOT/relative).read_bytes())
                self.assertEqual(names, set(check_export.EXPORT_FILES))
                self.assertTrue({'runtime/omp_identity.ts', 'runtime/terminal_identity.py',
                                 'tests/test_native_status_migration.py', 'tests/fixtures/beta1-hooks.json',
                                 'docs/native-status-events.md'} <= names)
            checksum = archive.with_name(archive.name+'.sha256').read_text()
            self.assertEqual(checksum, hashlib.sha256(archive.read_bytes()).hexdigest()+'  '+archive.name+'\n')
            self.assertNotIn(str(root), checksum)
            repeated = build_release.build(repo, root/'repeat')
            self.assertEqual(archive.read_bytes(), repeated.read_bytes())

    def test_missing_notice_or_source_hash_fails(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); repo = self.fixture(root)
            notice = repo/'THIRD_PARTY_NOTICES.md'; original = notice.read_bytes(); notice.unlink()
            self.assertTrue(check_export.check(repo))
            with self.assertRaises(ValueError):
                build_release.build(repo, root/'dist')
            notice.write_bytes(original)
            lock = repo/'sources.lock.json'; data = json.loads(lock.read_text())
            del data['sources'][0]['sha256']; lock.write_text(json.dumps(data))
            self.assertTrue(check_export.check(repo))
            data['sources'][0]['sha256'] = '0'*64; lock.write_text(json.dumps(data))
            self.assertTrue(check_export.check(repo))
            data['sources'][0]['ref'] = 'main'; lock.write_text(json.dumps(data))
            self.assertTrue(check_export.check(repo))

    def test_scanner_redacts_private_content_and_rejects_symlinks(self):
        with TemporaryDirectory() as tmp:
            repo = self.fixture(Path(tmp)); file = repo/'README.md'
            for value in ('https://'+'.'.join(('example','vk','team'))+'/private-secret',
                          'git@'+'.'.join(('gitlab','corp','mail','ru'))+':private-secret',
                          '/'+'Users/example/private-secret'):
                file.write_text(value)
                errors = check_export.check(repo)
                self.assertTrue(errors)
                self.assertNotIn('private-secret', '\n'.join(errors))
            file.unlink(); file.symlink_to(ROOT/'README.md')
            self.assertTrue(check_export.check(repo))

    def extract(self, archive, destination):
        with tarfile.open(archive) as tar:
            # Every generated member is a regular file under one fixed root.
            for member in tar.getmembers():
                self.assertTrue(member.isfile())
                self.assertTrue((destination/member.name).resolve().is_relative_to(destination.resolve()))
            for member in tar.getmembers():
                path = destination/member.name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(tar.extractfile(member).read())
                path.chmod(member.mode)
        return destination/('iterm2-utils-'+build_release.VERSION)

    def isolated_env(self, home):
        traps = home/'forbidden-bin'
        traps.mkdir(parents=True, exist_ok=True)
        for name in ('codex', 'claude', 'omp', 'bun', 'uvx', 'fzf', 'terminal-notifier'):
            path = traps/name
            path.write_text('#!/bin/sh\n: > "$HOME/forbidden-probe"\nexit 97\n')
            path.chmod(0o700)
        return {'HOME':str(home), 'ZDOTDIR':str(home), 'PATH':str(traps)+':/usr/bin:/bin',
                'PYTHONNOUSERSITE':'1', 'PYTHONDONTWRITEBYTECODE':'1', 'PYTHONPATH':'', 'TMUX':''}

    def run_python(self, extracted, home, *args):
        home.mkdir(exist_ok=True)
        return subprocess.run([sys.executable, *args], cwd=extracted, env=self.isolated_env(home),
                              text=True, capture_output=True, timeout=120)

    def test_fresh_extract_imports_and_bootstraps_all_bundles_without_optional_dependencies(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); repo = self.fixture(root)
            extracted = self.extract(build_release.build(repo, root/'dist'), root/'extract')
            shutil.rmtree(repo)
            shutil.rmtree(root/'dist')
            result = self.run_python(extracted, root/'home', '-c', IMPORT_AND_BOOTSTRAP)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertFalse((root/'home/forbidden-probe').exists())

    def test_extracted_release_installs_and_observes_shell_without_sdk_or_agent(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); repo = self.fixture(root)
            extracted = self.extract(build_release.build(repo, root/'dist'), root/'extract')
            shutil.rmtree(repo)
            result = self.run_python(extracted, root/'home', '-c', SHELL_INSTALL)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_extracted_shell_mode_uses_one_supervised_sdk_create_and_real_login_shell(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); repo = self.fixture(root)
            extracted = self.extract(build_release.build(repo, root/'dist'), root/'extract')
            shutil.rmtree(repo)
            result = self.run_python(extracted, root/'home', '-c', SHELL_LAUNCH)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_installed_parser_runs_after_extracted_sources_are_removed(self):
        bun = shutil.which('bun')
        self.assertIsNotNone(bun, 'Integrated native YAML coverage requires Bun')
        with TemporaryDirectory() as tmp:
            root = Path(tmp); repo = self.fixture(root)
            extracted = self.extract(build_release.build(repo, root/'dist'), root/'extract')
            shutil.rmtree(repo)
            script = SHELL_INSTALL + r"""
notices = {name:(root/name).read_bytes() for name in ('LICENSE', 'THIRD_PARTY_NOTICES.md')}
shutil.rmtree(root)
os.chdir(home)
for name, content in notices.items(): assert (current/name).read_bytes() == content
result = subprocess.run([BUN, '--no-install', '--no-env-file', '--config=/dev/null',
    str(current/'runtime/omp_config.ts')], input=json.dumps({
        'op':'patch', 'raw':'# keep\nterminal: {programStatus: false}\nmodel: unchanged\n',
        'pointer':['terminal','programStatus'], 'expected':{'exists':True,'value':False},
        'next':{'exists':True,'value':True}}), cwd=home, env=dict(os.environ),
        capture_output=True, text=True, timeout=5)
assert result.returncode == 0, result.stderr
raw = json.loads(result.stdout)['raw']
assert raw == '# keep\nterminal: {programStatus: true}\nmodel: unchanged\n', raw
""".replace('BUN,', repr(bun)+',')
            result = self.run_python(extracted, root/'home', '-c', script)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_extracted_skill_validator_covers_three_bundles(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); repo = self.fixture(root)
            extracted = self.extract(build_release.build(repo, root/'dist'), root/'extract')
            shutil.rmtree(repo)
            result = self.run_python(extracted, root/'home', 'tools/check_skill.py')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            (extracted/'skills/iterm2-launch/SKILL.md').write_text('invalid')
            result = self.run_python(extracted, root/'home', 'tools/check_skill.py')
            self.assertNotEqual(result.returncode, 0, 'Default validator missed broken launch skill')
            result = self.run_python(extracted, root/'home', 'tools/check_skill.py', 'skills/iterm2-setup')
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_current_workflows_execute_from_extracted_release_without_original_checkout(self):
        bun = shutil.which('bun')
        self.assertIsNotNone(bun, 'Integrated native YAML coverage requires Bun')
        with TemporaryDirectory() as tmp:
            root = Path(tmp); repo = self.fixture(root)
            extracted = self.extract(build_release.build(repo, root/'dist'), root/'extract')
            shutil.rmtree(repo)
            home = root/'home'; home.mkdir()
            env = self.isolated_env(home)
            selected = home/'selected-bin'; selected.mkdir()
            (selected/'bun').symlink_to(bun)
            env['PATH'] = str(selected)+os.pathsep+env['PATH']
            result = subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_cli',
                'tests.test_agent_workflow', 'tests.test_skill_install', 'tests.test_lifecycle',
                'tests.test_payload', '-v'], cwd=extracted, env=env,
                text=True, capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertFalse((home/'forbidden-probe').exists())

    def test_provenance_rejects_stripped_retained_metadata(self):
        import copy
        with TemporaryDirectory() as tmp:
            repo = self.fixture(Path(tmp))
            lock = repo/'sources.lock.json'
            data = json.loads(lock.read_bytes())
            self.assertFalse(check_export.check(repo))
            for field in ('url', 'license', 'license_file', 'attribution_file'):
                altered = copy.deepcopy(data)
                altered['sources'][0].pop(field)
                lock.write_text(json.dumps(altered))
                self.assertTrue(check_export.check(repo), field)


if __name__ == '__main__':
    unittest.main()
