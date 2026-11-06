"""Bounded maintenance outbox, future releases and immutable validation receipts."""
from pathlib import Path
import hashlib
import importlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time


def api():
    return importlib.import_module((__package__+'.' if __package__ else '')+'dev_cycle')


def files(root):
    for p in Path(root).rglob('*'):
        if p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&getattr(stat,'FILE_ATTRIBUTE_REPARSE_POINT',1024):
            raise ValueError('流程包不能包含符号链接或目录联接：'+str(p))
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob('*')) if p.is_file() and not {'.git','__pycache__'}&set(p.parts)}


def safe_name(name):
    path=Path(name)
    if path.is_absolute() or '..'in path.parts or not path.parts or ':'in name or '\\'in name:
        raise ValueError('维护路径必须是包内正向相对路径')
    return path


def pin_runtime(folder):
    """The CLI continues this task with its own code, never an updated checkout."""
    a=api();destination=Path(folder)/'controller/scripts';destination.mkdir(parents=True)
    for source in Path(__file__).parent.glob('dev_cycle*.py'):shutil.copyfile(source,destination/source.name)
    a.write(Path(folder)/'runtime.json',dict(version=a.VERSION,script=str(destination/'dev_cycle.py'),files=files(destination.parent)))


def runtime_target(folder):
    a=api();path=Path(folder)/'runtime.json'
    if not path.exists():return None
    data=a.read(path);script=Path(data['script']).resolve()
    if a.read(Path(folder)/'state.json')['version']!=data['version']:raise ValueError('历史任务只读保留；任务协议与固定控制器不一致')
    if files(script.parent.parent)!=data['files']:raise ValueError('任务固定控制器发生变化')
    return script


def sealed(root):
    return {str(Path(root).resolve()/name):value for name,value in files(root).items()}


def verify_sealed(values):
    return bool(values) and all(Path(name).is_file() and hashlib.sha256(Path(name).read_bytes()).hexdigest()==value for name,value in values.items())


def review_path(name):
    """Canonical file identity without turning links into trusted path aliases."""
    path=Path(name)
    if not path.is_absolute():raise ValueError('不是绝对路径')
    for part in (path,*path.parents):
        try:metadata=part.lstat()
        except FileNotFoundError:continue  # Missing sealed files are reported by inspection.
        if stat.S_ISLNK(metadata.st_mode) or getattr(metadata,'st_file_attributes',0)&1024:
            raise ValueError('链接')
    return path.resolve()


def review_evidence_manifest(job,policy,snapshot,validation,developer_record):
    """Build trust before review, only from controller-owned roots and explicit refs."""
    entries={}
    def add(name,expected,kind):
        path=review_path(name)
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
            raise ValueError('维护证据封存前已变化：'+str(path))
        entries[str(path)]=dict(path=str(path),sha256=expected,kind=kind,size=path.stat().st_size)
    for directory,kind in [(snapshot,'candidate'),(validation,'validation'),
                            (developer_record.parent/'development-artifacts'/developer_record.name,'developer')]:
        if directory.exists():
            for name,expected in sealed(directory).items():add(name,expected,kind)
    for proposal in [job['proposal'],*job.get('aliases',[])]:
        for ref in proposal.get('evidence_index',[]):add(ref['path'],ref['sha256'],'proposal')
    for ref in policy.get('historical_evidence',[]):add(ref['path'],ref['sha256'],'historical')
    return dict(format=1,files=list(entries.values()),
                allowed_files={name:entry['sha256']for name,entry in entries.items()if entry['size']>0},
                source_seal={name:entry['sha256']for name,entry in entries.items()})


def check_review_evidence(review,manifest):
    failures=[]
    def reject(path,reason):
        item=dict(path=str(path),reason=reason)
        if item not in failures:failures.append(item)
    def inspect(path,expected,nonempty=False):
        try:
            review_path(path)
            metadata=path.lstat()
            if path.is_symlink() or getattr(metadata,'st_file_attributes',0)&1024:reject(path,'链接');return
            if not path.is_file():reject(path,'非普通文件');return
            if nonempty and not metadata.st_size:reject(path,'空文件');return
            if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:reject(path,'哈希改变')
        except FileNotFoundError:reject(path,'不存在')
        except ValueError as exc:reject(path,str(exc))
        except OSError as exc:reject(path,'读取失败：'+str(exc))
    for name,expected in manifest['source_seal'].items():inspect(Path(name),expected)
    for evidence in review['evidence']:
        path=Path(evidence['path'])
        # Do not infer new trust from reviewer-selected siblings or links.
        try:key=str(review_path(path))
        except ValueError as exc:reject(path,str(exc));continue
        except OSError as exc:reject(path,'读取失败：'+str(exc));continue
        if key not in manifest['allowed_files']:reject(path,'未预封存')
        else:inspect(path,manifest['allowed_files'][key],nonempty=True)
    if failures:raise ValueError('维护审查证据门禁失败：'+json.dumps(failures,ensure_ascii=False))


