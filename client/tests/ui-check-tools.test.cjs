const {test,assert,React,create,act,loader}=require('./component-fixture.cjs');
test('visible preview action waits for the workspace and opens a synthetic quote through its public entry',()=>{
 let ready=false,changed,disconnected=0,quotes=[];
 global.document={body:{},querySelector:()=>ready?{}:null};
 global.MutationObserver=class{constructor(fn){changed=fn;}observe(){}disconnect(){disconnected++;}};
 const {UiCheckTools}=loader({'./side-workspace':{previewQuote:value=>quotes.push(value)}})('ui-check-tools');
 let view;act(()=>{view=create(React.createElement(UiCheckTools));});
 assert.equal(view.root.findByType('button').props.disabled,true);
 act(()=>{ready=true;changed();});assert.equal(view.root.findByType('button').props.disabled,false);assert.equal(disconnected,1);
 act(()=>view.root.findByType('button').props.onClick());assert.equal(quotes.length,1);assert.equal(quotes[0].title,'合成资料');assert.match(quotes[0].text,/https:\/\/example\.org/);
 act(()=>view.unmount());delete global.MutationObserver;delete global.document;
});
