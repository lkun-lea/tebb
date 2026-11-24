"""Validated calendar proposals live in task events; saved state belongs to LocalCalendar."""
import copy
from datetime import datetime
import json
import re
import uuid

from desk_companion.planning.calendar_adapter import creation_fields
from desk_companion.planning.calendar_time import TZ

KIND='calendar_proposal'
ZONE='Asia/Shanghai'


def _identity(value,*,optional=False):
    if optional and value=='':return ''
    if not isinstance(value,str)or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}',value):raise ValueError('提案来源编号无效。')
    return value


def _fields(values):
    if not isinstance(values,dict)or values.get('timezone',ZONE)!=ZONE:raise ValueError('日程提案使用 Asia/Shanghai 时区。')
    for key in('start','end'):
        if not isinstance(values.get(key),str):raise ValueError('请提供明确的起止时间。')
        parsed=datetime.fromisoformat(values[key])
        if parsed.utcoffset()is None:raise ValueError('提案起止时间必须包含时区。')
        if parsed.second or parsed.microsecond:raise ValueError('提案按分钟安排，请提供整分钟时段。')
    fields=creation_fields(values.get('summary'),values['start'],values['end'],allow_past=True)
    return dict(**fields,item_id=_identity(values.get('item_id',''),optional=True),timezone=ZONE)


def _proposal(fields,task_id,run_id=''):
    source=dict(task_id=_identity(task_id),run_id=_identity(run_id,optional=True))
    payload=json.dumps(dict(fields=fields,source=source),sort_keys=True,ensure_ascii=False,separators=(',',':'))
    ident=uuid.uuid5(uuid.NAMESPACE_URL,'tebb-calendar-proposal:'+payload).hex
    return dict(kind=KIND,version=1,id=ident,source=source,save_request_id=uuid.uuid5(uuid.NAMESPACE_URL,'tebb-calendar-proposal-save:'+ident).hex,**fields)


def require_item(item_id,items):
    if not item_id:return
    item=next((item for item in items if isinstance(item,dict)and item.get('id')==item_id),None)
    if item is None or item.get('archived'):raise ValueError('来源事项不存在或已归档，请先核对事项。')


def build(values,*,task_id,run_id='',items=(),now=None):
    fields=_fields(values);require_item(fields['item_id'],items)
    if datetime.fromisoformat(fields['end'])<=(now or datetime.now(TZ)):raise ValueError('安排已经结束，请提供未来或正在进行的时段。')
    return dict(ok=True,change_state='not_changed',proposal=_proposal(fields,task_id,run_id))


def validate(value,*,task_id):
    if not isinstance(value,dict)or value.get('kind')!=KIND or type(value.get('version'))is not int or value['version']!=1:raise ValueError('日程提案协议无效。')
    source=value.get('source')
    if not isinstance(source,dict)or source.get('task_id')!=task_id:raise ValueError('日程提案任务来源不匹配。')
    expected=_proposal(_fields(value),task_id,source.get('run_id',''))
    if value.get('id')!=expected['id']or value.get('save_request_id')!=expected['save_request_id']:
        raise ValueError('日程提案字段与原编号不匹配。')
    return expected


def tool_spec(workspace_path=None):
    def propose(arguments):
        from desk_companion.observability.agent_debug import metadata
        from desk_companion.planning.work_board import WorkBoardService
        source=metadata();task_id=_identity(source.get('task_id',''))
        board=WorkBoardService(path=workspace_path).load()
        if not board.get('ok'):raise ValueError('事项状态尚未读取，未生成提案。')
        return build(arguments,task_id=task_id,run_id=source.get('collab_run',''),items=board['items'])
    return dict(type='function',function=dict(name='calendar_propose',
        description='仅当用户明确要求草稿、先看看或确认后再保存时生成日程提案。仅校验本地事项、标题和明确起止时间，默认北京时间；不创建日程、不建立关联、不同步飞书。缺标题或时段先询问。返回结构化proposal后提示用户点击“打开日程草稿”，不能声称已保存。',
        parameters=dict(type='object',properties=dict(summary=dict(type='string'),start=dict(type='string',description='含时区的ISO开始时间'),
            end=dict(type='string',description='含时区的ISO结束时间'),item_id=dict(type='string',description='已知来源事项ID，可空；不能按标题猜测'),
            timezone=dict(type='string',enum=[ZONE])),required=['summary','start','end'],additionalProperties=False)),implementation=propose,read_only=True)


CREATE_GUIDANCE = ('用户要求创建或安排日程时，按北京时间结合前文确定标题、日期、开始时间及结束时间或时长。'
                   '只追问仍缺少或有歧义的信息，得到回答后直接调用 calendar_create。默认保存到 tebb 本地日历。'
                   '只有明确要求先看看、拟草稿或确认后再保存才使用 calendar_propose。'
                   '仅在保存回执成功后报告已创建；如指定飞书，另核对同步回执。')


