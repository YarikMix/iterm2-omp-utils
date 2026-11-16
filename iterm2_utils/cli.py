"""Public diagnostics serialize an allowlist, never settings or subprocess output."""
import argparse
import json
import os
from pathlib import Path
from dataclasses import asdict
from runtime.codex_restore.codexlib.transcripts import normalize_uuid
from .commands import Runner
from .discovery import discover, resolve_paths, live_status
from .models import Selection, Finding, Context, Outcome
from .legacy_state import AGENTS, LegacyReceipt, LegacySelection
from . import lifecycle, migration, state
from .planner import FEATURES, SHORTCUTS, plan


def _csv(value):
    return frozenset(part.strip() for part in value.split(',') if part.strip())


def _exit(findings):
    if any(f.state in {'conflict','missing_dependency','unavailable'} for f in findings):
        return 2
    return 3 if any(f.state in {'pending_ui','new_session'} for f in findings) else 0


def _selection(selection):
    if isinstance(selection, Selection):
        return dict(features=sorted(selection.features), shortcuts=sorted(selection.shortcuts),
                    parent_profile=selection.parent_profile,
                    omp_profile=dict(name=selection.omp_profile.name, agent_dir=str(selection.omp_profile.agent_dir)),
                    resume_key=selection.resume_key, notify_errors=selection.notify_errors)
    return dict(agents=sorted(selection.agents),features=sorted(selection.features),
                shortcuts=sorted(selection.shortcuts),parent_profile=selection.parent_profile,
                agent_features={a: sorted(selection.features_for(a)) for a in sorted(selection.agents)},
                agent_shortcuts={a: sorted(selection.shortcuts_for(a)) for a in sorted(selection.agents)},
                coexist_notifications=selection.coexist_notifications,
                notification_coexist_agents=sorted(a for a in selection.agents if selection.coexist_for(a)))


def _outcome(mode, result):
    pending = {step.feature for step in result.receipt.pending_ui}
    return dict(mode=mode,selection=_selection(result.receipt.selection),
                completed=sorted(result.receipt.selection.features-pending),pending=sorted(pending),
                findings=[asdict(f) for f in result.findings],ui=[asdict(s) for s in result.receipt.pending_ui])


