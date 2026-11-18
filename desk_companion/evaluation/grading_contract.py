"""Freeze grading code separately from the candidate implementation."""
from pathlib import Path
from desk_companion.observability.tool_monitor import fingerprint


def grading_contract(cases,judge_model_config=None,*,review_effort='provider_default'):
    directory=Path(__file__).parent
    files=['agent_evals.py','batch_metrics.py','promptfoo/provider.py','profile_snapshot.py','artifacts.py',
           '../../scripts/eval_agent.py',*[p.name for p in sorted(directory.glob('agent_eval_*.py'))]]
    if any(c.get('criteria')in{'reference_rubric','reference_judge_calibration'}for c in cases):
        files+=['reference_judge.py','../collaboration/feedback_review.py']
    if any(c.get('spec',{}).get('executor')=='timeout_probe'for c in cases):
        files+=['../observability/timeout_diagnostics.py','../observability/stream_progress.py']
    contract=dict(sources={name:fingerprint((directory/name).read_text('utf-8'))for name in files},judge_model_config=judge_model_config)
    # In business rubrics the reviewer is the grader. In calibration the reviewer
    # is the candidate being measured against fixed expected labels instead.
    if any(c.get('criteria')=='reference_rubric'for c in cases):contract['review_effort']=review_effort
    return fingerprint(contract)
