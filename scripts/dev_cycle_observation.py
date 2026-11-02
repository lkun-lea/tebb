"""Read-only, provenance-checked access to workflow failures; no model-written summaries."""
import hashlib
import json
from pathlib import Path


CAPABILITIES = ['independent_verification', 'structured_evidence_path_and_observation',
                'evidence_file_gate', 'one_supplement_without_score_changes', 'three_round_limit',
                'current_target_only_no_legacy_compatibility', 'predevelopment_scope_review',
                'progress_supervision_without_elapsed_termination', 'clean_python_with_source_guard',
                'standard_private_dependency_installation', 'namespace_module_provenance',
                'pre_model_environment_preflight']


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode()


def load_source(folder, ref):
    path = Path(ref['path']).resolve()
    if folder not in path.parents:
        raise ValueError('观察源不属于当前任务')
    if 'line' in ref:
        with path.open('r', encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                if number == ref['line']:
                    return canonical(json.loads(line))
        raise ValueError('原始事件行不存在')
    if 'selector' in ref:
        value = json.loads(path.read_text('utf-8'))
        for key in ref['selector']:
            value = value[key]
        return canonical(value)
    return path.read_bytes()


def build_index(folder, state):
    folder = Path(folder).resolve()
    rows = []

    def reference(path, **selector):
        ref = dict(path=str(Path(path).resolve()), **selector)
        try:
            data = load_source(folder, ref)
            ref.update(sha256=hashlib.sha256(data).hexdigest(), bytes=len(data))
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            ref['unavailable'] = type(exc).__name__
        return ref

    def add(kind, attempt, identity, refs, **metadata):
        ident = hashlib.sha256(canonical([attempt['directory'], kind, identity])).hexdigest()[:12]
        rows.append(dict(id='O-' + ident, kind=kind, stage=attempt['stage'], round=attempt['round'],
                         attempt=attempt['directory'], sources=refs, **metadata))

    for path in sorted((folder/'environment').glob('*/result.json')):
        try:
            result = json.loads(path.read_text('utf-8'))
        except (OSError, ValueError):
            continue
        if result.get('status') == 'blocked':
            attempt = dict(directory=path.parent.relative_to(folder).as_posix(), stage='environment', round=0)
            add('environment_preflight', attempt, 'result', [reference(path), reference(path.parent/'stderr.log'),
                                                            reference(path.parent/'install.log')])

    for path in sorted((folder/'acceptance').glob('revision-*/calibration/result.json')):
        try:result=json.loads(path.read_text('utf-8'))
        except (OSError,ValueError):continue
        if result.get('status')!='pass':
            attempt=dict(directory=path.parent.relative_to(folder).as_posix(),stage='evaluator_calibration',round=state.get('round',0))
            add('evaluator_calibration_failure',attempt,'result',[reference(path),reference(path.parent/'execution.json'),
                reference(path.parent/'stdout.log'),reference(path.parent/'stderr.log')])
    for path in sorted((folder/'acceptance').glob('revision-*/calibration-rejected.json')):
        attempt=dict(directory=path.parent.relative_to(folder).as_posix(),stage='evaluator_calibration',round=state.get('round',0))
        add('evaluator_calibration_rejected',attempt,'result',[reference(path)])
    for cycle in state.get('rounds', []):
        for number, result in enumerate(cycle.get('objective_history', [])):
            if result.get('status') in {'fail', 'unknown'}:
                path = Path(result['report'])
                attempt = dict(directory=path.parent.relative_to(folder).as_posix(), stage='objective', round=cycle['round'])
                add('objective_failure', attempt, number, [reference(path), reference(path.parent/'stdout.log'),
                    reference(path.parent/'stderr.log'), reference(path.parent/'execution.json')],
                    classification=result.get('failure_type'), classification_basis='objective_checker_assessment')

    for number, attempt in enumerate(state['attempts']):
        if attempt['stage'] == 'reflect' or attempt['status'] == 'running':
            continue
        root = folder / attempt['directory']
        result_path = root / 'result.json'
        try:
            result = json.loads(result_path.read_text('utf-8'))
        except (OSError, ValueError):
            result = None
        if attempt.get('error'):
            add('stage_error', attempt, 'error', [reference(folder/'state.json', selector=['attempts', number, 'error']),
                                                 reference(root/'stderr.log'), reference(root/'packet.json'),
                                                 reference(root/'monitor.json')])
        if attempt.get('gate_error'):
            add('handoff_rejected', attempt, 'gate', [reference(folder/'state.json', selector=['attempts', number, 'gate_error']),
                                                     reference(result_path)])
        notifications = folder/'notifications.jsonl'
        if notifications.is_file():
            for line_number, line in enumerate(notifications.read_text('utf-8').splitlines(), 1):
                try:
                    notice = json.loads(line)
                except ValueError:
                    continue
                if isinstance(notice, dict) and notice.get('attempt') == Path(attempt['directory']).name:
                    add('progress_attention', attempt, line_number, [reference(notifications, line=line_number),
                                                                   reference(root/'monitor.json')])
        # Controller-checked provenance receipts remain directly observable, even
        # if an agent swallowed ImportError and claimed a passing result.
        try:
            artifacts = json.loads((root/'artifacts.json').read_text('utf-8'))
            evidence_dir = Path(artifacts['evidence_dir']).resolve()
            if folder not in evidence_dir.parents:
                raise ValueError('来源审计目录超出任务')
            for path in (evidence_dir/'imports').glob('*.jsonl'):
                for line_number, line in enumerate(path.read_text('utf-8').splitlines(), 1):
                    receipt = json.loads(line)
                    if isinstance(receipt, dict) and receipt.get('allowed') is False:
                        add('source_mismatch', attempt, [path.name, line_number], [reference(path, line=line_number)])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if isinstance(result, dict):
            if attempt['stage'] == 'scope_review' and result.get('decision') != 'aligned':
                add('scope_misalignment', attempt, 'scope', [reference(result_path), reference(root/'packet.json')])
            if attempt['stage'] in {'verify', 'supplement'} and isinstance(result.get('checks'), list):
                for i, check in enumerate(result['checks']):
                    if not isinstance(check, dict) or check.get('status') not in {'fail', 'unknown'}:
                        continue
                    refs = [reference(result_path, selector=['checks', i])]
                    evidence_rows = check.get('evidence', [])
                    for evidence in evidence_rows if isinstance(evidence_rows, list) else []:
                        if isinstance(evidence, dict) and isinstance(evidence.get('path'), str):
                            refs.append(reference(evidence['path']))
                    add('failed_check', attempt, i, refs, criterion_id=check.get('criterion_id'),
                        status=check['status'], classification=check.get('failure_type'),
                        classification_basis='verifier_assessment_not_proven_root_cause')
            if attempt['stage'] == 'supervise' and result.get('decision') != 'pass':
                add('supervision_decision', attempt, 'decision', [reference(result_path)])
            if attempt['stage'] == 'supervise' and result.get('process_review',{}).get('status') in {'improve','unknown'}:
                add('workflow_assessment',attempt,'process_review',
                    [reference(result_path,selector=['process_review']),reference(root/'process-review.json')],
                    classification_basis='supervisor_assessment_not_proven_root_cause')
            if attempt['stage'] == 'develop' and result.get('status') == 'blocked':
                add('prerequisite_blocked', attempt, 'blocked', [reference(result_path)])
            if attempt['stage'] == 'requirements' and result.get('status') == 'needs_input':
                add('requirements_gap', attempt, 'questions', [reference(result_path)])
            if attempt['stage'] == 'develop' and attempt['round'] > 1:
                add('revision', attempt, 'changes', [reference(result_path)])
        events_path = root/'events.jsonl'
        if events_path.is_file():
            with events_path.open('r', encoding='utf-8', errors='replace') as stream:
                for line_number, line in enumerate(stream, 1):
                    try:
                        event = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    item = event.get('item')
                    item = item if isinstance(item, dict) else {}
                    code = item.get('exit_code')
                    if event.get('type') == 'item.completed' and item.get('type') == 'command_execution' and type(code) is int and code != 0:
                        add('command_nonzero', attempt, line_number,
                            [reference(events_path, line=line_number)], exit_code=code,
                            interpretation='Observed exit only; expected red tests are possible.')
                    elif event.get('type') in {'error', 'turn.failed'}:
                        add('transport_or_runtime_event', attempt, line_number, [reference(events_path, line=line_number)])
    return dict(version=1, current_capabilities=CAPABILITIES, observations=rows,
                interpretation='Observed facts and original assessments; causality may remain unknown.')


def index_view(index, offset=0, limit=12):
    priorities = {'failed_check': 0, 'objective_failure': 0, 'handoff_rejected': 1, 'stage_error': 2, 'prerequisite_blocked': 3,
                  'source_mismatch': 0, 'scope_misalignment': 1, 'progress_attention': 2,
                  'requirements_gap': 4, 'supervision_decision': 5, 'revision': 6}
    rows = sorted(index['observations'], key=lambda x: (priorities.get(x['kind'], 7), x['round'], x['attempt']))
    return dict(total=len(rows), offset=offset, truncated=offset+limit < len(rows),
                items=[{k: v for k, v in row.items() if k != 'sources'} for row in rows[offset:offset+limit]],
                current_capabilities=index['current_capabilities'])


def observe(folder, ids=(), *, max_bytes=6000, offset=0, limit=12, source_offset=0, output_only=False, tail=False):
    """Retrieve exact evidence by ID, verify snapshots, never execute commands or rewrite results."""
    folder = Path(folder).resolve()
    if not 256 <= max_bytes <= 12000 or len(ids) > 3 or not 0 <= offset or not 1 <= limit <= 40 or not 0 <= source_offset <= 1048576:
        raise ValueError('每次至多读取3个观察，内容预算256..12000字节，索引分页1..40条')
    path = folder/'observation-index.json'
    index = json.loads(path.read_text('utf-8')) if path.exists() else build_index(folder, json.loads((folder/'state.json').read_text('utf-8')))
    if not ids:
        return index_view(index, offset, limit)
    known = {row['id']: row for row in index['observations']}
    if any(ident not in known for ident in ids):
        raise ValueError('观察ID不存在，不猜测文件路径')
    result, remaining = [], max_bytes
    for ident in ids:
        row = known[ident]
        sources = []
        for ref in row['sources']:
            value = dict(reference=ref)
            try:
                data = load_source(folder, ref)
                verified = hashlib.sha256(data).hexdigest() == ref.get('sha256')
                value['verified'] = verified
                if verified:
                    if output_only:
                        event = json.loads(data)
                        item = event.get('item') if isinstance(event, dict) else None
                        text = item.get('aggregated_output') if isinstance(item, dict) else None
                        if not isinstance(text, str):
                            raise ValueError('该来源不是命令输出事件')
                        data = text.encode('utf-8')
                        value['view'] = 'original_item.aggregated_output'
                    capacity = min(remaining, 2400)
                    start = max(0, len(data)-capacity) if tail else min(source_offset, len(data))
                    count = min(len(data)-start, capacity)
                    value.update(content=data[start:start+count].decode('utf-8', errors='replace'),
                                 offset=start, has_more=start+count < len(data), truncated=start > 0 or count < len(data))
                    remaining -= count
                else:
                    value['error'] = 'source_changed_or_originally_unavailable'
            except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
                value.update(verified=False, error=type(exc).__name__)
            sources.append(value)
        result.append(dict(observation={k: v for k, v in row.items() if k != 'sources'}, sources=sources))
    return dict(observations=result, content_bytes=max_bytes-remaining,
                warning='Truncated/unavailable evidence does not prove a cause; use another bounded read if needed.')
