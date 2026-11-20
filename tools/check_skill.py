#!/usr/bin/env python3
"""Small stdlib structural validator. This does not assess agent behavior."""
import json
import re
import shlex
import sys
from pathlib import Path


def check(root):
    errors = []
    entry = root/'SKILL.md'
    if not entry.is_file() or entry.is_symlink():
        return ['SKILL.md must be a regular file']
    text = entry.read_text()
    match = re.match(r'\A---\n(.*?)\n---\n', text, re.S)
    if not match:
        return ['Missing standard frontmatter']
    fields = {}
    for line in match[1].splitlines():
        key, sep, value = line.partition(':')
        if not sep or key in fields:
            errors.append('Invalid or duplicate frontmatter field')
        fields[key] = value.strip()
    if fields.get('name') != root.name or not re.fullmatch(r'[a-z0-9-]{1,64}', fields.get('name', '')):
        errors.append('Invalid skill name')
    if not fields.get('description', '').startswith('Use when ') or len(fields.get('description','')) > 1024:
        errors.append('A concise Use when discovery description is required')
    referenced = set()
    for file in root.rglob('*'):
        if file.is_symlink():
            errors.append('Exported package must contain no symlinks')
        if not file.is_file() or file.suffix != '.md':
            continue
        content = file.read_text()
        if re.search(r'/Users/|/home/|~/.paiw|\.ai/skills|ai-proxy\.vk\.team', content):
            errors.append('Machine-specific path or private dependency in '+str(file.relative_to(root)))
        for link in re.findall(r'\]\(([^)]+)\)', content):
            if '://' in link or link.startswith('#'):
                continue
            destination = (file.parent/link.split('#')[0]).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.is_file():
                errors.append('Broken or external local reference: '+link)
            else:
                referenced.add(destination)
    for file in (root/'references').glob('*.md'):
        if file.resolve() not in referenced:
            errors.append('Unlinked reference: '+file.name)
    if root.name == 'iterm2-launch':
        # Check documentation examples only; this does not execute or prove a launch.
        try:
            content = (root/'references/resume.md').read_text()
            fixture = json.loads(re.search(r'```json\n(.*?)\n```', content, re.S)[1])
            examples = fixture['commands']
            if not isinstance(examples,list) or len(examples) < 2:
                raise ValueError()
            for example in examples:
                argv = example['expected_argv']
                if (not isinstance(argv,list) or not argv or
                        any(not isinstance(value,str) or not value for value in argv) or
                        '--resume' not in argv or '--cwd' not in argv or '--profile' not in argv):
                    raise ValueError()
                if (type(example['matches']) is not bool or
                        example['matches'] != (shlex.split(example['commandLine']) == argv)):
                    raise ValueError()
            if {example['matches'] for example in examples} != {True,False}:
                raise ValueError()
            continuations = fixture['continuations']
            if not isinstance(continuations,list) or len(continuations) < 2:
                raise ValueError()
            for example in continuations:
                if any(type(example[key]) is not bool for key in
                       ('latest_turn_verified','same_profile_cwd','matches')):
                    raise ValueError()
                if any(not isinstance(example[key],str) or not example[key]
                       for key in ('source_id','actual_id','parentSession')):
                    raise ValueError()
                if example['continuationOf'] is not None and not isinstance(example['continuationOf'],str):
                    raise ValueError()
            # These are declared synthetic observations, not a second history resolver.
            if {example['matches'] for example in continuations} != {True,False}:
                raise ValueError()
        except (OSError, ValueError, TypeError, KeyError, IndexError):
            errors.append('Invalid omp argv/continuation JSON fixtures')
    return errors


if __name__ == '__main__':
    roots = [Path(sys.argv[1])] if len(sys.argv) > 1 else [
        Path(__file__).resolve().parents[1]/'skills'/name
        for name in ('iterm2-setup', 'iterm2-launch', 'iterm2-projects')]
    errors = [(root.name+': ' if len(roots) > 1 else '')+error
              for root in roots for error in check(root)]
    for error in errors:
        print(error, file=sys.stderr)
    if not errors:
        print((f'{len(roots)} skills structurally valid' if len(roots) > 1 else 'Skill structure valid')+
              ' (not a behavioral evaluation).')
    raise SystemExit(bool(errors))
