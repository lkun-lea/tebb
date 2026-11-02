"""Measured workflow costs and rework; missing usage is never treated as zero."""
from pathlib import Path
import hashlib
import json


def measure(state):
    totals = {}
    phases = []
    missing = []
    counters = {}
    anomalies = []
    for attempt in state['attempts']:
        if attempt.get('replayed'):
            phases.append(dict(stage=attempt['stage'],directory=attempt['directory'],status='historical_replay',tokens=None,usage_reported=False))
            continue
        usage = [u for u in attempt.get('usage', []) if isinstance(u, dict)]
        row = dict(stage=attempt['stage'], directory=attempt['directory'],
                   status=attempt['status'], usage_reported=bool(usage), tokens={})
        session = attempt.get('session') or attempt.get('resume_session') or 'attempt:'+attempt['directory']
        row['accounting_session'] = session
        previous = counters.setdefault(session, {})
        # turn.completed reports a session counter, including previous resumed
        # turns. Use the last observation and subtract this session's high water.
        for packet in usage[-1:]:
            if any(type(packet.get(k)) is not int for k in ('input_tokens', 'cached_input_tokens', 'output_tokens')):
                anomalies.append(dict(attempt=attempt['directory'], reason='incomplete_token_fields'))
            for key, value in packet.items():
                if isinstance(value, int) and not isinstance(value, bool):
                    before = previous.get(key, 0)
                    if value < before or value < 0:
                        anomalies.append(dict(attempt=attempt['directory'], field=key, reason='counter_decreased'))
                        continue
                    delta = value-before
                    totals[key] = totals.get(key, 0)+delta
                    row['tokens'][key] = delta
                    previous[key] = value
            if packet.get('cached_input_tokens', 0) > packet.get('input_tokens', 0):
                anomalies.append(dict(attempt=attempt['directory'], reason='cache_exceeds_input'))
        if not usage and attempt['status'] != 'running':
            missing.append(attempt['directory'])
        if 'ended' in attempt:
            row['seconds'] = round(attempt['ended'] - attempt['started'], 3)
        phases.append(row)
    known = bool(totals)
    input_tokens = totals.get('input_tokens')
    cached = totals.get('cached_input_tokens')
    uncached = max(0, input_tokens-cached) if input_tokens is not None and cached is not None else None
    return dict(format=1, status=state['status'], version=state['version'],
                reported_tokens=totals if known else None, uncached_input_tokens=uncached,
                usage_complete=known and not missing and not anomalies and all(a['status'] != 'running' for a in state['attempts']),
                missing_usage_attempts=missing, counter_anomalies=anomalies,
                fees=None, phases=phases, cli_launches=state['launches'],
                development_submissions=len(state['rounds']),
                development_attempts=sum(a['stage']=='develop'and not a.get('replayed')for a in state['attempts']),
                repair_attempts=max(0,sum(a['stage']=='develop'and not a.get('replayed')for a in state['attempts'])-1),
                reflection_followups=state.get('reflection_followups',0),
                repair_submissions=max(0, len(state['rounds'])-1),
                scope_revisions=state['scope_revisions'],
                verification_refinements=len(state.get('verification_plan', [])),
                report_supplements=state['supplements_used'],
                recovery_actions=len(state.get('recoveries', [])),
                acceptance_revision_attempts=state.get('acceptance_revisions',0),
                acceptance_revisions_adopted=len(state.get('acceptance_history',[])),
                objective_cache_reuses=state.get('objective_cache_reuses',0),
                objective_receipt_handoffs=state.get('objective_receipt_handoffs',0),
                observed_environment_limits=len(state.get('environment_capabilities',[])),
                diagnostic_launches=sum(a['stage']=='diagnose'and not a.get('replayed')for a in state['attempts']),
                measurement_scope='Stage CLI only; external repairs/delivery and additional model probes must be reported separately, not as zero.',
                objective_rejections=sum(r.get('objective', {}).get('status') == 'fail' for r in state['rounds']),
                note='Session cumulative counters are de-duplicated across resume. Phase tokens are increments since the previous observed counter, possibly including interrupted attempts. Input includes cached input; reasoning output is a subset of output. CLI launches are not API calls. Red-step test failures are not automatically rework. Fees remain unknown.')


def improvement_candidates(folder, state, reflection):
    """A proposal remains proposed until a separate change and comparison proves it."""
    record=state.get('reflection',{}).get('report')
    index=Path(folder)/record/'observation-index.json'if record else Path(folder)/'observation-index.json'
    sources = [dict(path=str(index), sha256=hashlib.sha256(index.read_bytes()).hexdigest())] if index.is_file() else []
    observations=json.loads(index.read_text('utf-8')) if index.is_file() else dict(observations=[])
    known={o['id'] for o in observations['observations']}
    return dict(format=2, task=str(folder), workflow_version=state['version'],
                items=[dict(id='I-'+hashlib.sha256((str(folder)+json.dumps(proposal,sort_keys=True,ensure_ascii=False)).encode()).hexdigest()[:12],
                            status='proposed', **proposal, evidence_index=sources,
                            evidence_valid=bool(proposal['observation_ids']) and set(proposal['observation_ids'])<=known,
                            validation_plan=reflection['validation_plan'],
                            implementation=None, regression_case=None, comparison=None)
                       for proposal in reflection['proposals']])
