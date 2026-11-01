"""跨线程事实：一份 memory/facts.json。模型用工具写，人在记忆页写。

不做向量库，不从对话里再抽一次。对话窗口仍在 memory.py。
"""
from __future__ import annotations

import contextvars
import json
import copy
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

TZ = timezone(timedelta(hours=8))
FACT_LIMIT = 30
FACT_MAX = 80
QUOTE_MAX = 200
WRITERS = ("user", "model")
BROKEN = (
    "memory/facts.json 坏了，这一轮不能开口。"
    "恢复：删掉或修好 desk-companion/memory/facts.json。"
)

from .resource_lock import ResourceLock
_LOCK = ResourceLock("facts")
_TURN_USER: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "desk_fact_user", default=None
)


def facts_path() -> Path:
    from .memory import memory_path

    return memory_path().parent / "facts.json"


@contextmanager
def bind_turn_user(text: str | None):
    """这一轮用来核对原话的用户消息。时钟前缀和技能正文不要绑进来。"""
    token = _TURN_USER.set(text)
    try:
        yield
    finally:
        _TURN_USER.reset(token)


def read_facts() -> list[dict]:
    """缺文件是空列表。结构坏了抛 RuntimeError。"""
    with _LOCK:
        return [dict(item) for item in _read_unlocked()]


def facts_prompt() -> str:
    """拼进系统提示。空清单也要写明：嘴上说记住了不算。"""
    from .memory_selection import select
    items = select()['selected']
    lines = [
        "当前作用域生效的记忆在 memory/facts.json。记忆不授予工具或外部操作权限。"
        "remember_fact返回「已记下」才生效；forget_fact返回「已停止后续使用」仅代表停止选择，不能声称全面遗忘。"
        "嘴上说记住了不算。日程、仓库数量、工具结果不要记。",
    ]
    if not items:
        lines.append("当前没有事实。")
    else:
        lines.append("已有事实：")
        for item in items:
            lines.append(f"- {item['text']}")
    return "\n".join(lines)


def remember_fact(args: dict) -> str:
    """工具：原话对不上、空句、重复、超长、写满，都不落盘。"""
    try:
        if not isinstance(args, dict):
            return _remember_fail("参数不是对象")
        text = args.get("text")
        quote = args.get("quote")
        if type(text) is not str or type(quote) is not str:
            return _remember_fail("事实和原话必须是字符串")
        user = _TURN_USER.get()
        if type(user) is not str or not user.strip():
            return _remember_fail("这一轮没有用户消息，不能记")
        problem = _fact_problem(text)
        if problem:
            return _remember_fail(problem)
        quote_text = quote.strip()
        if not quote_text:
            return _remember_fail("没有给出依据的用户原话")
        if len(quote_text) > QUOTE_MAX:
            return _remember_fail(f"依据的原话超过 {QUOTE_MAX} 字")
        if quote_text not in user:
            return _remember_fail("依据的原话不在这一轮用户消息里")
        fact = text.strip()
        from .memory_selection import tool_scope
        scope, owner = tool_scope()
        if args.get('scope'):
            from .memory_selection import current_scope
            scope=args['scope']
            if scope not in {'user','project','partner','conversation'}:
                return _remember_fail('作用域无效')
            owner='' if scope=='user' else current_scope().get(scope,'')
            if scope!='user' and not owner:
                return _remember_fail('当前没有该作用域的归属')
        corrects=args.get('corrects')
        if corrects is not None:
            if not isinstance(corrects,dict) or not re.search(r'更正|纠正|改为|修改.{0,6}记忆|\bcorrect\b|\binstead\b',user,re.I):
                return _remember_fail('更正需要当前用户明确要求及准确旧编号与版本')
            from .memory_selection import current_scope
            from .agent_debug import metadata
            current=current_scope();origin=metadata()
            with _LOCK:
                old=next((i for i in _read_unlocked() if i['id']==corrects.get('id')),None)
                if old is None or old.get('scope','user')!='user' and current.get(old['scope'])!=old.get('owner'):
                    return _remember_fail('更正目标不属于当前范围')
                row=change(dict(type='save',id=old['id'],version=corrects.get('version'),operation=uuid.uuid4().hex,
                                text=fact,scope=old.get('scope','user'),owner=old.get('owner',''),key=old.get('key','')),
                           author='model',quote=quote_text,origin=dict(kind='user_quote',quote=quote_text,
                                conversation=current.get('conversation',''),task_id=origin.get('task_id',''),run_id=origin.get('collab_run','')))
            if row['state']!='active':
                return f"更正已保存，但同主题冲突未解决，尚未生效（id={row['id']} version={row['version']}）。"
            return f"已记下更正：{row['text']}（id={row['id']} version={row['version']} scope={row['scope']}）"
        with _LOCK:
            items = _read_unlocked()
            if any(item["text"] == fact and item.get('scope','user') == scope and item.get('owner','') == owner for item in items):
                return _remember_fail("这句话已经在事实里")
            if sum(i.get('scope','user')==scope and i.get('owner','')==owner for i in items) >= FACT_LIMIT:
                return _remember_fail(f"事实已经写满 {FACT_LIMIT} 条，先删一条再记")
            explicit = bool(re.search(r'记住|记下|保存.{0,8}(偏好|记忆)|\bremember\b', user, re.I)) and not bool(re.search(r'(不要|别|不用|do not|don.t).{0,4}(记住|记下|remember)',user,re.I))
            from .memory_selection import current_scope
            from .agent_debug import metadata
            origin=metadata();current=current_scope()
            ident=uuid.uuid4().hex
            items.append(
                {
                    "id": ident,
                    "text": fact,
                    "writer": "model",
                    "quote": quote_text,
                    "updated": _now(),
                    "scope": scope, "owner": owner, "version": 1,
                    "state": "active" if explicit else "candidate",
                    "source": {"kind": "user_quote", "quote": quote_text,"conversation":current.get('conversation',''),
                               "task_id":origin.get('task_id',''),"run_id":origin.get('collab_run','')},
                    "versions": [], "expires": "", "key": "",
                }
            )
            _write_unlocked(items)
        return f"已记下：{fact}（id={ident} version=1 scope={scope}）" if explicit else f"已保存待确认候选：{fact}（id={ident}）；尚未生效，不要说已记住。"
    except Exception as exc:
        return _remember_fail(str(exc))


