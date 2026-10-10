"""Bounded discovery beneath a requested ancestor; never index source files."""
import os
from pathlib import Path

EXCLUSIONS = frozenset(('.git', '.nebula', '.nebula-reports', '.superpowers', '.venv',
                        'venv', 'node_modules', 'target', 'dist', 'build', '__pycache__'))


def discover_roots(root, *, max_directories=10000, max_depth=12,
                   max_nebulas=100, max_entries=100000):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('stats root must be an existing directory')
    if any(type(v) is not int or v < 0 for v in (max_directories, max_depth, max_nebulas, max_entries)):
        raise ValueError('discovery limits must be nonnegative integers')
    result = {'roots': [], 'complete': True, 'visited': 0, 'entries': 0,
              'exclusions': sorted(EXCLUSIONS), 'warnings': []}
    pending = [(root, 0)]
    while pending:
        if result['visited'] >= max_directories:
            result['warnings'].append('Directory limit reached; discovery incomplete')
            result['complete'] = False
            break
        directory, depth = pending.pop()
        result['visited'] += 1
        try:
            if directory.is_symlink():
                continue
            state = directory / '.nebula'
            if state.exists() or state.is_symlink():
                if len(result['roots']) >= max_nebulas:
                    result['warnings'].append('Nebula limit reached; discovery incomplete')
                    result['complete'] = False
                    break
                result['roots'].append(directory)
            children = []
            with os.scandir(directory) as entries:
                for entry in entries:
                    if result['entries'] >= max_entries:
                        result['warnings'].append('Directory entry limit reached; discovery incomplete')
                        result['complete'] = False
                        return result
                    result['entries'] += 1
                    if entry.name in EXCLUSIONS or entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        continue
                    if depth >= max_depth:
                        result['complete'] = False
                        if 'Depth limit reached; discovery incomplete' not in result['warnings']:
                            result['warnings'].append('Depth limit reached; discovery incomplete')
                    else:
                        children.append(Path(entry.path))
            pending.extend((child, depth + 1) for child in sorted(children, reverse=True))
        except OSError as exc:
            result['complete'] = False
            result['warnings'].append(f'Cannot inspect {directory}: {exc}')
    return result
