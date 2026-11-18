"""Calibrate the public reference reviewer against fixed, reviewed candidates.

This is a component assessment operation, not a queued business task. Its real
budget member and model calls are retained without fabricating task receipts.
"""
from desk_companion.tasks.task_budgets import budgeted_operation,current
from desk_companion.evaluation.reference_judge import assess


def verdict(assessment,expected):
    goals=assessment.get('goal_checks',[])
    checks=[c for goal in goals for c in goal.get('checks',[])]
    valid=bool(goals)and bool(checks)and all(c.get('id')!='review_protocol'and not c.get('protocol_errors')and not c.get('invalid_evidence_ids')for c in checks)
    states=[goal['status']for goal in goals]
    observed='fail'if 'fail'in states else'pass'if states and all(s=='pass'for s in states)else'unknown'
    matched=valid and observed==expected
    return dict(verified=matched,expected=expected,observed=observed,valid_assessment=valid,
        false_accept=valid and expected!='pass'and observed=='pass',
        false_reject=valid and expected=='pass'and observed=='fail',
        candidate_accepted=valid and observed=='pass',scope='reviewer_calibration_not_business_task_acceptance')


@budgeted_operation('judge_calibration','simple')
def execute(spec,model,*,timeout,should_cancel=None,review_effort='provider_default',progress=lambda _:None):
    task=current().task
    progress(dict(task_id=task,task_ids=[task],execution_kind='component_operation',stage='review'))
    try:
        assessment=assess(dict(prompt=spec['prompt'],expected=spec['reference'],
            rubric=[dict(id='calibration_criterion',criterion=spec['criterion'],weight=1)]),spec['candidate'],model,
            timeout=min(timeout,60),should_cancel=should_cancel,review_effort=review_effort)
        evidence=verdict(assessment,spec['expected']['status'])
        outcome='success'if evidence['verified']else'incomplete'if not evidence['valid_assessment']or evidence['observed']=='unknown'else'failed'
        return dict(task_id=task,outcome=outcome,assessment=assessment,evidence=evidence)
    except Exception as exc:
        return dict(task_id=task,outcome='incomplete',error_kind=type(exc).__name__,
            evidence=dict(verified=False,expected=spec['expected']['status'],observed='unknown',valid_assessment=False,
                          scope='reviewer_calibration_not_business_task_acceptance'))
