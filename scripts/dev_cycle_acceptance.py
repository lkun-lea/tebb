"""Controller-owned objective checks, frozen before model execution."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
if __package__:
    from .dev_cycle_runtime import write_json
else:
    from dev_cycle_runtime import write_json


def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_plan(plan):
    if plan is None:
        return
    if not isinstance(plan.get('argv'), list) or not plan['argv'] or not all(isinstance(x, str) for x in plan['argv']):
        raise ValueError('客观验收须提供argv数组，不执行shell拼接')
    if not plan.get('files'):
        raise ValueError('客观验收须固定判定器文件哈希')
    if plan.get('prepare_argv')is not None and (not isinstance(plan['prepare_argv'],list)or not plan['prepare_argv']or not all(isinstance(a,str)for a in plan['prepare_argv'])):
        raise ValueError('环境准备必须提供冻结argv')
    for path, expected in plan['files'].items():
        if not Path(path).is_absolute() or fingerprint(path) != expected:
            raise ValueError('客观验收器来源发生变化：'+path)
    policy = plan.get('revision_policy')
    if policy is not None:
        root = Path(policy['root']).resolve()
        editable = policy.get('editable', [])
        names = {Path(p).resolve().relative_to(root).as_posix() for p in plan['files']}
        actual=set()
        for p in root.rglob('*'):
            if p.is_symlink()or getattr(p.lstat(),'st_file_attributes',0)&1024:
                raise ValueError('冻结验收包不能包含目录联接或符号链接')
            if '__pycache__'in p.parts or p.suffix in {'.pyc','.pyo'}:
                raise ValueError('冻结验收包不能包含未审阅的Python字节码')
            if p.is_file():actual.add(p.relative_to(root).as_posix())
        if actual!=names:raise ValueError('冻结验收包存在未封存文件')
        if (not editable or not set(editable) <= names or
                any(Path(p).is_absolute() or '..' in Path(p).parts or '\\' in p for p in editable)):
            raise ValueError('验收器修订路径必须属于冻结包')
        controls = policy.get('required_controls', [])
        if (not any(n.startswith('positive_') for n in controls) or
                not any(n.startswith('negative_') for n in controls)):
            raise ValueError('验收器修订必须有冻结的正例和负例校准')
        argv = policy.get('calibration_argv')
        if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
            raise ValueError('校准必须提供argv')
        scripts = [Path(a.replace('{validator}', str(root))).resolve() for a in argv if a.endswith('.py')]
        if not scripts or any(p not in {Path(n).resolve() for n in plan['files']} or
                              p.relative_to(root).as_posix() in editable for p in scripts):
            raise ValueError('校准入口必须冻结且不可由验收器作者修改')


def execute(plan, *, candidate, record, environment, is_cancelled, stop_process, binding=None):
    validate_plan(plan)
    record.mkdir(parents=True, exist_ok=False)
    result = record/'result.json'
    argv = [x.replace('{candidate}', str(candidate)).replace('{result}', str(result))
             .replace('{python}', environment['DEV_CYCLE_PYTHON'])
             .replace('{validator}', plan.get('revision_policy', {}).get('root', '')) for x in plan['argv']]
    receipt = dict(argv=argv, started=time.time(), candidate=str(candidate), files=plan['files'], binding=binding)
    with (record/'stdout.log').open('wb') as out, (record/'stderr.log').open('wb') as err:
        process = subprocess.Popen(argv, cwd=candidate, env=environment, stdout=out, stderr=err,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        receipt['pid'] = process.pid
        try:
            while process.poll() is None:
                if is_cancelled():
                    raise InterruptedError('用户取消客观验收')
                write_json(record/'progress.json',dict(pid=process.pid,observed=time.time(),
                    current='客观验收进程运行中；存活不代表通过'))
                time.sleep(.2)
        except BaseException:
            stop_process(process)
            raise
    receipt.update(ended=time.time(), exit_code=process.returncode)
    write_json(record/'execution.json',receipt)
    validate_plan(plan)
    if not result.is_file():
        raise ValueError('客观验收缺少结果；不得将未知当通过')
    report = json.loads(result.read_text('utf-8'))
    checks = report.get('checks')
    if (report.get('status') not in {'pass', 'fail', 'unknown'} or not isinstance(checks, list) or not checks
            or not all(isinstance(c, dict) and isinstance(c.get('name'), str)
                       and isinstance(c.get('passed'), bool) for c in checks)
            or len({c['name'] for c in checks}) != len(checks)):
        raise ValueError('客观验收格式无效或重复判定')
    if report['status'] == 'pass' and (process.returncode or not all(c['passed'] for c in checks)):
        raise ValueError('客观验收退出码或检查项与通过结论冲突')
    if report.get('failure_type') not in {'none', 'implementation', 'environment', 'evaluator', 'mixed'}:
        raise ValueError('客观验收缺少明确故障分类')
    if (report['status'] == 'pass') != (report['failure_type'] == 'none'):
        raise ValueError('客观验收通过状态与故障分类冲突')
    if report['status']!='pass'and all(c['passed']for c in checks):
        raise ValueError('全部检查通过却宣称失败，验收器判定矛盾')
    for check in checks:
        ids=check.get('criterion_ids')
        if not isinstance(ids,list)or not ids or not all(isinstance(n,str)and n for n in ids)or len(ids)!=len(set(ids)):
            raise ValueError('每项客观检查必须绑定明确的验收条件')
        if check.get('failure_type') not in {'none', 'implementation', 'environment', 'evaluator'} or type(check.get('observed')) is not bool:
            raise ValueError('每项客观检查必须记录故障来源和是否实际观察到行为')
        if check['passed'] and (check['failure_type'] != 'none' or not check['observed']):
            raise ValueError('没有实际观察不能判定通过')
        if not check['passed'] and check['failure_type'] == 'none':
            raise ValueError('未通过项必须保留原因')
        if check['failure_type'] == 'implementation' and not check['observed']:
            raise ValueError('行为未执行不能判定产品缺陷')
    return report


def seal(record):
    """Hashes bind reusable observations; a directory name or summary is not proof."""
    return {str(p.resolve()): fingerprint(p) for p in Path(record).rglob('*')
            if p.is_file() and p.suffix in {'.json', '.jsonl', '.log', '.txt', '.png'}
            and 'browser-profile' not in p.parts and '__pycache__' not in p.parts}


def verify_seal(files):
    return bool(files) and all(Path(p).is_file() and fingerprint(p) == value for p, value in files.items())


def prepare_revision(plan, destination):
    validate_plan(plan)
    policy = plan.get('revision_policy')
    if policy is None:
        raise ValueError('本验收器没有授权的修订范围和正负例校准')
    root = Path(policy['root']).resolve()
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    for name in plan['files']:
        source = Path(name)
        if source.is_symlink() or getattr(source.lstat(),'st_file_attributes',0)&1024:
            raise ValueError('验收包不能包含符号链接')
        target = destination/source.resolve().relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return destination


def revised_plan(original, destination):
    """Keep sealed controls immutable and allow only the declared oracle edits."""
    validate_plan(original)
    root = Path(original['revision_policy']['root']).resolve()
    destination = Path(destination).resolve()
    old = {Path(p).resolve().relative_to(root).as_posix(): value for p, value in original['files'].items()}
    actual = {}
    for p in destination.rglob('*'):
        if p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&1024:
            raise ValueError('修订包不能引入符号链接')
        if p.is_file():
            actual[p.relative_to(destination).as_posix()] = fingerprint(p)
    if set(actual) != set(old):
        raise ValueError('修订不能添加或删除冻结文件')
    changed = {p for p in old if old[p] != actual[p]}
    if not changed or not changed <= set(original['revision_policy']['editable']):
        raise ValueError('验收器修订无变化或修改了封存控制文件')
    result = json.loads(json.dumps(original))
    result['argv'] = [a.replace(str(root), str(destination)) for a in result['argv']]
    if result.get('prepare_argv'):result['prepare_argv']=[a.replace(str(root),str(destination))for a in result['prepare_argv']]
    result['files'] = {str(destination/p): value for p, value in actual.items()}
    result['revision_policy']['root'] = str(destination)
    result['revision_policy']['calibration_argv'] = [a.replace(str(root), str(destination))
                                                   for a in result['revision_policy']['calibration_argv']]
    validate_plan(result)
    return result, sorted(changed)


def calibration_plan(plan):
    result = json.loads(json.dumps(plan))
    result['argv'] = result['revision_policy']['calibration_argv']
    return result


def check_calibration(plan, report):
    required = set(plan['revision_policy']['required_controls'])
    actual = {row['name'] for row in report['checks']}
    if report['status'] != 'pass' or actual != required or not all(row['passed'] and row['observed'] for row in report['checks']):
        raise ValueError('冻结正负例校准未通过，不得审查或采用验收器修订')
