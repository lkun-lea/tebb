"""Default diagnostic export redaction. Stored originals remain owner-managed."""
import re
from urllib.parse import urlsplit,urlunsplit,parse_qsl,urlencode

SENSITIVE=re.compile(r'^(authorization|proxy-authorization|api[_-]?key|x-api-key|x-auth-token|x-goog-api-key|access[_-]?token|refresh[_-]?token|auth[_-]?token|session[_-]?token|token|password|client[_-]?secret|app[_-]?secret|cookie|set-cookie|private[_-]?key|signature|sig|x-amz-signature|x-goog-signature|x-goog-credential|AWSAccessKeyId|GoogleAccessId)$',re.I)


def redact(value,secrets=()):
    secrets=tuple(s for s in secrets if isinstance(s,str)and s)
    def text(value):
        for secret in secrets:
            if len(secret)>=8:value=value.replace(secret,'[redacted]')
            elif value==secret:value='[redacted]'
        value=re.sub(r'(?i)\bBearer\s+[^\s"\'<>]+','Bearer [redacted]',value)
        value=re.sub(r'\bsk-[A-Za-z0-9_-]{12,}','[redacted]',value)
        value=re.sub(r'(?i)(["\']?(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|client[_-]?secret|app[_-]?secret)["\']?\s*[:=]\s*["\']?)[^\s,"\'<>}{\[\]]+',r'\1[redacted]',value)
        def url(match):
            raw=match[0]
            try:
                parts=urlsplit(raw);query=parse_qsl(parts.query,keep_blank_values=True)
                signed=any(SENSITIVE.fullmatch(key)or key.lower().startswith(('x-amz-','x-goog-'))for key,_ in query)
                netloc=parts.netloc.rsplit('@',1)[-1]
                if not signed and netloc==parts.netloc:return raw
                return urlunsplit((parts.scheme,netloc,parts.path,urlencode([(k,'[redacted]'if signed else v)for k,v in query]),parts.fragment))
            except ValueError:return '[redacted-url]'
        return re.sub(r'https?://[^\s<>"\']+',url,value)
    def walk(item):
        if isinstance(item,str):return text(item)
        if isinstance(item,list):return [walk(v)for v in item]
        if isinstance(item,dict):return {k:'[redacted]'if SENSITIVE.fullmatch(str(k))and isinstance(v,(str,int,float))else walk(v)for k,v in item.items()}
        return item
    return walk(value)


def diagnostic_export(value):
    """Apply one credential policy to trace, batch and detailed-call responses."""
    import json
    from desk_companion.infrastructure.paths import data_root
    path=data_root()/'models.json'
    known=[]
    if path.is_file():
        try:known=[item.get('api_key','')for item in json.loads(path.read_text('utf-8')).get('items',[])]
        except (OSError,ValueError,TypeError,AttributeError):raise ValueError('脱敏配置暂不可读，未导出调用正文。')from None
    return redact(value,known)


def debug_detail(call_id,*,profile=None):
    from desk_companion.observability.agent_debug import detail
    result=diagnostic_export(detail(call_id,profile=profile))
    result['redacted']=True
    return result
