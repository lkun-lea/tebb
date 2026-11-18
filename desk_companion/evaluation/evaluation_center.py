"""Authenticated local evaluation management over the existing product harness."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid

from desk_companion.infrastructure.paths import source_root
from desk_companion.tasks.task_process import ProcessTree
from desk_companion.evaluation.golden_store import GoldenStore
from desk_companion.evaluation.artifacts import attempt_profile
from desk_companion.evaluation.batch_metrics import metrics,compare
from desk_companion.observability.tool_monitor import fingerprint


class EvaluationCenter:
    def __init__(self,store=None):
        self.store=store or GoldenStore();self.directory=self.store.path.parent/'evaluation-batches'
        self.lock=threading.Lock();self.jobs={};self.stopped=False
        # ProcessTree owns children. A host restart cannot invent completion from
        # a stale PID, nor automatically resume potentially side-effecting work.
        for batch in self.store.batches():
            if batch['state']in{'queued','running','cancelling'}:
                rows=self._stop_unsettled(self._results(batch['id']),'HostRestarted')
                self.store.update(batch['id'],state='interrupted',results=rows,metrics=metrics(rows,batch['planned']),error_kind='HostRestarted')
                self._clean_credentials(batch['id'])

    def operate(self,operation,payload=None):
        payload={}if payload is None else payload
        if not isinstance(payload,dict):raise ValueError('评测参数无效。')
        if operation=='cases':return dict(ok=True,items=self.store.cases())
        if operation=='coverage':
            from desk_companion.evaluation.coverage import coverage
            return coverage(self.store.cases(),self.store.batches(100))
        if operation=='diagnose':
            from desk_companion.observability.timeout_diagnostics import report
            from desk_companion.observability.performance import task_snapshot,task_timing
            batch=self.get(payload['ident'])['batch'];value=report(batch);value['tasks']=[]
            for index,plan in enumerate(batch['planned']):
                row=next((r for r in batch['results']if r['case_id']==plan['case_id']and r['sample']==plan['sample']),{})
                profile=attempt_profile(self.directory/batch['id']/('attempt-'+str(index)))
                original=task_snapshot(row.get('task_id'),profile=profile)
                if original:value['tasks'].append(dict(case_id=plan['case_id'],task=original['id'],state=original['state'],
                    timing=task_timing(original),budget_stop=(row.get('task_budget')or{}).get('stop_reason'),
                    evaluation_deadline_exceeded=row.get('deadline_exceeded',False),source='original_task_owner'))
            return value
        if operation=='gate':
            from desk_companion.evaluation.quality_gate import gate
            return gate(self.get(payload['baseline'])['batch'],self.get(payload['candidate'])['batch'],
                self.get(payload['holdout'])['batch']if payload.get('holdout')else None)
        if operation=='runtime':
            from desk_companion.pi_runtime.bridge import PiBridge
            package=Path(__file__).with_name('promptfoo')/'node_modules/promptfoo/package.json'
            return dict(ok=True,source_harness=(source_root()/'scripts/eval_agent.py').is_file(),node=bool(PiBridge().node),
                promptfoo_installed=package.is_file(),required=dict(node='24.22.3',promptfoo='0.125.1'),
                install='npm ci --ignore-scripts --no-audit --no-fund (desk_companion/evaluation/promptfoo)')
        if operation=='save_case':return dict(ok=True,case=self.store.save_case(**payload))
        if operation=='draft_failure':
            from desk_companion.observability.tool_monitor import ToolMonitor
            from desk_companion.observability.usage_store import UsageStore
            try:event=ToolMonitor(self.store.profile/'memory/tool-observations.sqlite3').get_event(payload['event_id'])
            except ValueError:event=UsageStore(self.store.profile/'memory/usage-observations.sqlite3').get(payload['event_id'])
            if not event or event.get('state')not in{'failed','timed_out','cancelled','unknown','rejected'}:raise ValueError('该记录没有已记录的失败或未知结果。')
            subject=event.get('tool')or event.get('model')or'该任务'
            return dict(ok=True,draft=dict(id='failure-'+fingerprint(event['id'])[:16],
                prompt='在隔离环境验证 '+subject+' 遇到 '+(event.get('error_kind')or event['state'])+' 时的预期行为。补充必要的合成输入；不要包含密钥、签名链接或真实外部写入。',
                expected=None,source_failure=event['id']),evidence={k:event.get(k)for k in('tool','model','definition_version','root','task','attempt_id','error_kind','error_message','prompt_version','tools_version')},ready=False)
        if operation=='start':return self.start(**payload)
        if operation=='get':return self.get(**payload)
        if operation=='list':return self.list_batches(**payload)
        if operation=='cancel':return self.cancel(**payload)
        if operation=='trace':return self.trace(**payload)
        if operation=='debug_call':return self.debug_call(**payload)
        if operation=='failures':
            batch=self.get(payload['ident'])['batch']
            return dict(ok=True,batch=batch['id'],items=[r for r in batch['results']if r.get('outcome')!='success'],manifest_hash=batch['manifest_hash'])
        if operation=='compare':return compare(self.get(payload['baseline'])['batch'],self.get(payload['candidate'])['batch'])
        raise ValueError('评测操作无效。')

    def start(self,request_id,case_versions,*,candidate='current',mode='fixture',samples=1,timeout=120,tool_loading='demand',live_authorized=False,model_id='',judge_model_id='',review_effort='provider_default'):
        if not isinstance(request_id,str)or not re.fullmatch(r'[A-Za-z0-9_-]{8,128}',request_id):raise ValueError('评测请求编号无效。')
        if not isinstance(candidate,str)or not 1<=len(candidate)<=200 or type(samples)is not int or not 1<=samples<=5 or type(timeout)is not int or not 20<=timeout<=300:raise ValueError('评测版本或预算无效。')
        if mode not in{'fixture','live'}or tool_loading not in{'demand','eager'}:raise ValueError('评测模式无效。')
        if not isinstance(review_effort,str)or review_effort not in {'auto','provider_default','low'}:raise ValueError('审阅推理策略无效。')
        if mode=='live'and live_authorized is not True:raise ValueError('真实模型评测须显式授权有限批次。')
        if not isinstance(model_id,str)or len(model_id)>200 or mode=='fixture'and model_id:raise ValueError('模型选择与评测模式不一致。')
        if not isinstance(case_versions,list)or not 1<=len(case_versions)<=20 or any(not isinstance(v,str)for v in case_versions)or len(set(case_versions))!=len(case_versions):raise ValueError('请选择1到20个固定版本用例。')
        catalog={c['version']:c for c in self.store.cases()}
        if any(v not in catalog for v in case_versions):raise ValueError('用例版本不存在。')
        cases=[catalog[v]for v in case_versions]
        if mode=='live'and any(c['spec'].get('executor')=='timeout_probe'for c in cases):raise ValueError('故障注入用例仅允许隔离模拟模式。')
        if not isinstance(judge_model_id,str)or len(judge_model_id)>200 or mode=='fixture'and judge_model_id:raise ValueError('审阅模型选择与评测模式不一致。')
        if len({c['id']for c in cases})!=len(cases):raise ValueError('同批不能混用同一用例的不同标准。')
        if len({c['split']for c in cases})!=1:raise ValueError('开发集、回归集与保留集须分批运行。')
        planned=[dict(case_id=c['id'],case_version=c['version'],sample=i+1,weight=c['weight'],goals=c.get('goals')or c['spec'].get('rubric',[]))for c in cases for i in range(samples)]
        from desk_companion.infrastructure.code_identity import code_version
        code=code_version()
        from desk_companion.evaluation.frozen_config import model_configuration
        model_config=model_configuration(mode,model_id)
        judge_config=model_configuration(mode,judge_model_id)if any(c['criteria']=='reference_rubric'for c in cases)else None
        from desk_companion.tasks.task_budgets import policy
        judge_limits=policy('simple')if judge_config or any(c['criteria']=='reference_judge_calibration'for c in cases)else None
        from desk_companion.evaluation.grading_contract import grading_contract
        judge_contract=grading_contract(cases,judge_config,review_effort=review_effort)
        case_hash=fingerprint(dict(cases=cases,planned=planned,mode=mode,timeout=timeout,judge_contract=judge_contract,judge_limits=judge_limits))
        manifest=dict(cases=cases,planned=planned,case_manifest_hash=case_hash,candidate=candidate,mode=mode,timeout=timeout,
                      tool_loading=tool_loading,review_effort=review_effort,code_version=code,model_config=model_config,judge_config=judge_config,judge_limits=judge_limits,judge_contract=judge_contract,framework=dict(name='promptfoo',version='0.125.1'),judge='product_contract_'+str(cases[0]['contract_version']))
        manifest_hash=fingerprint(manifest)
        value=dict(**manifest,id=uuid.uuid4().hex,created=time.time(),state='queued',manifest_hash=manifest_hash,results=[])
        with self.lock:
            if self.stopped:raise ValueError('评测服务正在退出，未创建新任务。')
            if self.jobs and self.store.request_batch(request_id)is None:raise ValueError('已有评测批次在运行，请完成或停止后再创建。')
            value,created=self.store.create_batch(value,request_id)
            if created:
                cancel=threading.Event();self.jobs[value['id']]=dict(cancel=cancel)
        if created:
            try:
                folder=self.directory/value['id'];folder.mkdir(parents=True,exist_ok=False)
                (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,allow_nan=False),'utf-8')
                threading.Thread(target=self._run,args=(value['id'],folder,cancel),daemon=True).start()
            except Exception:
                with self.lock:self.jobs.pop(value['id'],None)
                self.store.update(value['id'],state='failed',results=[],metrics=metrics([],value['planned']),error_kind='BatchPreparationFailed');raise
        # Start/get/cancel share one response shape. Even queued batches have
        # planned denominators; clients must not crash before the first poll.
        return dict(ok=True,batch=self.get(value['id'])['batch'],reused=not created)

    def _run(self,ident,folder,cancel):
        tree=None
        try:
            if cancel.is_set():
                self.store.update(ident,state='cancelled',results=[],metrics=metrics([],self.store.batch(ident)['planned']));return
            from desk_companion.pi_runtime.bridge import PiBridge
            node=PiBridge().node
            if not node:raise RuntimeError('PinnedNodeMissing')
            env=os.environ.copy();env.update(PROMPTFOO_PYTHON=sys.executable,PROMPTFOO_DISABLE_TELEMETRY='1',PROMPTFOO_DISABLE_UPDATE='1',PROMPTFOO_DISABLE_SHARING='1',PROMPTFOO_CONFIG_DIR=str(folder/'framework-profile'))
            for key in ('DESK_TERMINAL_TOKEN','DESK_TERMINAL_PORT'):env.pop(key,None)
            self.store.update(ident,state='running')
            with (folder/'framework.log').open('w',encoding='utf-8')as log:
                process=subprocess.Popen([node,str(Path(__file__).with_name('promptfoo')/'run.mjs'),str(folder)],cwd=source_root(),env=env,
                    stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt'else 0)
                tree=ProcessTree(process)
                with self.lock:self.jobs[ident]['tree']=tree
                started=time.monotonic();manifest=self.store.batch(ident)
                maximum=len(manifest['planned'])*(manifest['timeout']+120)+60
                cancel_started=None
                while process.poll() is None:
                    if cancel.is_set():
                        if cancel_started is None:
                            (folder/'cancel.requested').touch();cancel_started=time.monotonic()
                        if time.monotonic()-cancel_started>12:tree.close();break
                    elif time.monotonic()-started>maximum:tree.close();break
                    time.sleep(.2)
                code=process.wait(timeout=10)
            results=self._results(ident)
            self._clean_credentials(ident)
            state='cancelled'if cancel.is_set()else'completed'if code==0 and len(results)==len(manifest['planned'])and all(not r.get('progress')for r in results)else'failed'
            if state=='cancelled':results=self._stop_unsettled(results,'BatchCancelledBeforeSettlement')
            if state=='failed':
                results=[{**row,'product_outcome':row['outcome'],'outcome':'infrastructure_failure','error_kind':'FrameworkIncomplete'}for row in results]
            self.store.update(ident,state=state,results=results,metrics=metrics(results,manifest['planned']),framework_exit_code=code,error_kind=None if state=='completed'else'Cancelled'if state=='cancelled'else'FrameworkIncomplete')
        except Exception as exc:
            rows=self._stop_unsettled(self._results(ident),type(exc).__name__)
            self.store.update(ident,state='cancelled'if cancel.is_set()else'failed',results=rows,metrics=metrics(rows,self.store.batch(ident)['planned']),error_kind=type(exc).__name__)
        finally:
            try:
                if tree:tree.close()
            finally:
                try:self._clean_credentials(ident)
                except OSError:pass  # The failed cleanup is already a failed batch, never a pass.
                finally:
                    with self.lock:self.jobs.pop(ident,None)

    def _clean_credentials(self,ident):
        batch=self.store.batch(ident)
        for index in range(len(batch['planned'])):
            for name in ('models.json','model-network.json'):
                path=attempt_profile(self.directory/ident/('attempt-'+str(index)))/name
                path.unlink(missing_ok=True)

    @staticmethod
    def _stop_unsettled(rows,reason):
        return [{**r,'outcome':'incomplete'if r.get('task_id')else'not_started','progress':False,'error_kind':reason}if r.get('progress')else r for r in rows]

    def _results(self,ident):
        rows=[];batch=self.store.batch(ident);folder=self.directory/ident
        for i,plan in enumerate(batch['planned']):
            path=folder/('result-'+str(i)+'.json')
            if path.is_file():
                try:rows.append(json.loads(path.read_text('utf-8')))
                except (OSError,ValueError):pass  # Atomic writer may be settling; never synthesize a pass.
            else:
                report=folder/('attempt-'+str(i))/'report.json'
                try:
                    partial=json.loads(report.read_text('utf-8'))
                    if partial.get('cases'):
                        value=partial['cases'][0]
                        rows.append({**value,'case_id':plan['case_id'],'sample':plan['sample'],'product_outcome':value.get('outcome'),
                                     'outcome':'running'if value.get('task_id')else'not_started','progress':True})
                except (OSError,ValueError):pass
        return rows

    def trace(self,ident,case_id,sample=1):
        batch=self.get(ident)['batch']
        index=next((i for i,p in enumerate(batch['planned'])if p['case_id']==case_id and p['sample']==sample),None)
        if index is None:raise ValueError('用例不属于该批次。')
        row=next((r for r in batch['results']if r['case_id']==case_id and r['sample']==sample),{})
        task=row.get('task_id')
        if not task:raise ValueError('本用例尚未提交任务。')
        profile=attempt_profile(self.directory/ident/('attempt-'+str(index)))
        from desk_companion.observability.execution_center import ExecutionCenter
        from desk_companion.observability.execution_sources import owner_nodes,task_checks
        from desk_companion.observability.usage_sources import task_metadata
        from desk_companion.observability.usage_store import UsageStore
        from desk_companion.observability.tool_monitor import ToolMonitor
        paths=[profile/'memory/collaboration/workspace.sqlite3',*sorted((profile/'workspaces').glob('*.sqlite3'))]
        paths=[p for p in paths if p.is_file()and profile.resolve()in p.resolve().parents]
        service=ExecutionCenter(usage=UsageStore(profile/'memory/usage-observations.sqlite3'),tools=ToolMonitor(profile/'memory/tool-observations.sqlite3'),
            sources=lambda:task_metadata(profile,paths),owner_source=lambda root:owner_nodes(root,profile,paths),checks_source=lambda tasks:task_checks(tasks,profile))
        graph=service.locate(task)
        for judge_task in row.get('judge_task_ids',[]):
            judge_graph=service.locate(judge_task)
            graph['nodes'].extend(judge_graph['nodes']);graph['edges'].extend(judge_graph['edges'])
            graph['edges'].append(dict(id=graph['root']+'>'+judge_graph['root'],source=graph['root'],target=judge_graph['root'],relation='independent_evaluation'))
            graph['timeline'].extend(judge_graph['timeline'])
        if batch['state']in{'cancelled','interrupted','failed'}:
            graph['nodes']=[{**n,'observed_state':n['state'],'state':'unknown','recovery':'owner_receipt_missing_after_batch_stop'}if n.get('state')in{'queued','running','cancelling'}else n for n in graph['nodes']]
        return graph

    def debug_call(self,ident,case_id,sample,call_id):
        batch=self.get(ident)['batch']
        index=next((i for i,p in enumerate(batch['planned'])if p['case_id']==case_id and p['sample']==sample),None)
        row=next((r for r in batch['results']if r['case_id']==case_id and r['sample']==sample),{})
        if index is None or call_id not in row.get('call_ids',[]):raise ValueError('调用不属于该评测用例。')
        from desk_companion.observability.redaction import debug_detail
        profile=attempt_profile(self.directory/ident/('attempt-'+str(index)))
        return debug_detail(call_id,profile=profile)

    def get(self,ident):
        if not isinstance(ident,str)or not re.fullmatch(r'[a-f0-9]{32}',ident):raise ValueError('评测批次编号无效。')
        batch=self.store.batch(ident)
        results=self._results(ident)if batch['state']in{'queued','running','cancelling'}else batch.get('results',[])
        if results:batch['results']=results
        if batch['state']in{'queued','running','cancelling'}or 'metrics'not in batch:
            batch['metrics']=metrics(batch['results'],batch['planned'])
            if batch['state']not in{'queued','running','cancelling'}:batch['metrics_compatibility']='historical_summary_missing_recomputed_without_regrading'
        batch['valid_for_comparison']=batch['state']=='completed'and bool(batch.get('judge_contract'))
        return dict(ok=True,batch=batch)

    def list_batches(self,offset=0,limit=50):
        if type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=200:raise ValueError('评测分页参数无效。')
        page=self.store.batches(limit+1,offset);items=[]
        for item in page[:limit]:
            results=self._results(item['id'])if item['state']in{'queued','running','cancelling'}else item.get('results',[])
            summary=item.get('metrics')if item['state']not in{'queued','running','cancelling'}else None
            items.append({**{k:item.get(k)for k in('id','created','state','candidate','mode','manifest_hash','code_version','model_config')},'metrics':summary or metrics(results,item['planned'])})
        return dict(ok=True,items=items,next_offset=offset+limit if len(page)>limit else None)

    def cancel(self,ident):
        self.store.batch(ident)
        with self.lock:
            job=self.jobs.get(ident)
            if job:job['cancel'].set();self.store.update(ident,state='cancelling')
        return self.get(ident)

    def shutdown(self):
        with self.lock:
            self.stopped=True
            for job in self.jobs.values():job['cancel'].set()
        deadline=time.monotonic()+15
        while time.monotonic()<deadline:
            with self.lock:
                if not self.jobs:return dict(complete=True,pending_batch_ids=[])
            time.sleep(.1)
        with self.lock:return dict(complete=not self.jobs,pending_batch_ids=list(self.jobs))
