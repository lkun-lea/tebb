"""Export a verified, committed official skill snapshot, never a working tree."""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import uuid
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def read_lock(path=None):
    from desk_companion.integrations.skill_catalog import validate_source_manifest
    lock=json.loads(Path(path or ROOT/'skills-source.json').read_text('utf-8'))
    return validate_source_manifest(lock)


def snapshot(source,lock_path=None):
    lock=read_lock(lock_path)
    archive=subprocess.check_output(['git','-c','core.autocrlf=false','-C',str(source),'archive','--format=zip',lock['commit'],'--',*sorted(lock['files'])],stderr=subprocess.PIPE)
    result={}
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        for entry in package.infolist():
            path=PurePosixPath(entry.filename);mode=entry.external_attr>>16
            if path.is_absolute() or '..' in path.parts or '\\' in entry.filename or ':' in entry.filename or stat.S_ISLNK(mode):raise ValueError('Unsafe skill archive member.')
            if entry.is_dir():continue
            if stat.S_IFMT(mode) not in {0,stat.S_IFREG} or entry.filename not in lock['files']:raise ValueError('Unexpected skill archive member.')
            data=package.read(entry)
            if hashlib.sha256(data).hexdigest()!=lock['files'][entry.filename]:raise ValueError('Official skill digest mismatch.')
            if entry.filename.startswith('skills/'):
                text=data.decode('utf-8');match=re.fullmatch(r'---\r?\n(.*?)\r?\n---\r?\n(.+)',text,re.S)
                if not match or not match[2].strip():raise ValueError('Invalid skill document.')
                metadata=dict(line.split(':',1) for line in match[1].splitlines() if ':' in line)
                if metadata.get('name','').strip()!=path.parts[1] or not metadata.get('description','').strip():raise ValueError('Invalid skill metadata.')
            result[entry.filename]=data
    if set(result)!=set(lock['files']):raise ValueError('Incomplete pinned skill snapshot.')
    return lock,result


def export_snapshot(source,destination,lock_path=None):
    lock,files=snapshot(source,lock_path)
    destination=Path(destination).absolute()
    if destination.is_symlink() or getattr(destination,'is_junction',lambda:False)():raise ValueError('Skill destination must not be a link.')
    mapped={name.removeprefix('skills/'):data for name,data in files.items()}
    # Check every target before touching anything. Edited/custom content is never overwritten.
    for name,data in mapped.items():
        path=destination/name
        if not path.resolve().is_relative_to(destination.resolve()):raise ValueError('Skill target escapes destination.')
        current=path
        while current!=destination:
            if current.is_symlink() or getattr(current,'is_junction',lambda:False)():raise ValueError('Skill target contains a link.')
            current=current.parent
        if path.exists() and path.read_bytes().replace(b'\r\n',b'\n')!=data:raise ValueError(f'Existing content differs: {name}. Export into a new directory; custom content is preserved.')
    metadata=destination/'source.json'
    if metadata.is_symlink() or not metadata.resolve().is_relative_to(destination.resolve()):raise ValueError('Skill metadata target contains a link.')
    encoded=json.dumps(lock,sort_keys=True,indent=2).encode('utf-8')+b'\n'
    if metadata.exists() and metadata.read_bytes()!=encoded:raise ValueError('Destination contains another skill snapshot; use a new directory.')
    destination.mkdir(parents=True,exist_ok=True)
    for name,data in {**mapped,'source.json':encoded}.items():
        path=destination/name;path.parent.mkdir(parents=True,exist_ok=True)
        if path.exists() and path.read_bytes()==data:continue
        temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_bytes(data);os.replace(temporary,path)
        finally:temporary.unlink(missing_ok=True)
    return lock
