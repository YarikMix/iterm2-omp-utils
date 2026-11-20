import unittest
from dataclasses import replace
from iterm2_utils.models import FileEdit
from iterm2_utils.features.shell import build
from tests.native_features_support import NativeFixture


class ShellFixture(NativeFixture):
    def setUp(self):
        super().setUp()
        self.root = self.home

    def selection(self, features=('shell',)):
        return super().selection(*features)


class ShellTests(ShellFixture):
    def test_native_event_features_do_not_install_shell_dispatcher(self):
        self.assertEqual(build(self.context,self.selection(('status','notifications','restore'))).edits,[])

    def test_existing_integration_is_reused_without_ownership(self):
        self.context.paths.zshrc.write_text('source ~/.iterm2_shell_integration.zsh\n')
        changes = build(self.context,self.selection())
        self.assertFalse(changes.edits)
        self.assertTrue(any(f.code=='existing_integration' for f in changes.findings))

    def test_appearance_sources_only_retained_helper(self):
        changes = build(self.context,self.selection(('appearance',)))
        startup = changes.edits[0].after
        self.assertIn(b'appearance.zsh',startup)
        self.assertNotIn(b'codex',startup)
        self.assertNotIn(b'shell_integration',startup)
        self.assertEqual(changes.consumers['shared:shell'],{'appearance'})

    def test_shell_requires_no_agent_and_preserves_user_functions(self):
        self.context.executables = {k:v for k,v in self.context.executables.items() if k in {'zsh','iterm2'}}
        self.context.paths.zshrc.write_text('function omp() { command omp \"$@\"; }\n')
        changes = build(self.context,self.selection())
        self.assertIn(b'function omp()',changes.edits[0].after)
        self.assertNotIn(b'--auto-approve',changes.edits[0].after)

    def test_shell_marks_only_inside_iterm(self):
        import subprocess
        changes=build(self.context,self.selection())
        startup=next(e.after.decode() for e in changes.edits if isinstance(e,FileEdit) and e.path==self.context.paths.zshrc)
        integration=self.context.paths.data/'current/vendor/shell_integration/iterm2_shell_integration.zsh'
        integration.parent.mkdir(parents=True)
        integration.write_text('typeset -g FIXTURE_MARKS=loaded\n')
        for terminal,preloaded,expected in [('other','', 'absent'),('iTerm.app','', 'loaded'),('iTerm.app','Yes','absent')]:
            script='TERM_PROGRAM='+terminal+'; ITERM_SHELL_INTEGRATION_INSTALLED='+preloaded+'; '+startup+'\nprint -r -- ${FIXTURE_MARKS-absent}'
            result=subprocess.run(['/bin/zsh','-dfc',script],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(result.stdout.strip(),expected)
    def test_legacy_managed_wrapper_requires_migration(self):
        self.context.paths.zshrc.write_text('# >>> codex-no-daemon >>>\nfunction codex() { command codex "$@"; }\n# <<< codex-no-daemon <<<\n')
        self.assertEqual(build(self.context,self.selection(('status',))).edits,[])
    def test_shell_block_named_block_inverse_and_malformed_rejected(self):
        from iterm2_utils.config import zshrc
        original=b'export KEEP=yes\n'
        named=zshrc.block(original,'legacy','echo named')
        both=zshrc.block(named,'root','echo root')
        self.assertEqual(zshrc.block(both,'root',None),named)
        self.assertEqual(zshrc.block(zshrc.block(both,'legacy',None),'root',None),original)
        for malformed in (b'# >>> iterm2-utils >>>\n', b'# <<< iterm2-utils <<<\n',b'# >>> iterm2-utils BAD >>>\n',both+ b'# <<< iterm2-utils:bad <<<\n'):
            with self.assertRaises(ValueError): zshrc.blocks(malformed)
    def test_removing_shell_marks_keeps_appearance_consumer(self):
        from iterm2_utils import engine
        from iterm2_utils.models import Plan
        both = self.selection(('shell','appearance'))
        initial = engine.apply(Plan(both,build(self.context,both),'initial'),self.context,self.runner)
        self.assertSuccess(initial)
        remaining = self.selection(('appearance',))
        result = engine.apply(Plan(remaining,build(self.context,remaining),'remaining'),
                              self.context,self.runner,remove_owners=frozenset({'shell'}))
        self.assertSuccess(result)
        startup = self.context.paths.zshrc.read_text()
        self.assertNotIn('shell_integration',startup)
        self.assertIn('appearance.zsh',startup)
        self.assertEqual(set(result.receipt.resources[0]['owners']),{'shared:shell','appearance'})

    def test_unicode_source_path_is_literal(self):
        import os
        import subprocess
        data = self.home/"Юникод space ' $(touch INJECTED)"
        self.context.paths = replace(self.context.paths,data=data)
        integration = data/'current/vendor/shell_integration/iterm2_shell_integration.zsh'
        integration.parent.mkdir(parents=True)
        integration.write_text('typeset -g FIXTURE_MARKS=loaded\n')
        changes = build(self.context,self.selection())
        startup = next(e.after for e in changes.edits if e.path==self.context.paths.zshrc)
        path = self.home/'startup'
        path.write_bytes(startup)
        result = subprocess.run(['/bin/zsh','-dfc','source \"$1\"; print -r -- ${FIXTURE_MARKS-absent}',
            'fixture',str(path)],capture_output=True,text=True,cwd=self.home,
            env={**os.environ,'HOME':str(self.home),'TERM_PROGRAM':'iTerm.app',
                 'ITERM_SHELL_INTEGRATION_INSTALLED':''},timeout=5)
        self.assertEqual((result.returncode,result.stdout),(0,'loaded\n'),result.stderr)
        self.assertFalse((self.home/'INJECTED').exists())