def forget_fact(args: dict) -> str:
    """Stop selection by exact identity/version; never promise complete erasure."""
    try:
        if not isinstance(args, dict):
            return _forget_fail("参数不是对象")
        user=_TURN_USER.get() or ''
        if not re.search(r'忘|停止使用|撤回|别记|删除.{0,8}(记忆|偏好)|\bforget\b|remove.{0,8}(memory|fact)',user,re.I):
            return _forget_fail('这一轮没有明确停止使用记忆的要求')
        ident=args.get('id');version=args.get('version')
        if not isinstance(ident,str) or type(version)is not int:
            return _forget_fail('需要已有记忆的准确id与version')
        with _LOCK:
            items = _read_unlocked()
            from .memory_selection import current_scope
            scope=current_scope()
            item=next((i for i in items if i['id']==ident),None)
            if item is None or item.get('scope','user')!='user' and scope.get(item['scope'])!=item.get('owner'):
                return _forget_fail('没有当前范围内的这条记忆')
            if item.get('version',1)!=version:
                return _forget_fail('记忆版本已变化，请重新核对')
            previous=copy.deepcopy(item);previous.pop('versions',None)
            item['versions']=[*item.get('versions',[]),previous]
            item.update(state='revoked',version=version+1,updated=_now())
            _write_unlocked(items)
        return f"已停止后续使用：{item['text']}（id={ident} version={version+1}）。原聊天、摘要或调用快照可能仍含原文，不代表全面清理。"
    except Exception as exc:
        return _forget_fail(str(exc))


def add_user_fact(text: str) -> None:
    """记忆页新增。失败抛出原因，不写盘。"""
    problem = _fact_problem(text)
    if problem:
        raise RuntimeError(problem + "。")
    fact = text.strip()
    with _LOCK:
        items = _read_unlocked()
        if any(item["text"] == fact for item in items):
            raise RuntimeError("这句话已经在事实里。")
        if len(items) >= FACT_LIMIT:
            raise RuntimeError(f"事实已经写满 {FACT_LIMIT} 条，先删一条再记。")
        items.append(
            {
                "id": uuid.uuid4().hex,
                "text": fact,
                "writer": "user",
                "quote": "",
                "updated": _now(),
            }
        )
        _write_unlocked(items)