def validation_environment(policy,source):
    env={key:value for key,value in os.environ.items()if not key.startswith('DEV_CYCLE_') and key not in {'PYTHONHOME','PYTHONPATH','VIRTUAL_ENV'}}
    env.update(DEV_CYCLE_PYTHON=str(policy.get('validation_python',sys.executable)),PYTHONPATH=str(source),
               PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',DEV_CYCLE_SOURCE_ROOT=str(source),
               DEV_CYCLE_BASELINE=str(Path(policy['source_bundle']).resolve()))
    return env


def selected_release(policy, *, _locked=False):
    if not policy:return None
    a=api();root=Path(policy['root']).resolve();registry=root/'active-release.json'
    if not registry.exists():return None
    if not _locked:
        with a.locked(root):return selected_release(policy,_locked=True)
    check_policy(policy)
    data=a.read(registry)
    if data.get('status')=='rolled_back':return None
    adoption_path=Path(data['adoption_path']).resolve()
    if adoption_path.parent!=root/'adoptions' or hashlib.sha256(adoption_path.read_bytes()).hexdigest()!=data['adoption_sha256']:
        raise ValueError('采用回执来源变化')
    adoption=a.read(adoption_path)
    if adoption['policy_sha256']!=a.digest(policy) or data['id']!=adoption['id']:
        raise ValueError('采用策略身份不一致')
    if not verify_sealed(adoption['evidence_seal']):raise ValueError('维护验证或审查证据变化')
    release=(root/'releases'/adoption['id']).resolve()
    if release.parent!=root/'releases' or files(release)!=adoption['files']:raise ValueError('已采用流程包来源变化')
    if data['status']=='trial':
        record=root/'canary'/data['id'];record.parent.mkdir(exist_ok=True)
        if record.exists():raise ValueError('试用检查曾中断，保留原记录供核查')
        try:
            execute_check(policy['canary'],release,record,validation_environment(policy,release))
            check_policy(policy)
            if files(release)!=adoption['files'] or not verify_sealed(adoption['evidence_seal']):raise ValueError('试用改写候选或采用证据')
            data.update(status='confirmed',canary_seal=sealed(record))
            a.write(registry,data)
            a.write(root/'release-events'/('confirmed-'+data['id']+'.json'),data)
        except InterruptedError:
            raise
        except Exception as exc:
            event=dict(status='rolled_back',id=data['id'],error=f'{type(exc).__name__}: {exc}',
                       record=str(record),previous=data.get('previous'),at=time.time())
            a.write(root/'release-events'/('rollback-'+data['id']+'.json'),event)
            a.write(registry,data['previous'] if data.get('previous') else event)
            return selected_release(policy,_locked=True)
    elif data['status']!='confirmed':raise ValueError('未知采用状态')
    if not verify_sealed(data['canary_seal']):raise ValueError('试用回执变化')
    return release/'scripts/dev_cycle.py'


