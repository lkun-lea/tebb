"""Project-owned Atlas pin and reproducible embedded-runtime export from uv.lock."""
import argparse
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[1]
HEADER = '# Generated from uv.lock by uv run scripts/python_dependencies.py export; do not edit.\n'


def atlas_ref(root=ROOT):
    project = tomllib.loads((Path(root) / 'pyproject.toml').read_text('utf-8'))
    matches = [re.fullmatch(r'atlas @ git\+https://github\.com/lkun-lea/Atlas\.git@([a-f0-9]{40})', value)
               for value in project['project']['dependencies'] if value.startswith('atlas ')]
    if len(matches) != 1 or matches[0] is None:
        raise ValueError('Atlas 必须在 pyproject.toml 中固定官方仓库的完整提交。')
    return matches[0][1]


def runtime_export(root=ROOT):
    result = subprocess.run(['uv', 'export', '--locked', '--format', 'requirements-txt',
                             '--no-default-groups', '--group', 'runtime', '--no-emit-project',
                             '--no-emit-package', 'atlas', '--no-header', '--no-annotate'],
                            cwd=root, check=True, capture_output=True, text=True, encoding='utf-8')
    return HEADER + result.stdout.replace('\r\n', '\n')


def export_runtime(*, root=ROOT, check=False):
    expected = runtime_export(root)
    target = Path(root) / 'scripts/runtime-lock.txt'
    if check:
        if not target.is_file() or target.read_text('utf-8') != expected:
            raise ValueError('发布依赖清单已过期：运行 uv run scripts/python_dependencies.py export。')
    else:
        target.write_text(expected, encoding='utf-8', newline='\n')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['export', 'check'])
    args = parser.parse_args()
    print(export_runtime(check=args.command == 'check'))


if __name__ == '__main__':
    main()
