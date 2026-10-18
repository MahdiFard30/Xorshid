#!/usr/bin/env python3
"""Common local commands, runnable from any working directory."""
import argparse
import ast
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def check_project():
    """Validate source, metadata and local document links without changing files."""
    failures = []
    sources = [ROOT / 'khorshid.py', ROOT / 'khorshid_live.py']
    for folder in ('ultimate_khorshid', 'scripts', 'tests', 'evals', 'examples'):
        sources.extend((ROOT / folder).rglob('*.py'))
    for path in sources:
        try:
            ast.parse(path.read_text(encoding='utf-8'), filename=str(path), feature_version=(3, 10))
        except (OSError, SyntaxError) as exc:
            failures.append(f'{path.relative_to(ROOT)}: {type(exc).__name__}')
    try:
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib
        with (ROOT / 'pyproject.toml').open('rb') as stream:
            tomllib.load(stream)
    except (ImportError, OSError, ValueError) as exc:
        failures.append(f'pyproject.toml: {type(exc).__name__}')
    documents = list((ROOT / 'docs').rglob('*.md'))
    for path in documents:
        for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            if link.startswith(('https:', 'http:', 'mailto:', '#', '/')):
                continue
            target = link.split('#', 1)[0]
            if target and not (path.parent / target).exists():
                failures.append(f'{path.relative_to(ROOT)}: missing link {target}')
    if not (ROOT / 'ultimate_khorshid/assets/khorshid_sun_final.png').is_file():
        failures.append('Desktop image asset is missing')
    for item in failures:
        print('ERROR: ' + item)
    if failures:
        return 1
    print(f'OK: {len(sources)} Python files (3.10 syntax), project metadata, {len(documents)} documents and their local links.')
    return 0


def command_for(action):
    python = ROOT / '.venv/bin/python'
    executable = str(python) if python.is_file() else sys.executable
    commands = {
        'run': [executable, str(ROOT / 'khorshid.py')],
        'live': [executable, str(ROOT / 'khorshid_live.py')],
        'doctor': [executable, '-m', 'ultimate_khorshid.cli.main', 'doctor'],
        'test': [executable, str(ROOT / 'tests/run_offline.py')],
    }
    return commands[action]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'live', 'doctor', 'test', 'check'))
    args = parser.parse_args(argv)
    if args.action == 'check':
        return check_project()
    try:
        return subprocess.call(command_for(args.action), cwd=ROOT)
    except KeyboardInterrupt:
        return 130


if __name__ == '__main__':
    raise SystemExit(main())
