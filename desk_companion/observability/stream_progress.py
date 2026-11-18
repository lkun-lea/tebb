"""Count stream progress without retaining provider text or estimating tokens."""
import time
from desk_companion.observability.performance import HttpTiming
from desk_companion.observability.usage_store import number

COUNTERS={'frames','text_characters','reasoning_characters','tool_call_frames','tool_argument_characters'}
TIMES={'elapsed_ms','request_ms','headers_ms','first_frame_ms','last_frame_ms','first_text_ms','last_text_ms','first_reasoning_ms','last_reasoning_ms'}


def validate(value):
    if not isinstance(value,dict)or set(value)-COUNTERS-TIMES-{'version'}or type(value.get('version'))is not int or value.get('version')!=1:
        raise ValueError('流式进度只允许计时与计数元数据。')
    if not {'elapsed_ms','frames','text_characters','reasoning_characters','headers_ms','first_frame_ms','first_text_ms','first_reasoning_ms'}<=set(value)or number(value.get('elapsed_ms'))is None:
        raise ValueError('流式进度缺少必需测量字段。')
    for key,item in value.items():
        if key in COUNTERS and(type(item)is not int or item<0):raise ValueError('流式计数无效。')
        if key in TIMES and item is not None and number(item)is None:raise ValueError('流式计时无效。')
    for count,stamp in [('frames','last_frame_ms'),('text_characters','last_text_ms'),('reasoning_characters','last_reasoning_ms')]:
        if value[count]and number(value.get(stamp))is None:raise ValueError('非空流缺少最后活动测量。')


class StreamProgress:
    def __init__(self,clock=time.monotonic):
        self.timing=HttpTiming(clock);self.counters=dict.fromkeys(COUNTERS,0);self.last={}

    def event(self,kind,data):
        name={'model_request':'request','http_status':'headers','provider_frame':'frame','text_delta':'text','thinking_delta':'reasoning'}.get(kind)
        if not name or name in{'text','reasoning'}and(not isinstance(data,str)or not data):return
        if name in{'headers','request'}:self.timing.mark(name)
        else:
            self.timing.mark('first_'+name)
            self.last['last_'+name+'_ms']=round((self.timing.clock()-self.timing.start)*1000,2)
            self.counters[{'frame':'frames','text':'text_characters','reasoning':'reasoning_characters'}[name]]+=1 if name=='frame'else len(data)
            if name=='frame'and isinstance(data,dict):
                choices=data.get('choices');fragments=[]
                for choice in choices if isinstance(choices,list)else[]:
                    delta=choice.get('delta')if isinstance(choice,dict)else None
                    tools=delta.get('tool_calls')if isinstance(delta,dict)else None
                    if isinstance(tools,list):fragments.extend(t for t in tools if isinstance(t,dict))
                if fragments:
                    self.counters['tool_call_frames']+=1
                    for tool in fragments:
                        function=tool.get('function');arguments=function.get('arguments')if isinstance(function,dict)else None
                        if isinstance(arguments,str):self.counters['tool_argument_characters']+=len(arguments)

    def snapshot(self):
        value=self.timing.payload()
        return dict(version=1,elapsed_ms=value['total_ms'],**self.counters,**self.last,
            **{key+'_ms':value['marks'].get(key)for key in ('request','headers','first_frame','first_text','first_reasoning')})
