#!/usr/bin/env python3
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REMOVED: list[str] = []

# These files are never source/runtime inputs. They can appear when a ZIP is
# created from a previously tested working tree or when a repo was uploaded
# through a browser, which may bypass local .gitignore behaviour.
for dname in ('__pycache__', '.pytest_cache'):
    for path in sorted(ROOT.rglob(dname)):
        if not path.is_dir() or '.git' in path.parts:
            continue
        try:
            rel = str(path.relative_to(ROOT))
        except ValueError:
            rel = str(path)
        shutil.rmtree(path, ignore_errors=True)
        REMOVED.append(rel + '/')

for path in sorted(ROOT.rglob('*')):
    if not path.is_file() or '.git' in path.parts:
        continue
    if path.suffix.lower() in {'.pyc', '.pyo'} or path.name.endswith(('.tmp', '.bak')):
        try:
            rel = str(path.relative_to(ROOT))
        except ValueError:
            rel = str(path)
        try:
            path.unlink()
            REMOVED.append(rel)
        except FileNotFoundError:
            pass

print(f'Generated artifact cleanup: removed {len(REMOVED)} path(s)')
for item in REMOVED[:20]:
    print(f'  - {item}')
if len(REMOVED) > 20:
    print(f'  ... +{len(REMOVED)-20} more')