def update_user_fact(fact_id: str, text: str) -> None:
    """人改一句。句子变了就把来源改成你，并清掉依据原话。"""
    if type(fact_id) is not str or not fact_id.strip():
        raise RuntimeError("没有这条事实。")
    problem = _fact_problem(text)
    if problem:
        raise RuntimeError(problem + "。")
    fact = text.strip()
    with _LOCK:
        items = _read_unlocked()
        idx = _find_id(items, fact_id.strip())
        if items[idx]["text"] == fact:
            return
        if any(item["text"] == fact for i, item in enumerate(items) if i != idx):
            raise RuntimeError("这句话已经在事实里。")
        previous = copy.deepcopy(items[idx])
        previous.pop('versions', None)
        items[idx]["text"] = fact
        items[idx]["writer"] = "user"
        items[idx]['source']={'kind':'manual_edit','previous_version':previous.get('version',1)}
        items[idx]['state']='active'
        items[idx]["quote"] = ""
        items[idx]["updated"] = _now()
        items[idx]["version"] = items[idx].get("version", 1) + 1
        items[idx]["versions"] = [*items[idx].get("versions", []), previous]
        _write_unlocked(items)


def delete_user_fact(fact_id: str) -> None:
    if type(fact_id) is not str or not fact_id.strip():
        raise RuntimeError("没有这条事实。")
    with _LOCK:
        items = _read_unlocked()
        kept = [item for item in items if item["id"] != fact_id.strip()]
        if len(kept) == len(items):
            raise RuntimeError("没有这条事实。")
        _write_unlocked(kept)


REMEMBER_SPEC = {
    "func": remember_fact,
    "name": "remember_fact",
    "description": (
        "用户要求记住时调用；没有明确记住要求时仅生成待确认候选，不得声称已经生效。默认当前会话；scope可指定用户明确要求的user/project/partner/conversation，归属由后台核对。"
        "text 是一句不超过 80 字的事实。"
        "quote 必须是这一轮用户原话里的连续片段，不能是推断或工具结果。"
        "返回里没有「已记下」就不许说已经记住。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "一句事实，不超过 80 字"},
            "quote": {"type": "string", "description": "这一轮用户原话里的连续片段"},
            "scope": {"type":"string","enum":["user","project","partner","conversation"]},
            "corrects": {"type":"object","properties":{"id":{"type":"string"},"version":{"type":"integer"}},"required":["id","version"],"description":"仅在用户明确更正时，提供清单里的准确旧id和version；保留旧版本。"},
        },
        "required": ["text", "quote"],
    },
    "isReadOnly": False,
    "retry_max": 0,
}

FORGET_SPEC = {
    "func": forget_fact,
    "name": "forget_fact",
    "description": (
        "用户明确要求停止使用或忘记某条记忆时调用。id/version复制当前记忆清单或本轮保存回执。"
        "仅停止后续选择，原聊天、摘要与调用副本可能仍在；不得声称全面遗忘。"
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type":"string","description":"准确记忆编号"},
            "version": {"type":"integer","description":"已核对的当前版本"},
        },
        "required": ["id","version"],
    },
    "isReadOnly": False,
    "retry_max": 0,
}


def _remember_fail(reason: str) -> str:
    return f"{reason}，没有写入。不要说已经记住。"


def _forget_fail(reason: str) -> str:
    return f"{reason}，没有停止使用。不要说已经忘掉。"


def _fact_problem(text: str) -> str | None:
    if type(text) is not str:
        return "事实必须是字符串"
    fact = text.strip()
    if not fact:
        return "事实是空的"
    if len(fact) > FACT_MAX:
        return f"事实超过 {FACT_MAX} 字"
    return None


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def _find_id(items: list[dict], fact_id: str) -> int:
    for idx, item in enumerate(items):
        if item["id"] == fact_id:
            return idx
    raise RuntimeError("没有这条事实。")


