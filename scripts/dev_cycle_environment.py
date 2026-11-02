"""Standard private dependency installation and pre-model import checks."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tomllib
import venv


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def node_dependencies(source,on_progress=None):
    """Hash actual private dependency inputs, excluding derived development caches."""
    root=Path(source)/'client/node_modules'
    if not root.exists():return None
    if root.is_symlink()or getattr(root.lstat(),'st_file_attributes',0)&1024:
        raise ValueError('Node依赖必须属于当前隔离副本，不能使用目录联接')
    root=root.resolve();digest=hashlib.sha256();count=0;pending=[root]
    while pending:
        current=pending.pop()
        with os.scandir(current)as scan:entries=sorted(scan,key=lambda entry:entry.name)
        for entry in entries:
            path=Path(entry.path);relative=path.relative_to(root).as_posix();metadata=entry.stat(follow_symlinks=False)
            if entry.is_symlink()or getattr(metadata,'st_file_attributes',0)&1024:
                target=path.resolve()
                if root not in target.parents:raise ValueError('Node依赖链接跳出任务环境：'+relative)
                digest.update(json.dumps(['link',relative,target.relative_to(root).as_posix()]).encode())
            elif entry.is_dir(follow_symlinks=False):
                if entry.name not in {'.vite','.cache','__pycache__'}:pending.append(path)
            elif entry.is_file(follow_symlinks=False):
                file_hash=hashlib.sha256()
                with path.open('rb')as stream:
                    for block in iter(lambda:stream.read(1024*1024),b''):file_hash.update(block)
                digest.update(json.dumps(['file',relative,file_hash.hexdigest()]).encode());count+=1
                if on_progress and count%500==0:on_progress(dict(files=count,last=relative,complete=False))
    if on_progress:on_progress(dict(files=count,complete=True))
    return dict(root=str(root),files=count,sha256=digest.hexdigest())


def requirements(source, dependency_paths=()):
    source = Path(source)
    # The release runtime lock targets its embedded interpreter, which may be
    # different from the development interpreter. Do not select it implicitly.
    plan = None
    for name in ('requirements.lock', 'requirements.txt'):
        path = source/name
        if path.is_file():
            plan = dict(origin=name, text=path.read_text('utf-8-sig'))
            break
    project = source/'pyproject.toml'
    if plan is None and project.exists():
        data = tomllib.loads(project.read_text('utf-8'))
        if 'dependencies' in data.get('project', {}).get('dynamic', []):
            raise ValueError('动态依赖需先提供固定requirements文件')
        plan = dict(origin='pyproject.toml:project.dependencies',
                    text='\n'.join(data.get('project', {}).get('dependencies', []))+'\n')
    plan = plan or dict(origin='stdlib', text='')
    extras = []
    for dependency in dependency_paths:
        extra = requirements(dependency)
        if extra['text'].strip():
            extras.append(dict(path=str(Path(dependency).resolve()), **extra))
    return dict(**plan, source_dependencies=extras) if not extras else dict(
        origin=plan['origin'], text=plan['text']+'\n'+'\n'.join(extra['text'] for extra in extras), source_dependencies=extras)


def layout(folder):
    folder = Path(folder)
    python = folder/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    site = folder/('Lib/site-packages' if os.name == 'nt' else f'lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages')
    return python, site


def customization(dependency_paths):
    return 'from dev_cycle_import_guard import install\ninstall('+repr(dependency_paths)+')\n'


def identity(source, dependency_paths):
    plan = requirements(source, dependency_paths)
    return dict(format=1, base_python=sys.executable, version=sys.version, requirements=plan,
                dependency_paths=[str(Path(p).resolve()) for p in dependency_paths],
                guard_sha256=sha(Path(__file__).with_name('dev_cycle_import_guard.py')))


def clean_environment():
    env = {k:v for k,v in os.environ.items() if not k.startswith(('DEV_CYCLE_', 'PIP_'))
           and k not in {'PYTHONHOME', 'PYTHONPATH', 'VIRTUAL_ENV'}}
    env.update(PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PIP_CONFIG_FILE=os.devnull)
    return env


def prepare_environment(folder, source, record, dependency_paths=(), *, wheelhouse=None, offline=False):
    """Install dependencies using pip, never append host site-packages or run its .pth."""
    folder, source, record = Path(folder).resolve(), Path(source).resolve(), Path(record)
    record.mkdir(parents=True, exist_ok=True)
    python, site = layout(folder)
    expected = identity(source, dependency_paths)
    manifest = folder/'environment.json'
    if manifest.exists():
        current = json.loads(manifest.read_text('utf-8'))
        if (current['identity'] != expected or sha(site/'dev_cycle_import_guard.py') != expected['guard_sha256'] or
                (site/'sitecustomize.py').read_text('utf-8') != customization(expected['dependency_paths'])):
            raise ValueError('任务环境清单或校验器已变化；保留原环境，使用新任务准备依赖')
        return current
    # Only our own interrupted preparation with the identical plan can resume.
    marker = folder/'preparing.json'
    if folder.exists():
        if not marker.is_file() or json.loads(marker.read_text('utf-8')) != expected:
            raise ValueError('不采用来历未知或清单变化的未完成环境')
    else:
        venv.EnvBuilder(with_pip=False, system_site_packages=False).create(folder)
        marker.write_text(json.dumps(expected, ensure_ascii=True, indent=2), 'utf-8')
    plan = expected['requirements']
    frozen = record/'requirements.txt'
    frozen.write_text(plan['text'], 'utf-8')
    # Relative includes would otherwise resolve against this copied file, silently
    # selecting a different plan. This interface takes a dependency list, not pip configuration.
    for line in plan['text'].splitlines():
        if line.strip().startswith('-'):
            raise ValueError('依赖清单含pip配置/嵌套引用；请提供展开的依赖清单')
    env = clean_environment()
    env.update(DEV_CYCLE_SOURCE_ROOT=str(source), DEV_CYCLE_IMPORT_LOG=str((record/'evidence/imports').resolve()))
    command = [sys.executable, '-m', 'pip', '--python', str(python), '--disable-pip-version-check']
    installed = any(line.strip() and not line.lstrip().startswith('#') for line in plan['text'].splitlines())
    with (record/'install.log').open('wb') as log:
        if installed:
            args = command+['install', '--no-input', '-r', str(frozen),
                            '--report', str(record/'install-report.json')]
            if offline:
                args += ['--no-index']
            if wheelhouse is not None:
                if not Path(wheelhouse).is_dir():
                    raise ValueError('wheelhouse目录不存在')
                args += ['--find-links', str(Path(wheelhouse).resolve())]
            print('正在准备任务依赖，原始日志：'+str(record/'install.log'), file=sys.stderr, flush=True)
            result = subprocess.run(args, cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise ValueError('任务依赖安装失败，未启动模型；查看 '+str(record/'install.log'))
            checked = subprocess.run(command+['check'], cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT)
            if checked.returncode:
                raise ValueError('任务依赖一致性检查失败；查看 '+str(record/'install.log'))
    inventory = subprocess.run([str(python), '-c',
        'import importlib.metadata as m,json;print(json.dumps(sorted((d.metadata["Name"],d.version) for d in m.distributions())))'],
        cwd=source, env=env, capture_output=True, text=True)
    if inventory.returncode:
        raise ValueError('无法读取任务依赖清单：'+inventory.stderr)
    shutil.copyfile(Path(__file__).with_name('dev_cycle_import_guard.py'), site/'dev_cycle_import_guard.py')
    (site/'sitecustomize.py').write_text(customization(expected['dependency_paths']), 'utf-8')
    value = dict(identity=expected, distributions=json.loads(inventory.stdout),
                 install_report_sha256=sha(record/'install-report.json') if installed else None)
    manifest.write_text(json.dumps(value, ensure_ascii=True, indent=2), 'utf-8')
    return value


def python_environment(folder, source, record, dependency_paths=(), *, evidence_dir=None):
    folder, source, record = Path(folder).resolve(), Path(source).resolve(), Path(record)
    # Standalone stdlib-only probes need no package installer. Real project
    # dependencies must be explicitly prepared before any model is launched.
    if not (folder/'environment.json').exists():
        plan = requirements(source, dependency_paths)
        if any(line.strip() and not line.lstrip().startswith('#') for line in plan['text'].splitlines()):
            raise ValueError('任务依赖尚未准备；先运行 dev_cycle.py prepare')
    prepare_environment(folder, source, record, dependency_paths)
    python, _ = layout(folder)
    env = clean_environment()
    env.update(PYTHONPATH=str(source), VIRTUAL_ENV=str(folder),
               PATH=str(python.parent)+os.pathsep+env.get('PATH', ''),
               DEV_CYCLE_SOURCE_ROOT=str(source), DEV_CYCLE_PYTHON=str(python),
               DEV_CYCLE_IMPORT_LOG=str(((Path(evidence_dir) if evidence_dir is not None else record/'evidence')/'imports').resolve()))
    return env


def verify_imports(record, *, evidence_dir=None):
    root = Path(evidence_dir) if evidence_dir is not None else Path(record)/'evidence'
    for path in (root/'imports').glob('*.jsonl'):
        for line in path.read_text('utf-8').splitlines():
            row = json.loads(line)
            if row.get('allowed') is not True:
                raise ValueError('源码来源校验未通过；导入已拒绝，不能据此认定执行了外部源码：'+row.get('module', '?'))


PREFLIGHT = r'''
import importlib,importlib.util,importlib.metadata,json,os,pathlib,subprocess,sys
root=pathlib.Path(os.environ['DEV_CYCLE_SOURCE_ROOT']).resolve()
rows=[]
for name in sorted({p.stem for p in root.glob('*.py')} | {p.name for p in root.iterdir() if p.is_dir() and ((p/'__init__.py').exists() or any(p.glob('*.py')))}):
    spec=importlib.util.find_spec(name)
    rows.append(dict(module=name,origin=spec.origin if spec else None,paths=list(spec.submodule_search_locations or []) if spec else []))
for name in ['desk_companion.tasks'] if (root/'desk_companion/tasks.py').exists() else []:
    module=importlib.import_module(name)
    rows.append(dict(module=name,origin=module.__file__))
try:importlib.metadata.distribution('pywin32');has_pywin32=True
except importlib.metadata.PackageNotFoundError:has_pywin32=False
if sys.platform=='win32' and has_pywin32:
    for name in ['win32crypt','pywintypes']:
        module=importlib.import_module(name)
        rows.append(dict(module=name,origin=module.__file__))
if '--child' not in sys.argv:
    child=subprocess.run([sys.executable,__file__,'--child'],capture_output=True,text=True)
    if child.returncode:raise RuntimeError(child.stderr)
    print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,modules=rows,child=json.loads(child.stdout))))
else:print(json.dumps(dict(executable=sys.executable,prefix=sys.prefix,modules=rows)))
'''


def preflight_environment(folder, source, record, dependency_paths=()):
    record = Path(record)
    record.mkdir(parents=True, exist_ok=True)
    (record/'evidence').mkdir(exist_ok=True)
    script = record/'probe.py'
    script.write_text(PREFLIGHT, 'utf-8')
    try:
        env = python_environment(folder, source, record, dependency_paths)
        result = subprocess.run([env['DEV_CYCLE_PYTHON'], str(script.resolve())], cwd=source,
                                env=env, capture_output=True, text=True, encoding='utf-8')
        (record/'stdout.json').write_text(result.stdout, 'utf-8')
        (record/'stderr.log').write_text(result.stderr, 'utf-8')
        if result.returncode:
            raise ValueError('环境导入预检失败；查看 '+str(record/'stderr.log'))
        verify_imports(record)
        report = dict(status='ready', result=json.loads(result.stdout))
    except Exception as exc:
        report = dict(status='blocked', error=f'{type(exc).__name__}: {exc}')
        (record/'result.json').write_text(json.dumps(report, ensure_ascii=True, indent=2), 'utf-8')
        raise
    (record/'result.json').write_text(json.dumps(report, ensure_ascii=True, indent=2), 'utf-8')
    return report
