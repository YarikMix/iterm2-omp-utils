"""Public omp workflows; diagnostics never serialize settings or ownership snapshots."""
import argparse
from dataclasses import asdict, replace
import json
import os
from pathlib import Path
from .commands import Runner
from .discovery import discover, resolve_paths, live_status
from .models import Context, Finding, Receipt, Selection
from .legacy_state import LegacyReceipt
from .omp_profile import resolve_omp_profile
from . import lifecycle, migration, state
from .planner import FEATURES, SHORTCUTS, plan


def _csv(value):
    return frozenset(part.strip() for part in value.split(',') if part.strip())


def _exit(findings):
    if any(f.state in {'conflict','missing_dependency','unavailable'} for f in findings):
        return 2
    return 3 if any(f.state in {'pending_ui','new_session'} for f in findings) else 0


def _selection(selection):
    if not isinstance(selection, Selection):
        return dict(features=sorted(selection.features & FEATURES), migration_required=True)
    return dict(features=sorted(selection.features), shortcuts=sorted(selection.shortcuts),
                parent_profile=selection.parent_profile,
                omp_profile=dict(name=selection.omp_profile.name, agent_dir=str(selection.omp_profile.agent_dir)),
                resume_key=selection.resume_key, notify_errors=selection.notify_errors)


def _outcome(mode, result):
    pending = {step.feature for step in result.receipt.pending_ui}
    historical = isinstance(result.receipt, LegacyReceipt)
    return dict(mode=mode, selection=_selection(result.receipt.selection),
                completed=[] if historical else sorted(result.receipt.selection.features-pending),
                pending=sorted(pending), findings=[asdict(f) for f in result.findings],
                ui=[] if historical else [asdict(s) for s in result.receipt.pending_ui])


def _emit(args, output):
    if args.json:
        print(json.dumps(output, sort_keys=True))
    else:
        # JSON escaping keeps terminal control characters inert in text output too.
        print(json.dumps(output.get('status', output['mode']))+
              (' '+ ' '.join(key+'='+json.dumps(output.get(key))
               for key in ('window_id','tab_id','session_id','profile')) if args.command=='launch-omp' else ''))
        for finding in output.get('findings', []):
            print(json.dumps(finding['message']))
    return _exit([Finding(**f) for f in output.get('findings', [])])


def _problem(args, code, message):
    output = dict(mode=args.command, findings=[asdict(Finding('selection',None,code,'conflict',message))])
    if args.command=='launch-omp':
        output.update(mode='launch_omp',launch_mode=args.mode,status='blocked',window_id=None,
                      tab_id=None,session_id=None,profile=args.profile,command='unverified',
                      identity='unverified',history='not_requested',ack='not_requested')
    _emit(args,output)
    return 2


def _parser():
    parser = argparse.ArgumentParser(description='Explicit omp-only iTerm2 workflows; ordinary tabs use shell.')
    sub = parser.add_subparsers(dest='command',required=True)
    for command in ('plan','install','update','uninstall','doctor','reconcile'):
        p = sub.add_parser(command)
        p.add_argument('--json',action='store_true')
        p.add_argument('--omp-profile')
        if command != 'reconcile':p.add_argument('--dry-run',action='store_true')
        if command in {'plan','install'}:
            p.add_argument('--features',required=True,help=', '.join(sorted(FEATURES)))
            p.add_argument('--shortcuts',default='',help=', '.join(sorted(SHORTCUTS)))
            p.add_argument('--parent-profile')
            p.add_argument('--resume-key')
            p.add_argument('--notify-errors',action='store_true')
            p.add_argument('--appearance-config',type=Path)
            p.add_argument('--project-launcher-config',type=Path)
        elif command == 'uninstall':p.add_argument('--features',required=True)
        elif command == 'doctor':p.add_argument('--live',action='store_true')
        elif command == 'reconcile':p.add_argument('--step',required=True)
    p = sub.add_parser('launch-omp',help='Create one shell or omp tab without retries.')
    p.add_argument('--mode',choices=['shell','new','handoff','resume'],required=True)
    p.add_argument('--window',default='')
    p.add_argument('--profile',required=True)
    p.add_argument('--cwd',type=Path,required=True)
    p.add_argument('--omp-profile')
    p.add_argument('--handoff',type=Path)
    p.add_argument('--resume-file',type=Path)
    p.add_argument('--resume-id')
    p.add_argument('--allow-duplicate',action='store_true',help='Explicitly authorize an additional exact-resume tab.')
    p.add_argument('--json',action='store_true')
    p = sub.add_parser('bootstrap-skill',help='Copy one skill; authorize no terminal settings changes.')
    p.add_argument('--skill',choices=['iterm2-setup','iterm2-launch','iterm2-projects'],default='iterm2-setup')
    p.add_argument('--omp-profile')
    p.add_argument('--dry-run',action='store_true')
    p.add_argument('--json',action='store_true')
    p = sub.add_parser('migrate-omp',help='Preview receipt-authorized cleanup by default; never launch historical agents.')
    mode = p.add_mutually_exclusive_group()
    mode.add_argument('--dry-run',action='store_true')
    mode.add_argument('--apply',action='store_true')
    p.add_argument('--restore-external',action='store_true',help='Explicitly restore proven previously disabled external integration values.')
    p.add_argument('--omp-profile')
    p.add_argument('--json',action='store_true')
    return parser


