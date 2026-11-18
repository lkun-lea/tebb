"""Golden reference assessment through the existing bounded evidence reviewer.

One tool-free call per frozen criterion. The supplied reference is user material,
never evidence of an external operation. Missing or invalid evidence stays unknown.
"""
import json
from desk_companion.tasks.task_budgets import budgeted_operation,current,phase
from desk_companion.collaboration.feedback_review import review,INSTRUCTION
from desk_companion.observability.tool_monitor import fingerprint


@budgeted_operation('golden_reference_judge','simple')
def assess(spec,answer,model,*,timeout=60,should_cancel=None):
    from atlas.llm import ChatOptions
    from desk_companion.pi_runtime.inference import PiInference
    from desk_companion.observability.agent_debug import context
    rows=[];task=current().task
    with PiInference(model,timeout=timeout)as llm:
        for criterion in spec['rubric']:
            if should_cancel and should_cancel():
                rows.append(dict(id=criterion['id'],weight=criterion['weight'],passed=None,status='unknown',error_kind='Cancelled'));continue
            goal=json.dumps(dict(task=spec['prompt'],reference=spec['expected'],criterion=criterion['criterion'],
                scope='参考答案是给定材料；候选可以采用其他满足目标的合法表达；参考不证明任何外部操作。'),ensure_ascii=False)
            with phase('feedback_review'),context(phase='golden_reference_judge',role='independent_reviewer',agent='golden_reference_judge'):
                checks=review(goal,answer,[],[],lambda messages:llm.chat(messages,options=ChatOptions(should_cancel=should_cancel)))
            statuses=[c['status']for c in checks]
            state='fail'if 'fail'in statuses else'pass'if statuses and all(s=='pass'for s in statuses)else'unknown'
            rows.append(dict(id=criterion['id'],weight=criterion['weight'],passed=True if state=='pass'else False if state=='fail'else None,
                status=state,checks=checks,evidence='existing_feedback_review_exact_excerpts'))
    return dict(task_id=task,goal_checks=rows,model_id=model['id'],model=model['model'],prompt_version=fingerprint(INSTRUCTION),
        contract='reference_rubric_v1',calls_budgeted=True,tools_allowed=False)
