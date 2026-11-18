// Official Pi owns the loop. Python owns model admission, tool authorization and receipts.
import { Agent } from '@earendil-works/pi-agent-core';
import { stream } from '@earendil-works/pi-ai/api/openai-completions';

const emptyUsage = { input:0, output:0, cacheRead:0, cacheWrite:0, totalTokens:0,
  cost:{ input:0, output:0, cacheRead:0, cacheWrite:0, total:0 } };
function history(rows, model) {
  const names = new Map();
  return rows.map(row => {
    if (row.role === 'system' || row.role === 'user') return { role:row.role, content:row.content, timestamp:0 };
    if (row.role === 'assistant') {
      const content = row.content ? [{ type:'text', text:row.content }] : [];
      if (row.reasoning_content) content.unshift({ type:'thinking', thinking:row.reasoning_content });
      for (const call of row.tool_calls || []) {
        names.set(call.id, call.function.name);
        content.push({ type:'toolCall', id:call.id, name:call.function.name, arguments:JSON.parse(call.function.arguments) });
      }
      return { role:'assistant', content, api:model.api, provider:model.provider, model:model.id,
        usage:structuredClone(emptyUsage), stopReason:row.tool_calls?.length ? 'toolUse' : 'stop', timestamp:0 };
    }
    if (row.role === 'tool') return { role:'toolResult', toolCallId:row.tool_call_id,
      toolName:names.get(row.tool_call_id), content:[{ type:'text', text:row.content }], isError:false, timestamp:0 };
    throw new Error('Unsupported product history role');
  });
}

export async function runProductAgent({ id, data, model, common, ask, emit, active, usage }) {
  const tools=(data.tools || []).map(tool => ({ ...tool, label:tool.name,
    execute:async (callId,args) => {
      if (active.abort.signal.aborted) throw new Error('cancelled');
      const receipt=await ask(id,'tool_call',{ name:tool.name, call_id:callId, arguments:args });
      if (!receipt.ok || active.abort.signal.aborted) throw new Error('Product tool gate stopped');
      return { content:[{ type:'text', text:typeof receipt.result==='string' ? receipt.result : JSON.stringify(receipt.result) }],
        details:receipt.result };
    },
  }));
  const messages=history(data.messages,model);
  if (messages[0]?.role !== 'system') throw new Error('Missing product system message');
  messages[0].toolsAdded=tools.map(({ name,description,parameters })=>({ name,description,parameters }));
  const agent=new Agent({ initialState:{ model,messages,tools,thinkingLevel:data.thinking_level || 'low' },
    toolExecution:'sequential', streamFn:(current,context,options)=>stream(current,context,{ ...options,...common }),
  });
  active.agent=agent;
  agent.subscribe(async event => {
    if (event.type==='message_update') {
      const change=event.assistantMessageEvent;
      if (change.type==='text_delta' || change.type==='thinking_delta') emit(id,change.type,change.delta);
    }
    if (event.type==='message_end' && event.message.role==='assistant') {
      const message=structuredClone(event.message); delete message.errorMessage;
      // Await settlement before Pi can execute tools or start another model call.
      const receipt=await ask(id,'model_end',{ message,provider_usage:usage.raw });
      if (!receipt.ok || active.abort.signal.aborted) throw new Error('Model settlement stopped');
    }
    if (event.type==='tool_execution_end') emit(id,'tool_result',{ name:event.toolName,call_id:event.toolCallId,
      result:event.result,is_error:event.isError });
  });
  await agent.continue();
  return agent.state.messages.filter(row=>row.role==='assistant').at(-1);
}
