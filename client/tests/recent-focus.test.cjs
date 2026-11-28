const test=require('node:test');
const assert=require('node:assert/strict');
const {recentFocus}=require('./load-client.cjs')('recent-focus.ts');
const now=Date.UTC(2026,10,29), stamp=now/1000;
const chat={conversations:[],projects:[],messages:[{sender:'user',created:stamp,text:'正在准备产品评审'}]};
const item={title:'产品评审议程',state:'doing',updated:stamp};
const notes=[{notes:[{question:'产品评审材料',saved:new Date(now).toISOString()}]}];
test('会话、更新中的事项和保留笔记均可独立提供近期关注',()=>{
 for(const sources of [[[],chat,[]],[[],null,[item]],[notes,null,[]]])assert.match(recentFocus(...sources,now)[0],/产品评审/);
});
test('三类记录围绕同一主题时只展示一次',()=>assert.deepEqual(recentFocus(notes,chat,[item],now),['产品评审']));
test('已完成、归档和超出时间范围的事项不形成当前关注',()=>assert.deepEqual(recentFocus([],null,[{...item,state:'done'},{...item,archived:true},{...item,updated:stamp-15*86400}],now),[]));