def _receipt_boundary(receipt, args):
    """Stop old consumer dispatch before discovery when state has crossed versions."""
    if receipt is None:
        return False
    historical = isinstance(receipt, LegacyReceipt)
    finding = Finding('selection', None, 'migration_required' if historical else 'invalid_selection', 'conflict',
                      'Historical ownership requires explicit migration.' if historical else
                      'Current omp ownership cannot be used with a historical agent selection.')
    output = _outcome(args.command, Outcome(receipt, [finding]))
    print(json.dumps(output, sort_keys=True) if args.json else finding.message)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description='Inspect and apply explicitly selected iTerm2 features.')
    sub = parser.add_subparsers(dest='command',required=True)
    for command in ('plan','install','update','uninstall','doctor','reconcile'):
        command_parser = sub.add_parser(command)
        command_parser.add_argument('--json',action='store_true')
        if command != 'reconcile':
            command_parser.add_argument('--dry-run',action='store_true')
        if command in {'plan','install'}:
            command_parser.add_argument('--agent',choices=['codex','claude','both'],required=True)
            command_parser.add_argument('--features',required=True,help=', '.join(sorted(FEATURES)))
            command_parser.add_argument('--shortcuts',default='',help=', '.join(sorted(SHORTCUTS)))
            command_parser.add_argument('--parent-profile')
            command_parser.add_argument('--appearance-config', type=Path)
            command_parser.add_argument('--project-launcher-config', type=Path)
            command_parser.add_argument('--adopt-legacy',action='store_true')
            command_parser.add_argument('--coexist-notifications',action='store_true')
        elif command == 'uninstall':
            command_parser.add_argument('--features',required=True)
            command_parser.add_argument('--agent',choices=['codex','claude','both'])
        elif command == 'doctor':
            command_parser.add_argument('--live',action='store_true')
        elif command == 'reconcile':
            command_parser.add_argument('--step',required=True)
    launch_parser = sub.add_parser('launch-codex', help='Launch one Codex in an explicit iTerm2 tab.')
    for flag in ('window', 'profile', 'cwd'):
        launch_parser.add_argument('--'+flag, required=True)
    launch_modes = launch_parser.add_mutually_exclusive_group(required=True)
    launch_modes.add_argument('--handoff')
    launch_modes.add_argument('--resume', type=normalize_uuid)
    launch_parser.add_argument('--json', action='store_true')
    bootstrap = sub.add_parser('bootstrap-skill', help='Copy one public skill; select no terminal features.')
    bootstrap.add_argument('--skill', choices=['iterm2-setup','iterm2-launch','iterm2-projects'], default='iterm2-setup')
    bootstrap.add_argument('--omp-profile')
    bootstrap.add_argument('--dry-run', action='store_true')
    bootstrap.add_argument('--json', action='store_true')
    try:
        args = parser.parse_args(argv)
    except SystemExit as error:
        return int(error.code)
    if args.command in {'plan','install','uninstall'}:
        features = _csv(args.features)
        shortcuts = _csv(getattr(args,'shortcuts',''))
        if not features or features-FEATURES or shortcuts-SHORTCUTS:
            if args.json:
                print(json.dumps({'mode':'invalid_selection','findings':[asdict(Finding('selection',None,'invalid_selection','conflict','Choose supported features and shortcuts explicitly.'))]}))
            else:
                print('Choose supported features explicitly; no inspection or changes performed.')
            return 2
    if getattr(args,'appearance_config',None) is not None and 'appearance' not in features:
        finding = Finding('appearance',None,'appearance_config_selection','conflict','An appearance configuration requires an explicit appearance feature selection.')
        print(json.dumps({'mode':'invalid_selection','findings':[asdict(finding)]}) if args.json else finding.message)
        return 2
    if getattr(args,'project_launcher_config',None) is not None and 'project-launcher' not in features:
        finding = Finding('project-launcher',None,'project_launcher_config_selection','conflict','A project configuration requires an explicit project-launcher selection.')
        print(json.dumps({'mode':'invalid_selection','findings':[asdict(finding)]}) if args.json else finding.message)
        return 2
    runner = Runner()
    paths = resolve_paths()
    if args.command == 'launch-codex':
        from .launch import launch
        from .launch_checks import LaunchRequest
        request = LaunchRequest(args.window, args.profile, Path(args.cwd),
                                Path(args.handoff) if args.handoff is not None else None, args.resume)
        status, output = launch(request, paths, runner)
    elif args.command == 'bootstrap-skill':
        from . import skill_install
        from .omp_profile import resolve_omp_profile
        # Bootstrap resolves paths only, never agent settings or executables.
        try:
            profile = resolve_omp_profile(paths.home, dict(os.environ), args.omp_profile)
        except ValueError:
            print('Invalid omp profile.')
            return 2
        context = Context(paths, {}, {}, frozenset(), {}, {}, omp_profile=profile)
        findings = skill_install.install(context, runner, dry_run=args.dry_run, skill=args.skill)
        output = dict(mode='bootstrap_preview' if args.dry_run else 'bootstrap_skill',
                      selection=dict(omp_profile=dict(name=profile.name, agent_dir=str(profile.agent_dir)),
                                     features=[], shortcuts=[], parent_profile='Default'),
                      findings=[asdict(f) for f in findings])
        status = _exit(findings)
    elif args.command in {'plan','install'}:
        agents = AGENTS if args.agent=='both' else frozenset({args.agent})
        try:
            previous = state.load(paths.data/'receipt.json')
        except (OSError, ValueError):
            previous = None
        if _receipt_boundary(previous, args):
            return 2
        context = discover(paths,runner,features=features | (previous.selection.features if previous else frozenset()))
        context.appearance_config = args.appearance_config
        context.project_launcher_config = args.project_launcher_config
        selection = LegacySelection(agents,features,shortcuts,args.parent_profile if args.parent_profile is not None else previous.selection.parent_profile if previous else 'Default',args.adopt_legacy,coexist_notifications=args.coexist_notifications)
        if args.command == 'plan':
            # Preview the same cumulative intent as install, with new choices
            # applied only to their explicitly requested agents.
            choice = previous.selection.merge(selection, selection.features) if previous else selection
            from .features.project_launcher import prepare
            prepared = plan(prepare(context,choice,runner),choice)
            output = dict(mode='read_only_preview',selection=_selection(prepared.selection),
                          findings=[asdict(f) for f in prepared.changes.findings],
                          ui=[asdict(s) for s in prepared.changes.ui],fingerprint=prepared.fingerprint)
            status = _exit(prepared.changes.findings)
        else:
            result = lifecycle.install(context,selection,runner,dry_run=args.dry_run)
            output = _outcome('install_preview' if args.dry_run else 'install',result)
            status = _exit(result.findings)
    else:
        receipt_error = False
        try:
            receipt = state.load(paths.data/'receipt.json')
        except (ValueError,OSError):
            receipt = None
            receipt_error = True
        if isinstance(receipt, LegacyReceipt):
            if _receipt_boundary(receipt, args):
                return 2
        if receipt is not None and not isinstance(receipt, LegacyReceipt):
            context = discover(paths,runner,features=receipt.selection.features)
            context.omp_profile = receipt.selection.omp_profile
            if args.command == 'doctor':
                findings = lifecycle.doctor(context, receipt, runner)
                if args.live and 'mcp' in receipt.selection.features:
                    from .config.mcp import probe
                    findings.append(probe(context, runner))
                output = dict(mode='read_only_discovery', selection=_selection(receipt.selection),
                              findings=[asdict(f) for f in findings])
            else:
                result = (lifecycle.update(context, runner, dry_run=args.dry_run) if args.command == 'update' else
                          lifecycle.uninstall(context, features, runner, dry_run=args.dry_run) if args.command == 'uninstall' else
                          lifecycle.reconcile_ui(context, args.step, runner))
                findings = result.findings
                output = _outcome(args.command, result)
            print(json.dumps(output, sort_keys=True) if args.json else '\n'.join(f.message for f in findings))
            return _exit(findings)
        context = discover(paths,runner,features=receipt.selection.features if receipt else frozenset())
        if args.command == 'doctor':
            findings = migration.preview_omp_migration(context, runner).changes.findings
            if receipt_error:
                findings.append(Finding('selection',None,'ownership_unavailable','conflict',
                    'The ownership receipt is unreadable or invalid; repair it before updating or uninstalling.'))
            if receipt:
                findings += lifecycle.doctor(context,receipt,runner)
                findings += [Finding(s.feature,s.agent,s.code,'pending_ui',s.instruction) for s in receipt.pending_ui]
            if args.live:
                findings.extend(live_status(context,runner,receipt.selection if receipt else None))
                if receipt and 'appearance' in receipt.selection.features:
                    from .discovery import live_appearance
                    findings.append(live_appearance(context,runner))
            output = dict(mode='read_only_discovery',executables=sorted(context.executables),versions=context.versions,
                          capabilities=sorted(context.capabilities),features=sorted(FEATURES),
                          python_api='ready' if any(f.code=='status_api' and f.state=='ready' for f in findings) else 'not_verified',
                          runtime_connection='not_verified',findings=[asdict(f) for f in findings])
            if receipt:
                output['selection'] = _selection(receipt.selection)
            status = _exit(findings) if 'iterm2' in context.executables else 2
        else:
            if args.command == 'update':
                result = lifecycle.update(context,runner,dry_run=args.dry_run)
            elif args.command == 'uninstall':
                result = lifecycle.uninstall(context,features,runner,dry_run=args.dry_run)
            else:
                result = lifecycle.reconcile_ui(context,args.step,runner)
            output = _outcome(args.command+('_preview' if getattr(args,'dry_run',False) else ''),result)
            status = _exit(result.findings)
    if args.json:
        print(json.dumps(output,sort_keys=True))
    else:
        if args.command == 'launch-codex':
            print(output['status']+' '+ ' '.join(key+'='+json.dumps(output[key])
                  for key in ('window_id', 'tab_id', 'session_id', 'profile')))
        else:
            print(output['mode'].replace('_',' ').capitalize()+'.')
        for finding in output['findings']:
            print(f"{finding['feature']} ({finding['agent'] or 'selection'}): {finding['state']}: {finding['message']}")
        if args.command == 'doctor':
            print('Detected: '+', '.join(output['executables']))
            print('Available features: '+', '.join(sorted(FEATURES)))
    return status
