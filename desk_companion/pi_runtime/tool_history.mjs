// Rebuild public Pi tool declarations at their owned loading receipts. These
// receipts never grant permission: only currently authorized matching versions
// can be replayed. Missing/compacted receipts get a current SDK declaration.
export function replayToolHistory(rows, messages, {catalog,versions,baseNames}) {
  const byName=new Map(catalog.map(tool=>[tool.name,tool]));
  const declaration=name=>{const tool=byName.get(name);return tool&&{name,description:tool.description,parameters:tool.parameters};};
  const base=baseNames.map(declaration).filter(Boolean),loaded=new Set(base.map(t=>t.name));
  messages[0].toolsAdded=base;
  const names=new Map(),result=[];
  for (let index=0;index<rows.length;index++) {
    const row=rows[index];
    result.push(messages[index]);
    for(const call of row.tool_calls||[])names.set(call.id,call.function.name);
    if(row.role!=='tool'||!['tebb_tools_search','tebb_tools_load'].includes(names.get(row.tool_call_id)))continue;
    let receipt;try{receipt=JSON.parse(row.content);}catch{continue;}
    if(receipt.ok!==true)continue;
    const isLoad=names.get(row.tool_call_id)==='tebb_tools_load';
    if(isLoad&&!Array.isArray(receipt.loaded))continue;
    const added=[];
    if(!loaded.has('tebb_tools_load') && byName.has('tebb_tools_load')){
      loaded.add('tebb_tools_load');added.push(declaration('tebb_tools_load'));
    }
    for(const name of isLoad ? receipt.loaded : []){
      if(typeof name!=='string'||loaded.has(name)||!versions[name]||receipt.versions?.[name]!==versions[name])continue;
      const tool=declaration(name);if(tool){loaded.add(name);added.push(tool);}
    }
    if(added.length)result.push({role:'system',content:'',timestamp:0,toolsAdded:added});
  }
  return result;
}
