"""Local Git inputs for the tebb delivery bridge. Commands run in the terminal sandbox."""
from hashlib import sha256
from io import BytesIO
from pathlib import PurePosixPath
from subprocess import check_output
from zipfile import ZipFile
import os
import re


def git(repo, *args):
    return check_output(['git', '-C', str(repo), *args], timeout=40)


def validate_source(repo, frozen):
    base, commit = frozen['base'], frozen['commit']
    if any(not re.fullmatch(r'[a-f0-9]{40}', item) for item in (base, commit)):
        raise ValueError('候选和基准必须是完整提交。')
    origin = git(repo, 'config', '--get', 'remote.origin.url').decode().strip().removesuffix('.git')
    if origin not in {f"https://github.com/{frozen['repository']}", f"git@github.com:{frozen['repository']}"}:
        raise ValueError('本机仓库与派发仓库不一致。')
    if git(repo, 'merge-base', base, commit).decode().strip() != base:
        raise ValueError('候选提交不属于固定基准。')


def patch_digest(patch):
    if not patch or len(patch) > 512 * 1024:
        raise ValueError('首版候选补丁必须在 1 字节至 512 KiB 内。')
    return sha256(patch).hexdigest()


def install(repo, commit, workspace):
    with ZipFile(BytesIO(git(repo, 'archive', '--format=zip', commit))) as archive:
        if sum(entry.file_size for entry in archive.infolist()) > 96 * 1024 * 1024:
            raise ValueError('候选快照超过 96 MiB。')
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename or ':' in entry.filename
                    or entry.external_attr >> 28 == 0o12):
                raise ValueError('候选包含不支持的文件路径或符号链接。')
        location = str(workspace.resolve())
        if os.name == 'nt' and not location.startswith('\\\\?\\'):
            location = '\\\\?\\UNC\\' + location[2:] if location.startswith('\\\\') else '\\\\?\\' + location
        archive.extractall(location)


def prepare(repo, frozen, workspace):
    validate_source(repo, frozen)
    base, commit = frozen['base'], frozen['commit']
    patch = git(repo, '-c', 'core.quotePath=true', 'diff', '--no-ext-diff', '--no-textconv', '--no-renames',
                '--no-color', '--src-prefix=a/', '--dst-prefix=b/', '--binary', base, commit, '--')
    digest = patch_digest(patch)
    if frozen['digest'] and frozen['digest'] != digest:
        raise ValueError('本机候选摘要与派发不一致。')
    install(repo, commit, workspace)
    return patch, digest
