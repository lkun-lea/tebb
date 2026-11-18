"""Content identity for executable product/evaluation code, excluding dependencies."""
import os
from functools import lru_cache
from pathlib import Path
from desk_companion.infrastructure.paths import source_root
from desk_companion.observability.tool_monitor import fingerprint


def code_version():
    root=source_root();files=[]
    for directory in ('desk_companion','scripts','client/src'):
        for path,folders,names in os.walk(root/directory):
            folders[:]=[n for n in folders if n not in {'node_modules','__pycache__'}]
            files.extend(Path(path)/name for name in names if Path(name).suffix in {'.py','.mjs','.ts','.tsx','.css'})
    files.extend(root/name for name in ('pyproject.toml','uv.lock','skills-source.json',
        'desk_companion/pi_runtime/package.json','desk_companion/pi_runtime/package-lock.json',
        'desk_companion/evaluation/promptfoo/package.json','desk_companion/evaluation/promptfoo/package-lock.json',
        'client/package.json','client/pnpm-lock.yaml')if(root/name).is_file())
    return fingerprint({str(p.relative_to(root)):fingerprint(p.read_text('utf-8'))for p in sorted(files)})


@lru_cache(maxsize=1)
def process_code_version():
    """Observed source content at this process's first model call; restart after edits."""
    return code_version()