def enqueue(folder):
    a=api();folder=Path(folder);out=folder/'improvement-jobs';out.mkdir(exist_ok=True)
    snapshots=sorted(folder.glob('improvement-candidates-attempt-*.json'))
    reports=[a.read(p)for p in snapshots]if snapshots else[a.read(folder/'improvement-candidates.json')]
    paths=[];canonical={}
    for existing in sorted(out.glob('*.json')):
        job=a.read(existing);proposal=job.get('proposal',{})
        refs=proposal.get('evidence_index',[])
        if (job.get('status')not in {'deduplicated','needs_evidence','needs_task_owner'} and
                proposal.get('kind')=='workflow' and proposal.get('owner')=='maintenance' and
                proposal.get('evidence_valid') and proposal.get('observation_ids') and
                refs and verify_sealed({ref['path']:ref['sha256']for ref in refs})):
            canonical.setdefault((proposal['kind'],proposal['owner'],tuple(sorted(set(proposal['observation_ids'])))),existing)
    for item in [i for report in reports for i in report['items']]:
        safe_name(item['id'])
        path=out/(item['id']+'.json')
        source_valid=bool(item.get('evidence_index')) and all(
                Path(ref['path']).is_file() and folder.resolve() in Path(ref['path']).resolve().parents and
                hashlib.sha256(Path(ref['path']).read_bytes()).hexdigest()==ref['sha256']for ref in item.get('evidence_index',[]))
        valid=item['kind']=='workflow' and item['owner']=='maintenance' and item['evidence_valid'] and source_valid
        key=(item['kind'],item['owner'],tuple(sorted(set(item.get('observation_ids',[])))))
        if valid and key[2] and key in canonical and canonical[key]!=path:
            master=canonical[key];job=a.read(master);aliases=job.setdefault('aliases',[])
            if item['id']not in [alias['id']for alias in aliases]:aliases.append(item);a.write(master,job)
            if not path.exists():a.write(path,dict(id=item['id'],status='deduplicated',canonical=str(master),proposal=item))
            paths.append(path);continue
        if valid and key[2]:canonical[key]=path
        if not path.exists():
            a.write(path,dict(format=1,id=item['id'],task=str(folder.resolve()),proposal=item,
                status='queued'if valid else'needs_task_owner'if item['kind']=='task'else'needs_evidence',
                attempts=[],cli_launches=0,developer_session=None,created=time.time()))
        paths.append(path)
    return paths


def check_policy(policy):
    a=api()
    for key in ('root','source_bundle','environment'):
        if not Path(policy[key]).is_absolute():raise ValueError('维护策略路径须绝对')
    if not 1<=policy['max_jobs']<=3 or not 1<=policy['max_revisions']<=2 or not 2<=policy['max_cli']<=8:
        raise ValueError('维护额度超出有界范围')
    if not policy['allowed_paths']:raise ValueError('未授权维护文件')
    for ref in policy.get('historical_evidence',[]):
        if not Path(ref['path']).is_absolute() or not verify_sealed({ref['path']:ref['sha256']}):
            raise ValueError('明确提供的历史维护证据已变化')
    for name in policy['allowed_paths']:safe_name(name)
    for name in ('regression','comparison','canary'):
        spec=policy[name]
        a.validate_plan(spec['plan'])
        if not spec['required_checks']:raise ValueError('维护验收必须固定检查名称')
    source=Path(policy['source_bundle']).resolve()
    if not policy['source_files'] or not Path(policy['environment']).is_dir():raise ValueError('维护基线包或任务环境缺失')
    if files(source)!=policy['source_files']:raise ValueError('维护基线包发生变化')
    root=Path(policy['root']).resolve()
    if root==source or source in root.parents or root in source.parents:raise ValueError('维护状态和基线包必须分离')


def execute_check(spec,source,record,environment):
    a=api()
    report=a.execute_acceptance(spec['plan'],candidate=source,record=record,environment=environment,
        is_cancelled=lambda:(record.parents[1]/'cancel-request.json').exists(),stop_process=a.stop_tree)
    found={c['name']for c in report['checks']if c['passed'] and c.get('observed')is True}
    if report['status']!='pass' or any(c.get('observed')is not True or not c['passed'] for c in report['checks']) or not set(spec['required_checks'])<=found:
        raise ValueError('维护验证未通过或缺固定检查：'+str(record))
    return report


