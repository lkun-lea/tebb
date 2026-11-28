"""Map existing model identity/sampling/network policy to pinned Pi AI."""
from desk_companion.models import model_capacity, model_network
from desk_companion.models.model_generation import official_luna


def payload_for(item, sampling):
    endpoint=item['base_url'].rstrip('/')+'/chat/completions'
    capacity=model_capacity.for_call(item.get('id',''),item['model'],endpoint)
    wire={}
    if 'reasoning_effort' in sampling:wire['thinking']={'type':'enabled'}
    if item['model'].lower().startswith(('glm-4.7','glm-5')):
        wire['thinking']={**wire.get('thinking',{}),'clear_thinking':False}
        wire['tool_stream']=True
    return dict(model=dict(id=item['model'],name=item['model'],api='openai-completions',provider='tebb',
        baseUrl=item['base_url'],reasoning=True,input=['text'],contextWindow=capacity.get('window')or 0,maxTokens=0,
        cost=dict(input=0,output=0,cacheRead=0,cacheWrite=0),thinkingLevelMap={'max':'max'},
        compat=dict(supportsDeveloperRole=False,supportsStore=False,supportsUsageInStreaming=True,
                    supportsReasoningEffort=True,supportsMidConvoSystemMessages=True)),
        api_key=item['api_key'],network=model_network.pi_policy(),wire_options=wire,observe_provider=True,
        options={**({'reasoningEffort':sampling['reasoning_effort']}if 'reasoning_effort'in sampling else{}),
                 **({'temperature':sampling['temperature']}if 'temperature'in sampling else{}),
                 **({'samplingParams':{'top_p':sampling['top_p']}}if 'top_p'in sampling else{})})


def apply_chat_parameters(body, base_url):
    """Apply route-specific restrictions after the final tool set is known."""
    if not official_luna(body.get('model'), base_url):
        return
    body.pop('thinking', None)
    if body.get('tools'):
        body['reasoning_effort'] = 'none'
    elif body.get('reasoning_effort') != 'none':
        body.pop('temperature', None)
        body.pop('top_p', None)
