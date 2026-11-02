"""Bound feedback to its immutable owner, source and contract before dispatch."""
import hashlib
import json


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def check_plan(draft, review, plan):
    if plan['draft_sha256']!=digest(draft) or plan['source_review_sha256']!=digest(review):
        raise ValueError('验证计划来源不属于当前契约和审查')
    opinions=review['criteria']+review['omissions']
    expected={x['criterion_id'] for x in opinions}
    actual=[x['opinion_id'] for x in plan['items']]
    if set(actual)!=expected or len(actual)!=len(expected):
        raise ValueError('验证计划必须逐一落实原审查意见')
    criteria={x['id']for x in draft['criteria']}
    for item in plan['items']:
        if not item['criterion_ids'] or not set(item['criterion_ids'])<=criteria:
            raise ValueError('计划必须绑定现有验收条件，不创建新评分编号')


def supplement_delta(contract, original, report):
    """Extra opinions are facts to retain, not contract scores to preserve."""
    expected={c['id']for c in contract['criteria']}
    old=[c for c in (original or {}).get('checks',[]) if isinstance(c,dict)]
    new=[c for c in (report or {}).get('checks',[]) if isinstance(c,dict)]
    changes=[];conflicts=[];seen=set()
    for c in old:
        ident=c.get('criterion_id')
        if ident not in expected or ident in seen or c.get('status')not in {'pass','fail','unknown'}:continue
        seen.add(ident)
        if len({(x.get('status'),x.get('failure_type'))for x in old if x.get('criterion_id')==ident})>1:
            conflicts.append(ident)
            continue
        match=next((n for n in new if n.get('criterion_id')==ident),{})
        before={k:c.get(k)for k in ('status','failure_type')}
        after={k:match.get(k)for k in ('status','failure_type')}
        if before!=after:changes.append(dict(criterion_id=ident,before=before,after=after))
    return dict(valid_score_changes=changes,conflicting_scores=conflicts,extra_opinions=[c for c in old if c.get('criterion_id')not in expected],
                original_sha256=digest(original),supplement_sha256=digest(report))