def run_job(path,policy,executor=None):
    a=api();path=Path(path);job=a.read(path)
    if job['status']!='queued':return job
    if not verify_sealed({ref['path']:ref['sha256']for proposal in [job['proposal'],*job.get('aliases',[])]for ref in proposal.get('evidence_index',[])}):
        job.update(status='needs_evidence',error='原始提案证据变化');a.write(path,job);return job
    check_policy(policy);root=Path(policy['root']).resolve();root.mkdir(parents=True,exist_ok=True)
    with a.locked(root):
        ledger_path=root/'ledger.json'
        ledger=a.read(ledger_path)if ledger_path.exists()else dict(jobs=[],policy_sha256=a.digest(policy))
        if ledger['policy_sha256']!=a.digest(policy):raise ValueError('不能通过变更策略重置维护额度')
        key=str(path.resolve())
        if key in ledger['jobs']:raise ValueError('中断维护须显式核对；不自动重放模型写入')
        if len(ledger['jobs'])>=policy['max_jobs']:
            job['status']='exhausted';a.write(path,job);return job
        ledger['jobs'].append(key);a.write(ledger_path,ledger)
        target=root/job['id'];target.mkdir();work=target/'work'
        active=selected_release(policy,_locked=True)
        baseline_source=active.parent.parent if active else Path(policy['source_bundle'])
        shutil.copytree(baseline_source,work)
        (target/'briefs').mkdir()
        env_path=target/'python-env'
        if os.name=='nt':
            subprocess.run(['powershell.exe','-NoProfile','-Command',
                "New-Item -ItemType Junction -Path '"+str(env_path).replace("'","''")+"' -Target '"+str(Path(policy['environment']).resolve()).replace("'","''")+"' | Out-Null"],check=True)
        else:env_path.symlink_to(Path(policy['environment']).resolve(),target_is_directory=True)
        a.git(work,'init','--quiet');a.git(work,'add','.')
        a.git(work,'-c','user.name=Workflow','-c','user.email=workflow@localhost','commit','--quiet','-m','maintenance baseline')
        baseline=files(work);job.update(status='running',directory=str(target));a.write(path,job)
        actor=executor or a.Codex(openai_https=policy.get('openai_https',False),dependency_paths=policy.get('dependency_paths',[]))

        def call(stage,prompt,cwd):
            if job['cli_launches']>=policy['max_cli']:raise ValueError('维护CLI额度耗尽')
            if (target/'cancel-request.json').exists():raise ValueError('维护已取消')
            job['cli_launches']+=1;record=target/f"attempt-{job['cli_launches']:02d}-{stage}";record.mkdir()
            attempt=dict(stage=stage,directory=str(record),status='running',started=time.time(),
                resume_session=job['developer_session']if stage=='develop'else None)
            job['attempts'].append(attempt);a.write(path,job)
            (record/'prompt.txt').write_text(prompt,'utf-8')
            try:
                value=actor(stage=stage,prompt=prompt,cwd=cwd,record=record,session=attempt['resume_session'],task_folder=target,
                    check_seconds=30,silence_seconds=180,started=lambda pid,created:a.write(record/'process.json',dict(pid=pid,created=created)))
                a.validate(stage,value);a.write(record/'result.json',value);return value
            finally:
                sid,usage=a.event_info(record/'events.jsonl');attempt.update(session=sid,usage=usage,ended=time.time(),status='completed'if(record/'result.json').exists()else'failed')
                if sid and stage=='develop':job['developer_session']=sid
                a.write(path,job)

        try:
            feedback=None
            for revision in range(1,policy['max_revisions']+1):
                job['revision']=revision;a.write(path,job)
                prompt=('用户授权维护未来流程隔离副本。只修改allowed_paths，允许新增指定回归；不得改其它文件、全局配置、提交推送、运行嵌套开发闭环或接触业务外部写入。'
                    '依据原始观察修复流程机制，不仅补当前任务材料，不降低契约和权限。旧任务和运行中规则冻结。先复现反例，定向检查，证据写DEV_CYCLE_EVIDENCE_DIR。'
                    '宿主会执行冻结的红绿回归及真实比较，随后独立审查，全部通过才能采用。按develop schema报告。\n'+
                    json.dumps(dict(proposal=job['proposal'],related_proposals=job.get('aliases',[]),allowed_paths=policy['allowed_paths'],baseline=baseline,feedback=feedback),ensure_ascii=False))
                response=call('develop',prompt,work)
                developer_record=Path(job['attempts'][-1]['directory'])
                if response['status']!='ready':raise ValueError('维护开发报告blocked')
                candidate=files(work)
                changed={n for n in set(baseline)|set(candidate)if baseline.get(n)!=candidate.get(n)}
                if not changed or not changed<=set(policy['allowed_paths']):raise ValueError('维护越界或没有实际修改：'+str(sorted(changed)))
                check_policy(policy)
                snapshot=target/f'review-{revision}';shutil.copytree(work,snapshot,ignore=shutil.ignore_patterns('.git','__pycache__'))
                validation=target/f'validation-{revision}';validation.mkdir()
                environment=validation_environment(policy,snapshot)
                try:
                    receipts={name:execute_check(policy[name],snapshot,validation/name,environment)for name in ('regression','comparison')}
                except ValueError as exc:
                    feedback=dict(error=str(exc),validation=str(validation));job['validation_failure']=feedback;a.write(path,job)
                    continue
                if files(snapshot)!=candidate or files(work)!=candidate:raise ValueError('验证修改了维护候选')
                validation_seal=sealed(validation)
                manifest=review_evidence_manifest(job,policy,snapshot,validation,developer_record)
                manifest_path=target/f'review-evidence-{revision}.json';a.write(manifest_path,manifest)
                manifest_hash=hashlib.sha256(manifest_path.read_bytes()).hexdigest()
                review=call('maintenance_review',a.ROLES['maintenance_review']+
                    '\n最终evidence只能引用allowed_evidence中预封存的非空原始文件，逐字使用清单path。可读取这些材料，但不得改写。'
                    '清单外历史任务、同目录其他文件或后加文件不能作为正式证据；不得为引用任意路径临时复制或补信任。\n'+
                    json.dumps(dict(proposal=job['proposal'],candidate=str(snapshot),changed=sorted(changed),validation=str(validation),
                        receipts=receipts,evidence_manifest=str(manifest_path),
                        allowed_evidence=[dict(path=entry['path'],kind=entry['kind']) for entry in manifest['files']if entry['size']>0]),ensure_ascii=False),target/'briefs')
                if hashlib.sha256(manifest_path.read_bytes()).hexdigest()!=manifest_hash:raise ValueError('维护审查改写了可引用清单')
                check_review_evidence(review,manifest)
                if files(snapshot)!=candidate or files(work)!=candidate or not verify_sealed(validation_seal):raise ValueError('独立审查改写了维护候选或验证证据')
                if review['decision']!='pass' or review['defects']:
                    feedback=review
                    if review['decision']=='blocked':break
                    continue
                check_policy(policy)
                if not (snapshot/'scripts/dev_cycle.py').is_file():raise ValueError('维护候选缺少控制器入口')
                release_id=a.digest(candidate);release=root/'releases'/release_id;release.parent.mkdir(exist_ok=True)
                if not release.exists():shutil.copytree(snapshot,release)
                if files(release)!=candidate:raise ValueError('采用包已存在但内容不同')
                evidence_seal=dict(manifest['source_seal'],**sealed(target/f"attempt-{job['cli_launches']:02d}-maintenance_review"))
                evidence_seal[str(manifest_path)]=manifest_hash
                evidence_seal.update({ref['path']:ref['sha256']for proposal in [job['proposal'],*job.get('aliases',[])]for ref in proposal['evidence_index']})
                if not verify_sealed(evidence_seal):raise ValueError('原始提案或维护证据变化')
                adoption=dict(id=release_id,files=candidate,job=str(path.resolve()),revision=revision,evidence_seal=evidence_seal,
                    validation=str(validation),review=review,adopted_at=time.time(),policy_sha256=a.digest(policy))
                adoption_path=root/'adoptions'/(release_id+'.json');adoption_path.parent.mkdir(exist_ok=True)
                (root/'release-events').mkdir(exist_ok=True)
                if adoption_path.exists():raise ValueError('相同采用包已登记，拒绝覆盖采用历史')
                a.write(adoption_path,adoption)
                registry=root/'active-release.json';previous=a.read(registry)if registry.exists()else None
                a.write(registry,dict(id=release_id,status='trial',previous=previous,adoption_path=str(adoption_path),
                                     adoption_sha256=hashlib.sha256(adoption_path.read_bytes()).hexdigest()))
                job.update(status='adopted',release=adoption);break
            else:job.update(status='exhausted')
            if job['status']=='running':job['status']='blocked'
        except Exception as exc:
            job.update(status='blocked',error=f'{type(exc).__name__}: {exc}')
        finally:
            if files(Path(policy['source_bundle']))!=policy['source_files']:
                job.update(status='blocked',error='原始维护基线发生变化')
            job['ended']=time.time();a.write(path,job)
            a.write(target/'metrics.json',a.measure(dict(status=job['status'],version=a.VERSION,attempts=job['attempts'],
                launches=job['cli_launches'],rounds=[],scope_revisions=0,supplements_used=0)))
    return job


def dispatch(folder,policy=None,executor=None):
    a=api();paths=enqueue(folder);outcomes=[]
    for path in paths:
        job=a.read(path)
        followup=Path(folder)/'reflection-followup.json'
        if job['status']=='needs_task_owner' and followup.exists():
            receipt=a.read(followup)
            if receipt['action']['id']==job['id']:
                job.update(status='task_followup_completed'if a.read(Path(folder)/'state.json')['status']=='accepted'else'task_followup_failed',
                    execution=str(followup));a.write(path,job)
        if job['status']=='queued' and policy:
            try:job=run_job(path,policy,executor)
            except Exception as exc:
                job=a.read(path);job.update(status='blocked',error=f'{type(exc).__name__}: {exc}');a.write(path,job)
        outcomes.append(dict(id=job['id'],status=job['status'],path=str(path)))
    a.write(Path(folder)/'improvement-dispatch.json',dict(jobs=outcomes,policy_enabled=bool(policy)))
    return outcomes
