"""A reviewable gate over frozen original batches; never rewrite or retry results."""
from desk_companion.evaluation.batch_metrics import compare
from desk_companion.observability.timeout_diagnostics import report


def gate(baseline,candidate,holdout=None):
    comparison=compare(baseline,candidate)
    def passed(batch):
        return bool(batch and batch['state']=='completed'and batch['planned']and len(batch.get('results',[]))==len(batch['planned'])
            and all(r['outcome']=='success'and not r.get('progress')for r in batch['results']))
    before=report(baseline);after=report(candidate)
    def observed(batch):
        return bool(batch and batch.get('results')and all(r.get('call_ids')and r.get('call_evidence_complete')and r.get('model_observations_complete')for r in batch['results']))
    independent=bool(holdout and holdout['cases']and all(c['split']=='holdout'for c in holdout['cases'])
        and not({c['id']for c in holdout['cases']}&{c['id']for c in candidate['cases']})
        and all(holdout.get(k)==candidate.get(k)for k in ('model_config','judge_config','review_effort','tool_loading','judge_limits','code_version','mode','judge_contract','timeout')))
    checks=dict(candidate_all_mandatory_checks=passed(candidate),no_regressions=not comparison['changes'].get('regressed'),
        baseline_model_evidence_complete=observed(baseline),candidate_model_evidence_complete=observed(candidate),
        timeout_baseline_observed=before['timeout_calls']>0,no_candidate_timeouts=after['timeout_calls']==0,
        independent_holdout=independent,holdout_all_mandatory_checks=independent and passed(holdout)and observed(holdout))
    return dict(ok=True,ready_for_review=all(checks.values()),checks=checks,comparison=comparison,
        timeout_before=before['timeout_calls'],timeout_after=after['timeout_calls'],
        holdout=holdout['id']if holdout else None,scope='fixed_samples_not_population_reliability',
        baseline=baseline['id'],candidate=candidate['id'],verification_mode=candidate['mode'],automatic_release=False)