def _read_unlocked() -> list[dict]:
    path = facts_path()
    if not path.exists():
        return []
    if not path.is_file():
        raise RuntimeError(BROKEN)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(BROKEN) from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("items"), list):
        raise RuntimeError(BROKEN)
    items: list[dict] = []
    seen_id: set[str] = set()
    seen_text: set[tuple] = set()
    for row in raw["items"]:
        item = _checked_item(row)
        text_key = (item.get('scope','user'), item.get('owner',''), item['text'])
        if item["id"] in seen_id or text_key in seen_text:
            raise RuntimeError(BROKEN)
        seen_id.add(item["id"])
        seen_text.add(text_key)
        items.append(item)
    if len(items) > 3000:
        raise RuntimeError(BROKEN)
    return items


def _checked_item(row: object) -> dict:
    if not isinstance(row, dict):
        raise RuntimeError(BROKEN)
    fact_id = row.get("id")
    text = row.get("text")
    writer = row.get("writer")
    quote = row.get("quote")
    updated = row.get("updated")
    if type(fact_id) is not str or not fact_id.strip():
        raise RuntimeError(BROKEN)
    if type(text) is not str or not text.strip() or text != text.strip() or len(text) > 2000:
        raise RuntimeError(BROKEN)
    if writer not in WRITERS:
        raise RuntimeError(BROKEN)
    if type(quote) is not str or len(quote) > QUOTE_MAX:
        raise RuntimeError(BROKEN)
    if writer == "model" and not quote.strip():
        raise RuntimeError(BROKEN)
    if writer == "user" and quote != quote.strip():
        raise RuntimeError(BROKEN)
    if type(updated) is not str or not updated.strip():
        raise RuntimeError(BROKEN)
    try:
        stamp = datetime.fromisoformat(updated)
    except ValueError as exc:
        raise RuntimeError(BROKEN) from exc
    if stamp.tzinfo is None:
        raise RuntimeError(BROKEN)
    result = {
        **copy.deepcopy(row),
        "id": fact_id,
        "text": text,
        "writer": writer,
        "quote": quote,
        "updated": updated,
    }
    # Existing original rows remain untouched on read. New metadata is part of
    # this same store, rather than a migrated copy or a second write path.
    for key in ('scope', 'owner', 'version', 'state', 'source', 'versions', 'expires', 'key', 'operation','operation_digest'):
        if key in row:
            result[key] = copy.deepcopy(row[key])
    if result.get('scope', 'user') not in {'user','project','partner','conversation'}:
        raise RuntimeError(BROKEN)
    if result.get('state', 'active') not in {'active','candidate','disabled','revoked','conflict'}:
        raise RuntimeError(BROKEN)
    if type(result.get('version', 1)) is not int or result.get('version', 1) < 1:
        raise RuntimeError(BROKEN)
    if result.get('scope','user') != 'user' and not isinstance(result.get('owner'), str):
        raise RuntimeError(BROKEN)
    if not isinstance(result.get('versions',[]),list) or not isinstance(result.get('source',{}),dict):
        raise RuntimeError(BROKEN)
    if result.get('expires'):
        try:
            if datetime.fromisoformat(result['expires']).tzinfo is None:
                raise ValueError('timezone')
        except (TypeError, ValueError) as exc:
            raise RuntimeError(BROKEN) from exc
    return result


