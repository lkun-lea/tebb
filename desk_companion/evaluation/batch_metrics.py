"""Versioned denominators over frozen attempts; never select only successes."""
from collections import Counter,defaultdict
import math

VERSION=1
OUTCOMES={'success','false_success','failed','needs_input','skip','incomplete','timed_out','cancelled','not_started','infrastructure_failure','running'}


def metrics(rows, planned):
    plan_keys={(p['case_id'],p['sample'])for p in planned};row_keys=[(r['case_id'],r['sample'])for r in rows]
    if len(plan_keys)!=len(planned)or len(set(row_keys))!=len(rows)or set(row_keys)-plan_keys:raise ValueError('评测结果重复或不属于固定计划。')
    if any(r.get('outcome')not in OUTCOMES for r in rows):raise ValueError('评测结果状态未知，未计为成功。')
    states=Counter(r.get('outcome','not_started') for r in rows)
    states['not_started']+=len(planned)-len(rows)
    # Cancellations, timeouts and infra failures remain in the planned denominator.
    denominator=len(planned);success=states['success']
    indexed={(r['case_id'],r['sample']):r for r in rows};weight=0;achieved=0
    for p in planned:
        row=indexed.get((p['case_id'],p['sample']),{});goals=p.get('goals')or[]
        if goals:
            checks={c['id']:c for c in row.get('goal_checks',[])}
            weight+=sum(g['weight']for g in goals)
            achieved+=sum(g['weight']for g in goals if checks.get(g['id'],{}).get('passed')is True)
        else:
            weight+=p.get('weight',1)
            if row.get('outcome')=='success':achieved+=p.get('weight',1)
    latencies=sorted(r['elapsed_ms']for r in rows if type(r.get('elapsed_ms'))in(int,float)and math.isfinite(r['elapsed_ms'])and r['elapsed_ms']>=0)
    known={k:[]for k in('input_tokens','output_tokens')}
    for row in rows:
        for k in known:
            v=(row.get('usage')or{}).get(k)
            if type(v)is int and v>=0:known[k].append(v)
    groups=defaultdict(list)
    for plan in planned:groups[plan['case_id']].append(plan['sample'])
    reliability={}
    for ident,samples in groups.items():
        actual=[indexed.get((ident,sample))for sample in sorted(samples)]
        settled=[r for r in actual if r and not r.get('progress')]
        n=len(samples);c=sum(r.get('outcome')=='success'for r in settled)
        complete=len(settled)==n and all(r.get('outcome')not in{'not_started','infrastructure_failure'}for r in settled)
        reliability[ident]=dict(planned=n,settled=len(settled),successes=c,first_success=next((r['sample']for r in actual if r and r.get('outcome')=='success'),None),
            pass_at_1=c/n if complete else None,pass_all=c==n if complete else None,pass_any=c>0 if settled else None,
            estimates=[dict(k=k,pass_at_k=1-(math.comb(n-c,k)if n-c>=k else 0)/math.comb(n,k),
                            pass_power_k=(math.comb(c,k)if c>=k else 0)/math.comb(n,k))for k in range(1,n+1)]if complete else[],
            estimator='fixed_attempts_without_replacement',cancelled_counts_as_failure=True,complete_sample_plan=complete)
    observations={o['id']:o for r in rows for o in r.get('model_observations',[])}
    model_rows=list(observations.values());costs=[r['cost_cny']for r in model_rows if type(r.get('cost_cny'))in(int,float)and math.isfinite(r['cost_cny'])and r['cost_cny']>=0]
    complete=bool(model_rows)and all(r.get('model_observations_complete')for r in rows if r.get('task_id'))
    cache={}
    for key in ('cached_tokens','cache_write_tokens'):
        values=[(r.get('usage')or{}).get(key)for r in model_rows];valid=[v for v in values if type(v)is int and v>=0]
        cache[key]=dict(known=sum(valid),unknown_model_calls=len(values)-len(valid))
    # Historical first_token_ms may include reasoning. It is not evidence of
    # first visible text and must not silently enter the new TTFT definition.
    times=[r.get('first_text_ms')for r in model_rows]
    ttft=sorted(t for t in times if type(t)in(int,float)and math.isfinite(t)and t>=0)
    return dict(version=VERSION,planned=denominator,observed=sum(not r.get('progress')for r in rows),started=sum(bool(r.get('task_id'))for r in rows),outcomes=dict(states),success=dict(numerator=success,denominator=denominator,rate=success/denominator if denominator else None),
                attainment=dict(achieved_weight=achieved,total_weight=weight,rate=achieved/weight if weight else None,scope='explicit_goal_checks_or_all_mandatory_case_checks'),
                false_success=states['false_success'],cancellation_denominator='included_in_planned',
                latency=dict(samples=len(latencies),p50_ms=latencies[(len(latencies)-1)//2]if latencies else None,p95_ms=latencies[math.ceil(len(latencies)*.95)-1]if len(latencies)>=20 else None),
                usage={k:dict(known=sum(v),unknown_attempts=denominator-len(v))for k,v in known.items()},
                cache=cache,model_observations=len(model_rows),model_observations_complete=complete,
                ttft=dict(definition='model_adapter_entry_to_first_visible_text_reasoning_excluded',samples=len(ttft),unknown_model_calls=len(model_rows)-len(ttft),p50_ms=ttft[(len(ttft)-1)//2]if ttft else None,p95_ms=ttft[math.ceil(len(ttft)*.95)-1]if len(ttft)>=20 else None),
                cost_cny=round(sum(costs),8)if complete and len(costs)==len(model_rows)else None,
                cost=dict(known_cny=round(sum(costs),8),unknown_model_calls=len(model_rows)-len(costs),coverage_complete=complete),reliability=reliability)


def compare(baseline,candidate):
    if baseline.get('state','completed')!='completed'or candidate.get('state','completed')!='completed':raise ValueError('评测批次尚未完整结算，不能判定改善。')
    if any(c.get('criteria')=='reference_rubric'for c in baseline.get('cases',[]))and baseline.get('review_effort','provider_default')!=candidate.get('review_effort','provider_default'):
        raise ValueError('两批独立评分的审阅策略不同，不能作为同标准改善比较。')
    if not baseline.get('judge_contract')or baseline['judge_contract']!=candidate.get('judge_contract'):raise ValueError('两批判定代码或 Judge 配置不同，请建立同一判定合同下的新批次。')
    if baseline['case_manifest_hash']!=candidate['case_manifest_hash']:raise ValueError('两批用例、标准或样本计划不同，不能作为同集改善比较。')
    a={(r['case_id'],r['sample']):r for r in baseline.get('results',[])};b={(r['case_id'],r['sample']):r for r in candidate.get('results',[])}
    pairs=[]
    for planned in baseline['planned']:
        key=(planned['case_id'],planned['sample']);left=a.get(key,{});right=b.get(key,{})
        before=left.get('outcome','not_started');after=right.get('outcome','not_started')
        pairs.append(dict(case_id=key[0],sample=key[1],baseline=before,candidate=after,
            change='improved'if after=='success'and before!='success'else'regressed'if before=='success'and after!='success'else'unchanged'))
    return dict(ok=True,baseline=baseline['id'],candidate=candidate['id'],items=pairs,changes=dict(Counter(p['change']for p in pairs)),
                configuration_changes={key:dict(baseline=baseline.get(key),candidate=candidate.get(key))for key in ('tool_loading','review_effort','model_config','code_version','candidate')if baseline.get(key)!=candidate.get(key)},
                baseline_metrics=baseline.get('metrics')or metrics(baseline.get('results',[]),baseline['planned']),candidate_metrics=candidate.get('metrics')or metrics(candidate.get('results',[]),candidate['planned']))