def main(argv=None):
    parser = _parser()
    try:
        args = parser.parse_args(argv)
        if args.command == 'launch-omp':
            if ((args.handoff is not None) != (args.mode=='handoff') or
                    (args.resume_file is not None) != (args.mode=='resume') or
                    (args.resume_id is not None) != (args.mode=='resume') or
                    args.allow_duplicate and args.mode!='resume'):
                parser.error('Use --mode shell|new alone, handoff with --handoff, or resume with --resume-file and --resume-id; --allow-duplicate is resume-only.')
        if args.command in {'plan','install','uninstall'}:
            features = _csv(args.features)
            shortcuts = _csv(getattr(args,'shortcuts',''))
            if not features or features-FEATURES or shortcuts-SHORTCUTS:
                return _problem(args,'invalid_selection','Choose supported features and shortcuts explicitly.')
            for flag,feature in (('appearance_config','appearance'),('project_launcher_config','project-launcher')):
                if getattr(args,flag,None) is not None and feature not in features:
                    return _problem(args,flag+'_selection','A local configuration requires its explicitly selected feature.')
    except SystemExit as error:
        return int(error.code)
    runner, paths = Runner(), resolve_paths()
    selected = None
    shell = args.command=='launch-omp' and args.mode=='shell'
    recorded_profile = args.command in {'update','uninstall','doctor','reconcile'} and args.omp_profile is None
    if not shell and not recorded_profile:
        try:
            selected = resolve_omp_profile(paths.home,dict(os.environ),args.omp_profile)
        except ValueError:
            return _problem(args,'invalid_omp_profile','Select a valid omp profile.')
    if args.command == 'launch-omp':
        from .launch import launch
        from .launch_checks import LaunchRequest
        from .omp_sessions import resolve_resume
        try:
            target = resolve_resume(args.resume_file,args.resume_id,selected) if args.mode=='resume' else None
            request = LaunchRequest(args.window,args.profile,args.cwd,selected,args.mode,args.handoff,target,args.allow_duplicate)
            status,output = launch(request,paths,runner)
        except (OSError,ValueError):
            return _problem(args,'launch_invalid_request','Exact launch inputs could not be validated; no fallback was attempted.')
        _emit(args,output)
        return status
    if args.command in {'bootstrap-skill','migrate-omp'}:
        context = Context(paths,{}, {},frozenset(),{}, {},omp_profile=selected)
    if args.command == 'bootstrap-skill':
        from . import skill_install
        findings = skill_install.install(context,runner,dry_run=args.dry_run,skill=args.skill)
        output = dict(mode='bootstrap_preview' if args.dry_run else 'bootstrap_skill',
                      selection=_selection(Selection(frozenset(),frozenset(),'Default',selected)),
                      findings=[asdict(f) for f in findings])
        return _emit(args,output)
    if args.command == 'migrate-omp':
        # Preview and cleanup require no executable discovery. Native source intent
        # on apply uses the same feature-scoped discovery as a normal install.
        if args.apply:
            try:
                intended = frozenset()
                for path in (paths.data/'receipt.json', paths.data/'journal/intent.json', paths.data/'journal/result.json'):
                    previous = state.load(path)
                    if previous:
                        intended |= previous.selection.features & FEATURES
                    if isinstance(previous,Receipt):
                        for raw in previous.legacy_cleanup:
                            intended |= frozenset(raw['selection']['features']) & FEATURES
                if intended:
                    context = discover(paths,runner,features=intended,omp_profile=selected)
            except (OSError,ValueError):
                pass  # Migration emits its bounded ownership/recovery finding.
        result = migration.migrate_to_omp(context,runner,dry_run=not args.apply,restore_external=args.restore_external)
        output = _outcome('migration_apply' if args.apply else 'migration_preview',result)
        output['restore_external'] = args.restore_external
        return _emit(args,output)
    try:
        receipt = state.load(paths.data/'receipt.json')
        for journal_file in ('intent.json','result.json'):
            if isinstance(state.load(paths.data/'journal'/journal_file),LegacyReceipt):
                return _problem(args,'migration_required','Run migrate-omp before recovering a historical transaction.')
    except (OSError,ValueError):
        return _problem(args,'ownership_unavailable','The ownership receipt is invalid or unreadable; no empty-state replacement was attempted.')
    if isinstance(receipt,LegacyReceipt):
        return _problem(args,'migration_required','Run migrate-omp for explicit preview, then migrate-omp --apply; historical ownership was not changed.')
    if receipt and args.command not in {'plan','install'}:
        if selected is not None and selected != receipt.selection.omp_profile:
            return _problem(args,'selection_conflict','Keep the recorded omp profile until owned features are removed.')
        selected = receipt.selection.omp_profile
    if selected is None:
        try:
            selected = resolve_omp_profile(paths.home,dict(os.environ),args.omp_profile)
        except ValueError:
            return _problem(args,'invalid_omp_profile','Select a valid omp profile.')
    context = discover(paths,runner,features=(features if args.command in {'plan','install'} else frozenset()) |
                       (receipt.selection.features if receipt else frozenset()),omp_profile=selected)
    if args.command in {'plan','install'}:
        context.appearance_config = args.appearance_config
        context.project_launcher_config = args.project_launcher_config
        choice = Selection(features,shortcuts,args.parent_profile if args.parent_profile is not None else
                           receipt.selection.parent_profile if receipt else 'Default',selected,args.resume_key,args.notify_errors)
        if args.command=='plan':
            if receipt and receipt.selection.features and (selected!=receipt.selection.omp_profile or choice.parent_profile!=receipt.selection.parent_profile):
                return _problem(args,'selection_conflict','Keep the recorded omp and parent profiles until owned features are removed.')
            if receipt:
                choice = replace(choice,features=receipt.selection.features | features,
                    shortcuts=receipt.selection.shortcuts | shortcuts,
                    resume_key=(args.resume_key if 'resume' in shortcuts else receipt.selection.resume_key),
                    notify_errors=(args.notify_errors if 'notifications' in features else receipt.selection.notify_errors))
            from .features.project_launcher import prepare
            prepared = plan(prepare(context,choice,runner),choice)
            output = dict(mode='read_only_preview',selection=_selection(choice),
                          findings=[asdict(f) for f in prepared.changes.findings],
                          ui=[asdict(s) for s in prepared.changes.ui],fingerprint=prepared.fingerprint)
        else:
            output = _outcome('install_preview' if args.dry_run else 'install',lifecycle.install(context,choice,runner,dry_run=args.dry_run))
    elif args.command=='doctor':
        findings = lifecycle.doctor(context,receipt,runner) if receipt else migration.preview_omp_migration(context,runner).changes.findings
        if receipt:
            findings.extend(Finding(s.feature,s.agent,s.code,'pending_ui',s.instruction) for s in receipt.pending_ui)
        if args.live:
            findings.extend(live_status(context,runner,receipt.selection if receipt else None))
            if receipt and 'appearance' in receipt.selection.features:
                from .discovery import live_appearance
                findings.append(live_appearance(context,runner))
            if receipt and 'mcp' in receipt.selection.features:
                from .config.mcp import probe
                findings.append(probe(context,runner))
        output = dict(mode='read_only_discovery',executables=sorted(context.executables),versions=context.versions,
                      capabilities=sorted(context.capabilities),features=sorted(FEATURES),findings=[asdict(f) for f in findings])
        if receipt:output['selection'] = _selection(receipt.selection)
    else:
        result = (lifecycle.update(context,runner,dry_run=args.dry_run) if args.command=='update' else
                  lifecycle.uninstall(context,features,runner,dry_run=args.dry_run) if args.command=='uninstall' else
                  lifecycle.reconcile_ui(context,args.step,runner))
        output = _outcome(args.command+('_preview' if getattr(args,'dry_run',False) else ''),result)
    return _emit(args,output)
