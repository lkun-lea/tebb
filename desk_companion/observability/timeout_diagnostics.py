"""Evidence-based timeout localization. Observations are not inferred root causes."""
from collections import Counter

LABELS={'before_model_send':'模型发送前超时（进程桥或准入阶段）','before_headers':'响应头前超时','before_frame':'已收到响应头，未收到流事件','reasoning_without_answer':'已输出推理，尚无正文',
    'stream_gap':'流式输出后出现长间隔','text_unfinished':'正文已开始，结果未完成','tool_call_unfinished':'工具调用参数仍未完成','stream_without_output':'已收到流事件，未收到正文或推理',
    'unknown':'缺少阶段证据','not_timeout':'非超时调用'}


def diagnose(row):
    error=row.get('error_kind')or''
    timeout=row.get('state')=='timed_out'or 'timeout'in error.lower()
    progress=row.get('stream_progress')
    if progress is not None:
        from desk_companion.observability.stream_progress import validate
        try:validate(progress)
        except ValueError:progress=None
    kind='not_timeout'
    if timeout:
        kind='unknown'
        if progress:
            elapsed=progress['elapsed_ms'];last=max((progress.get(k)or 0)for k in ('last_frame_ms','last_text_ms','last_reasoning_ms'))
            if 'request_ms'in progress and progress['request_ms']is None:kind='before_model_send'
            elif progress.get('headers_ms')is None:kind='before_headers'
            elif progress.get('first_frame_ms')is None:kind='before_frame'
            elif elapsed-last>=1000 and elapsed-last>=(elapsed-progress['first_frame_ms'])*.5:kind='stream_gap'
            elif progress.get('text_characters',0):kind='text_unfinished'
            elif progress.get('reasoning_characters',0):kind='reasoning_without_answer'
            elif progress.get('tool_call_frames',0):kind='tool_call_unfinished'
            else:kind='stream_without_output'
    return dict(id=row['id'],task=row.get('task'),kind=kind,label=LABELS[kind],timeout=timeout,
        error_kind=error or None,progress=progress,evidence='measured_stream_progress'if progress else'missing_historical_timing',
        limitation='响应头前不能区分DNS/TCP/TLS/网关排队；流间隔不证明断网；推理持续输出不证明模型缺陷。')


def report(batch):
    calls={r['id']:r for row in batch.get('results',[])for r in row.get('model_observations',[])}
    rows=[dict(**diagnose(r),case_id=next((a['case_id']for a in batch['results']if any(o['id']==r['id']for o in a.get('model_observations',[]))),None))for r in calls.values()]
    return dict(ok=True,batch=batch['id'],calls=len(rows),timeout_calls=sum(r['timeout']for r in rows),
        localization=dict(Counter(r['kind']for r in rows if r['timeout'])),items=rows,
        scope='model_call_timeout_not_business_task_outcome',unknown_usage_preserved=True)