def change(action: dict, *, origin=None, author='user', quote='') -> dict:
    """Version-checked source edits. A caller-supplied operation ID is idempotent."""
    if not isinstance(action, dict):
        raise ValueError('记忆修改须为对象。')
    ident, operation = action.get('id',''), action.get('operation','')
    if not isinstance(operation, str) or not re.fullmatch('[a-f0-9]{32}', operation):
        raise ValueError('需要新的操作编号。')
    with _LOCK:
        items = _read_unlocked()
        from .context_sources import digest
        action_digest=digest(action)
        found = next((i for i in items if i['id'] == ident), None) if ident else None
        prior = next((v for i in items for v in [i,*i.get('versions',[])] if v.get('operation') == operation), None)
        if prior:
            if prior.get('operation_digest')!=action_digest:
                raise ValueError('操作编号已被其他修改使用。')
            return copy.deepcopy(prior)
        if ident and found is None:
            raise ValueError('记忆已不存在，请重新读取。')
        if found and action.get('version') != found.get('version', 1):
            raise ValueError('记忆版本已变化，请重新读取；未覆盖修改。')
        kind = action.get('type', 'save')
        if kind not in {'save','disable','confirm','revoke','restore'}:
            raise ValueError('记忆操作无效。')
        if kind != 'save' and not found:
            raise ValueError('需要已有记忆编号。')
        row = copy.deepcopy(found) if found else dict(id=operation, versions=[], version=0, scope='user', owner='',
            writer='user', quote='', state='active', expires='', key='', source={'kind':'manual'})
        for key, value in dict(versions=[], version=1, scope='user', owner='', state='active', expires='', key='', source={'kind':'manual'}).items():
            row.setdefault(key,value)
        history = copy.deepcopy(row)
        history.pop('versions', None)
        if kind == 'save':
            text = action.get('text')
            if not isinstance(text,str) or not 1 <= len(text.strip()) <= 2000:
                raise ValueError('记忆正文须为1至2000字。')
            scope, owner = action.get('scope', row['scope']), action.get('owner', row['owner'])
            if scope not in {'user','project','partner','conversation'} or not isinstance(owner, str) or (scope != 'user' and not owner):
                raise ValueError('请指定有效作用域与归属。')
            expires = action.get('expires', row.get('expires',''))
            if expires and (not isinstance(expires,str) or datetime.fromisoformat(expires).tzinfo is None):
                raise ValueError('到期时间需要时区。')
            key = action.get('key', row.get('key',''))
            if not isinstance(key,str) or len(key)>100:
                raise ValueError('冲突主题须为不超过100字的文本。')
            row.update(text=text.strip(), scope=scope, owner='' if scope=='user' else owner, expires=expires,
                       key=key.strip(), writer=author, quote=quote, state='active',source={'kind':'manual_edit' if found else 'manual','previous_version':history.get('version') if found else None})
            if origin:row['source'].update(origin)
            if any(i['id'] != row['id'] and (i.get('scope','user'), i.get('owner',''), i['text']) == (row['scope'], row['owner'], row['text']) for i in items):
                raise ValueError('同一作用域已存在相同记忆。')
        else:
            row['state'] = {'disable':'disabled','confirm':'active','revoke':'revoked','restore':'active'}[kind]
        row.update(version=row['version']+1, updated=_now(), operation=operation,operation_digest=action_digest)
        if found:
            row['versions'].append(history)
            items[items.index(found)] = row
        else:
            if len(items)>=3000:
                raise ValueError('记忆数量达到3000条保护上限。')
            items.append(row)
        # Explicit corrections specify the exact prior versions being superseded.
        supersedes = action.get('supersedes', [])
        if not isinstance(supersedes,list):
            raise ValueError('更正目标无效。')
        for target in supersedes:
            old = next((i for i in items if i['id']==target.get('id')), None)
            if not old or old['id']==row['id'] or old.get('version',1)!=target.get('version') or (old.get('scope','user'),old.get('owner',''))!=(row['scope'],row['owner']):
                raise ValueError('更正目标或版本变化，请重新读取。')
            previous = copy.deepcopy(old); previous.pop('versions', None)
            old['versions'] = [*old.get('versions',[]), previous]
            old.update(state='revoked', version=old.get('version',1)+1, updated=_now())
        if row.get('key') and row['state']=='active':
            conflicts = [i for i in items if i['id']!=row['id'] and i.get('state','active') in {'active','conflict'} and
                         (i.get('scope','user'),i.get('owner',''),i.get('key')) == (row['scope'],row['owner'],row['key'])]
            if conflicts:
                row['state']='conflict'
                for old in conflicts:
                    if old.get('state','active') != 'conflict':
                        previous=copy.deepcopy(old); previous.pop('versions',None)
                        old['versions']=[*old.get('versions',[]),previous]
                        old.update(state='conflict',version=old.get('version',1)+1,updated=_now())
        _write_unlocked(items)
        return copy.deepcopy(row)


def _write_unlocked(items: list[dict]) -> None:
    path = facts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"items": items}
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def erase_checked(ident,version):
    """Explicit source cleanup, only after stopping selection and checking version."""
    with _LOCK:
        items=_read_unlocked()
        item=next((i for i in items if i['id']==ident),None)
        if not item or item.get('version',1)!=version:
            raise ValueError('来源版本已变化，请重新预览清理范围。')
        if item.get('state','active') not in {'disabled','revoked'}:
            raise ValueError('请先停止使用，再清理来源及旧版本。')
        _write_unlocked([i for i in items if i['id']!=ident])
