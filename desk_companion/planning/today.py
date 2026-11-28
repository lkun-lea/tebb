"""账户工作区内的今日看板。简报按本地日期与时段保存，可追溯到原会话。"""
from datetime import datetime
import re


def defaults():
    return dict(version=0, project='', morning=dict(time='08:00', focus='questions'),
                evening=dict(time='20:00', focus='project'))


def timeline(state, project):
    if not project:
        return []
    chats = {c['id'] for c in state['conversations'] if c.get('project_id') == project}
    first_messages = {}
    for message in state['messages']:
        if message.get('run') and message['conversation'] in chats and message['sender'] == 'user':
            first_messages.setdefault(message['run'], message)
    events = []
    for run in state['runs']:
        if run['conversation'] not in chats or run.get('parent'):
            continue
        # 追加答复会更新运行标题。时间线的起点始终使用原始提问。
        first = first_messages.get(run['id'])
        title = (first['text'].strip() if first else '') or run['title']
        result = {'succeeded': '完成', 'failed': '失败', 'cancelled': '已取消'}.get(run['state'], '结束')
        for field, label in [('created', '开始'), ('finished', result)]:
            stamp = run.get(field)
            if stamp:
                events.append(dict(time=int(stamp), title=label + ' · ' + title[:120],
                                   conversation=run['conversation'], source=run['id']))
    return sorted(events, key=lambda row: row['time'], reverse=True)[:30]


def due_slots(board, now):
    day, clock = now.strftime('%Y-%m-%d'), now.strftime('%H:%M')
    reports = board.get('reports', {})
    for slot in ('morning', 'evening'):
        config = board['preferences'][slot]
        key = day + '/' + slot
        frequency = config.get('frequency', 'daily')
        days = {'daily': range(7), 'weekdays': range(5), 'weekends': (5, 6), 'off': ()}
        if now.weekday() not in days[frequency] or clock < config['time'] or key in reports:
            continue
        yield slot, key


def update_reports(board, now, questions, events):
    day = now.strftime('%Y-%m-%d')
    reports = board.setdefault('reports', {})
    for slot, key in due_slots(board, now):
        config = board['preferences'][slot]
        pending = [dict(title=q['prompt'], conversation=q['conversation'], source=q['run']) for q in questions]
        recent = [event for event in events if 0 <= now.timestamp() - event['time'] < 86400]
        rows = {'questions': pending, 'project': recent, 'both': pending + recent}[config['focus']]
        terms = config.get('keywords', '').casefold().split()
        if terms:
            rows = [row for row in rows if any(term in row['title'].casefold() for term in terms)]
        reports[key] = dict(slot=slot, date=day, generated=int(now.timestamp()), rows=rows[:8])
    for key in sorted(reports)[:-28]:
        del reports[key]


def latest_receipt(state, conversation=None):
    receipts = (run['journal_receipt'] for run in state['runs'] if run.get('journal_receipt')
                and (conversation is None or run['conversation'] == conversation))
    latest = max(receipts, key=lambda row: row['accepted'], default=None)
    if latest:
        return dict(latest, day=datetime.fromtimestamp(latest['accepted']).date().isoformat())


def project_board(state, questions, preferences, scheduled, now):
    board = state.setdefault('today_board', dict(preferences=defaults()))
    config = board['preferences']
    projects = [dict(id=p['id'], name=p['name']) for p in state['projects']]
    if preferences is not None:
        if not isinstance(preferences, dict) or preferences.get('version') != config['version']:
            raise ValueError('看板设置已更新，请刷新后再保存。')
        selected = preferences.get('project', '')
        if selected and selected not in {p['id'] for p in projects}:
            raise ValueError('所选项目已移除。')
        next_config = dict(version=config['version'] + 1, project=selected)
        for slot in ('morning', 'evening'):
            period = preferences.get(slot) or {}
            if (not isinstance(period, dict) or period.get('focus') not in ('questions', 'project', 'both')
                or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', str(period.get('time', '')))):
                raise ValueError('请选择有效的简报时间和内容。')
            words = period.get('keywords', '')
            if not isinstance(words, str) or len(words) > 120:
                raise ValueError('关注词最多 120 个字符。')
            frequency = period.get('frequency', 'daily')
            if frequency not in ('daily', 'weekdays', 'weekends', 'off'):
                raise ValueError('请选择有效的简报周期。')
            next_config[slot] = dict(time=period['time'], focus=period['focus'], keywords=words.strip(),
                                     frequency=frequency)
        board['preferences'] = config = next_config
    events = timeline(state, config['project'])
    if not scheduled:
        forms = {run['id']: run['clarification_form'] for run in state['runs'] if run.get('clarification_form')}
        for question in questions:
            form = forms.get(question['run'])
            if form and form['version'] == question['version']:
                question['form'] = form
    update_reports(board, now, questions, events)
    if not scheduled:
        day = now.strftime('%Y-%m-%d')
        return dict(day=day, receipt=latest_receipt(state), preferences=config, projects=projects, questions=questions, events=events,
                    reports=[r for r in board['reports'].values() if r['date'] == day])


def attach_mobile_board(state, history, now=None):
    """只随已授权的会话投影视图。撤销共享后，对应看板内容也随快照移除。"""
    board = state.get('today_board')
    if not history:
        return
    day = (now or datetime.now().astimezone()).strftime('%Y-%m-%d')
    events = timeline(state, board['preferences']['project']) if board else []
    sources = {'project': events}
    sources.update({r['slot']: r['rows'] for r in (board or {}).get('reports', {}).values() if r['date'] == day})
    for chat in history:
        sections = {}
        for slot, rows in sources.items():
            visible = [dict(title=r['title'][:160], time=r.get('time'), source=r['source'])
                       for r in rows if r['conversation'] == chat['id']][:6]
            if visible:
                sections[slot] = visible
        receipt = latest_receipt(state, chat['id'])
        if sections or receipt:
            chat['today'] = dict(date=day, sections=sections)
            if receipt:
                chat['today']['receipt'] = dict(receipt, answer=receipt['answer'][:400], truncated=len(receipt['answer']) > 400)