def create_spec(workspace_path=None):
    from desk_companion.planning.scheduling import SchedulingService
    from desk_companion.planning.work_board import WorkBoardService

    draft = tool_spec(workspace_path)

    def create(arguments):
        labels = {'summary': '日程内容', 'start': '开始日期和时间', 'end': '结束时间或时长'}
        missing = [label for key, label in labels.items() if not arguments.get(key)]
        if missing:
            return dict(ok=False, change_state='not_changed', state='needs_clarification',
                        missing=missing, error='请在当前对话补充' + '、'.join(missing) + '。')
        result = draft['implementation'](arguments)
        proposal = result['proposal']
        action = {key: proposal[key] for key in ('summary', 'start', 'end', 'item_id')}
        action.update(type='create', request_id=proposal['save_request_id'], local_id=proposal['id'])
        local = SchedulingService(WorkBoardService(path=workspace_path)).local
        receipt = local.change(action)
        if receipt.get('ok') and receipt.get('operation', {}).get('state') == 'saved':
            return dict(ok=True, change_state='committed', proposal=proposal, event=receipt['event'],
                        request_id=proposal['save_request_id'])
        return receipt

    return dict(type='function', function=dict(name='calendar_create', description=CREATE_GUIDANCE,
                parameters=draft['function']['parameters']), implementation=create, read_only=False)


def task_event(result,task_id,call_id):
    if not isinstance(result,dict)or result.get('ok')is not True or 'proposal'not in result:return None
    proposal=validate(result['proposal'],task_id=task_id)
    if result.get('change_state')=='committed':
        if (result.get('event') or {}).get('local_id')!=proposal['id']:return None
        proposal['saved']=True
    return dict(proposal=proposal,call_id=str(call_id))


def handoff_checks(receipts,task_id):
    """Validate the current tool's proposal, without inventing GUI/save facts."""
    from desk_companion.collaboration.feedback import check
    relevant=[r for r in receipts if r.get('tool')=='calendar_propose']
    if not relevant:return []
    try:
        proposals=[]
        for receipt in relevant:
            result=receipt.get('result')
            if (receipt.get('read_only')is not True or not isinstance(result,dict)
                    or result.get('ok')is not True or result.get('change_state')!='not_changed'):
                raise ValueError('缺少成功且未写入的提案工具回执。')
            proposal=validate(result.get('proposal'),task_id=task_id)
            proposals.append(dict(id=proposal['id'],save_request_id=proposal['save_request_id'],call_id=receipt['call_id']))
        contract=dict(kind=KIND,stage='awaiting_user_confirmation',proposals=proposals,ui_observed=False,
            scope='仅证明本工具生成合法且绑定原任务的提案；没有证明GUI已打开、用户已保存或全局从未发生其他写入。')
        return [check('calendar_proposal_handoff','artifact','pass','提案字段、任务归属与稳定保存编号已核对；用户可下一步打开草稿确认。',delivery_contract=contract)]
    except (ValueError,KeyError,TypeError)as exc:
        return [check('calendar_proposal_handoff','artifact','fail',str(exc))]


def proposal_task(task_id):
    """Read the original proposal event from desktop or collaboration task history."""
    from desk_companion.infrastructure.paths import data_root
    from desk_companion.collaboration.store import workspace_path
    from desk_companion.observability.usage_store import read_rows

    collaboration = workspace_path().parent
    paths = (data_root() / 'memory' / 'tasks.sqlite3',
             collaboration / 'work' / 'tasks.sqlite3', collaboration / 'chat' / 'tasks.sqlite3')
    for path in paths:
        rows = read_rows(path, 'SELECT data FROM events WHERE task=? AND kind=? ORDER BY seq', (task_id, KIND))
        if rows:
            return dict(id=task_id, events=[dict(kind=KIND, data=json.loads(row['data'])) for row in rows])
    return None


class CalendarProposalService:
    def __init__(self,board,scheduling,task_lookup):
        self.board=board;self.scheduling=scheduling;self.task_lookup=task_lookup

    def read(self,task_id,proposal_id):
        try:
            _identity(task_id);_identity(proposal_id)
            task=self.task_lookup(task_id)
            if not isinstance(task,dict)or task.get('id')!=task_id:raise ValueError('没有此提案来源任务。')
            proposal=None
            for event in task.get('events',[]):
                if not isinstance(event,dict)or event.get('kind')!=KIND:continue
                data=event.get('data');candidate=data.get('proposal')if isinstance(data,dict)else None
                if isinstance(candidate,dict)and candidate.get('id')==proposal_id:proposal=validate(candidate,task_id=task_id)
            if proposal is None:raise ValueError('原任务中没有可核实的结构化日程提案。')
            page=self.scheduling.local.load(request_id=proposal['save_request_id'])
            if not page.get('ok'):return dict(ok=False,state='unconfirmed',proposal=proposal,error='日程状态读取未确认，请核对原编号。')
            operation=page.get('operation')
            event=next((event for event in page['events']if event.get('local_id')==proposal['id']),None)
            if (operation and operation.get('state')!='saved')or(event and not operation):
                return dict(ok=False,state='unconfirmed',proposal=proposal,operation=operation,error='原保存回执尚未确认，请按原编号核对。')
            if event:return dict(ok=True,state='saved',proposal=proposal,event=copy.deepcopy(event))
            if operation:return dict(ok=True,state='consumed',proposal=proposal,operation=operation,notice='此提案已经保存过，当前安排已移除；不会再次创建。')
            board=self.board.load()
            if not board.get('ok'):raise ValueError('当前事项状态读取未确认。')
            require_item(proposal['item_id'],board['items'])
            return dict(ok=True,state='proposed',proposal=proposal,
                notice='时段已经结束，请在草稿中调整后再保存。'if datetime.fromisoformat(proposal['end'])<=datetime.now(TZ)else'')
        except (ValueError,KeyError,TypeError,RuntimeError)as exc:return dict(ok=False,state='blocked',error=str(exc))
