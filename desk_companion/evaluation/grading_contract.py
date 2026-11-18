"""Freeze grading code separately from the candidate implementation."""
from pathlib import Path
from desk_companion.observability.tool_monitor import fingerprint


def grading_contract(cases,judge_model_config=None):
    directory=Path(__file__).parent
    files=['agent_evals.py','batch_metrics.py','promptfoo/provider.py','profile_snapshot.py',
           '../../scripts/eval_agent.py',*[p.name for p in sorted(directory.glob('agent_eval_*.py'))]]
    if any(c.get('criteria')in{'reference_rubric','reference_judge_calibration'}for c in cases):
        files+=['reference_judge.py','../collaboration/feedback_review.py']
    return fingerprint(dict(sources={name:fingerprint((directory/name).read_text('utf-8'))for name in files},judge_model_config=judge_model_config))
