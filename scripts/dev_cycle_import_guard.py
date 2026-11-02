"""Installed in the task's clean Python environment; never loads host .pth files."""
import hashlib
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import sys
import time


def install(dependencies):
    root = Path(os.environ['DEV_CYCLE_SOURCE_ROOT']).resolve()
    audit = Path(os.environ['DEV_CYCLE_IMPORT_LOG'])
    names = {p.stem for p in root.glob('*.py')}
    names.update(p.name for p in root.iterdir() if p.is_dir() and
                 ((p/'__init__.py').exists() or any(p.glob('*.py'))))

    class ProjectImports(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname.split('.')[0] not in names:
                return None
            spec = importlib.machinery.PathFinder.find_spec(fullname, path)
            locations = [] if spec is None else ([spec.origin] if spec.origin not in {None, 'namespace'} else [])
            if spec is not None:
                locations += list(spec.submodule_search_locations or [])
            # Namespace parents contain search locations, not executable code.
            # Keep Python's namespace semantics; each concrete child is checked
            # independently before its loader can execute a foreign file.
            namespace = spec is not None and spec.origin in {None, 'namespace'} and bool(spec.submodule_search_locations)
            local = [p for p in locations if root == Path(p).resolve() or root in Path(p).resolve().parents]
            allowed = bool(local) if namespace else bool(locations) and len(local) == len(locations)
            row = dict(time=time.time(), pid=os.getpid(), module=fullname, checkout=str(root),
                       paths=locations, allowed=allowed, kind='namespace_search' if namespace else 'module',
                       reason='namespace_contains_candidate' if namespace and allowed else
                              'candidate_module' if allowed else 'module_source_outside_candidate')
            if allowed and spec.origin and Path(spec.origin).is_file():
                row['sha256'] = hashlib.sha256(Path(spec.origin).read_bytes()).hexdigest()
            try:
                audit.mkdir(parents=True, exist_ok=True)
                with (audit/f'{os.getpid()}.jsonl').open('a', encoding='utf-8') as stream:
                    stream.write(json.dumps(row, ensure_ascii=True)+'\n')
            except OSError as exc:
                raise ImportError('dev-cycle source audit unavailable; refusing unaudited project import') from exc
            if not allowed:
                raise ImportError(f'dev-cycle source mismatch: {fullname}; expected {root}')
            return spec

    sys.meta_path.insert(0, ProjectImports())
    sys.path.insert(0, str(root))
    # Append explicit dependency directories; addsitedir would execute editable .pth hooks.
    for entry in dependencies:
        if entry not in sys.path:
            sys.path.append(entry)
