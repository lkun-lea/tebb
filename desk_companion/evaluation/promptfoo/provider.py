"""Fixed Promptfoo Python provider using the existing isolated product eval entry.

No case content is evaluated as Python, JavaScript or shell. The provider's only
command and assertion code live in the repository, not the editable golden set.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
if str(ROOT)not in sys.path:sys.path.insert(0,str(ROOT))


def call_api(prompt, options, context):
    config=options['config'];index=int(context['vars']['attempt'])
    batch=Path(config['batch_dir']).resolve()
    manifest=json.loads((batch/'manifest.json').read_text('utf-8'))
    from desk_companion.infrastructure.code_identity import code_version
    from desk_companion.evaluation.frozen_config import model_configuration
    if manifest['code_version']!=code_version():raise RuntimeError('FrozenCodeChanged')
    if manifest['model_config']!=model_configuration(manifest['mode'],manifest['model_config']['id']):raise RuntimeError('FrozenModelConfigurationChanged')
    judge_config=manifest.get('judge_config')
    if judge_config and judge_config!=model_configuration(manifest['mode'],judge_config['id']):raise RuntimeError('FrozenJudgeConfigurationChanged')
    planned=manifest['planned'][index];case=next(c for c in manifest['cases']if c['id']==planned['case_id'])
    if (batch/'cancel.requested').exists():
        row=dict(case_id=case['id'],sample=planned['sample'],outcome='not_started',error_kind='BatchCancelledBeforeSubmission')
        (batch/('result-'+str(index)+'.json')).write_text(json.dumps(row),'utf-8')
        return dict(output=json.dumps(row))
    snapshot=batch/('case-'+str(index)+'.json');snapshot.write_text(json.dumps([case],ensure_ascii=False),'utf-8')
    output=batch/('attempt-'+str(index))
    command=[sys.executable,str(ROOT/'scripts/eval_agent.py'),'--output',str(output),'--case-snapshot',str(snapshot),
             '--samples','1','--limit','1','--timeout',str(manifest['timeout']),
             '--tool-loading',manifest['tool_loading']]
    if manifest['mode']=='live':command.extend(['--live','--model-id',manifest['model_config']['id'],'--reuse-model-policy'])
    if manifest['mode']=='live'and judge_config:command.extend(['--judge-model-id',judge_config['id']])
    # stdout/stderr stay private; public errors are categories, not echoed keys.
    try:
        with (batch/('attempt-'+str(index)+'.log')).open('w',encoding='utf-8')as log:
            result=subprocess.run(command,cwd=ROOT,stdout=log,stderr=log,env={**os.environ,'TEBB_EVAL_CANCEL_FILE':str(batch/'cancel.requested')},timeout=manifest['timeout']+120)
    finally:
        # Credentials are always temporary, including parent harness failure.
        for name in ('models.json','model-network.json'):
            (output/'private-profile'/name).unlink(missing_ok=True)
    report_path=output/'report.json'
    if not report_path.is_file():
        row=dict(case_id=case['id'],sample=planned['sample'],outcome='infrastructure_failure',error_kind='ProductEvalUnavailable')
    else:
        report=json.loads(report_path.read_text('utf-8'));row=report['cases'][0] if report['cases'] else dict(outcome='not_started')
        row.update(case_id=case['id'],sample=planned['sample'],case_version=case['version'],contract_version=report['contract_version'],
                   report='attempt-'+str(index)+'/report.json',product_exit_code=result.returncode,mode=report['mode'])
        if result.returncode!=0 and row['outcome']=='success':
            row.update(product_outcome='success',outcome='infrastructure_failure',error_kind='ProductCleanupOrHarnessFailed')
    if manifest['code_version']!=code_version()or manifest['model_config']!=model_configuration(manifest['mode'],manifest['model_config']['id'])or(judge_config and judge_config!=model_configuration(manifest['mode'],judge_config['id'])):
        row.update(original_outcome=row['outcome'],outcome='infrastructure_failure',error_kind='FrozenCodeOrConfigurationChanged')
    from desk_companion.observability.usage_store import UsageStore
    observations=[r for r in UsageStore(output/'private-profile/memory/usage-observations.sqlite3').rows()if r['kind']=='model']
    row['model_observations']=observations
    observed_calls={ident for r in observations for ident in r.get('debug_calls',([r['debug_call']]if r.get('debug_call')else[]))}
    row['model_observations_complete']=bool(observations)and set(row.get('call_ids',[]))<=observed_calls
    goals=case.get('goals')or[]
    if goals:
        from desk_companion.evaluation.agent_evals import json_answer,same_json
        try:answer=json_answer(row.get('answer',''))
        except (ValueError,TypeError):answer=None
        evidence=[]
        for goal in goals:
            actual=answer;exists=True
            for key in goal['path']:
                if not isinstance(actual,dict)or key not in actual:exists=False;break
                actual=actual[key]
            passed=exists and same_json(actual,goal['expected'])
            evidence.append(dict(id=goal['id'],weight=goal['weight'],passed=passed,task_id=row.get('task_id'),evidence='answer_json_path'if exists else'missing'))
        row['goal_checks']=evidence
        if row['outcome']=='success'and any(not c['passed']for c in evidence):
            row.update(product_outcome='success',outcome='false_success',error_kind='RequiredGoalCheckFailed')
    # Persist each settled attempt even if the framework is cancelled later.
    target=batch/('result-'+str(index)+'.json');temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(row,ensure_ascii=False,allow_nan=False),'utf-8');temporary.replace(target)
    return dict(output=json.dumps(dict(outcome=row['outcome'],case_id=case['id'],sample=planned['sample']),ensure_ascii=False))


def get_assert(output, context):
    value=json.loads(output)
    return {'pass':value.get('outcome')=='success','score':1 if value.get('outcome')=='success'else 0,
            'reason':'existing product receipt judge: '+value.get('outcome','unknown')}
