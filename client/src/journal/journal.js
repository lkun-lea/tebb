/* Windows 与 Android 的今日手记阅读器。宿主负责身份、来源校验和提交回执。 */
class TodayJournal {
  constructor(root, action, mode = 'desktop') {
    this.root = root;
    this.action = action;
    this.mode = mode;
    this.drafts = new Map();
    this.fingerprint = '';
  }
  update(data) {
    const fingerprint = JSON.stringify(data);
    if (fingerprint === this.fingerprint) return;
    this.fingerprint = fingerprint;
    this.data = data;
    const root = this.root;
    const editing = root.contains(document.activeElement) && document.activeElement.tagName === 'TEXTAREA';
    const selection = editing && [document.activeElement.selectionStart, document.activeElement.selectionEnd];
    const previousKey = this.activeKey;
    root.replaceChildren();
    root.className = 'journal';
    const make = (parent, tag, style, text) => {
      const node = document.createElement(tag);
      node.className = style;
      if (text !== undefined) node.textContent = text;
      parent.append(node);
      return node;
    };
    const button = globalThis.createJournalButton;
    const q = data.questions[0];
    const record = q || data.receipt;
    const stamp = t => t ? new Date(t*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit',hour12:false}) : '';
    const receivedToday = data.receipt && data.receipt.day === data.day;
    const state = q ? 'pending' : receivedToday ? 'received' : 'quiet';
    root.dataset.state = state;
    root.dataset.solo = String(Boolean(data.solo));
    const keys = new Set(data.questions.map(row => JSON.stringify([row.conversation,row.run,row.version])));
    for (const key of this.drafts.keys()) if (!keys.has(key)) this.drafts.delete(key);
    const main = make(root,'div','jr-page');
    const top = make(main,'nav','jr-nav');
    button(top,'主聊',()=>this.action({type:'chat'}));
    make(top,'strong','','今日');
    if(this.mode==='desktop') button(top,data.solo?'双栏':'独立阅读',()=>this.action({type:'layout'}));
    if(data.profiles) button(top,'个人资料',()=>this.action({type:'profiles'}));
    if(data.settings) button(top,'偏好',()=>this.action({type:'settings'})).classList.add('jr-prefs');
    const content = make(main,'div','jr-content');
    const head = make(content,'header','jr-head');
    make(head,'small','jr-date',new Date(data.day+'T12:00:00').toLocaleDateString('zh-CN',{month:'long',day:'numeric',weekday:'long'}));
    make(head,'h1','',state==='quiet'?'今天，慢一点。':(data.greeting || '你好')+(data.name?'，'+data.name:'。'));
    make(head,'p','',q?'有一件事，需要你定下来。':receivedToday?'原任务已经收到你的答复。':'今天还没有新的待答任务。');
    make(head,'span','jr-mascot').ariaHidden='true';
    const card = (label,title) => {
      const a=make(content,'article','jr-card');
      make(a,'small','jr-kicker',label);
      make(a,'h2','',title);
      return a;
    };
    if (data.notice) make(content,'p','jr-notice',data.notice).setAttribute('role','status');
    const open = () => this.action({type:'source',conversation:record.conversation,run:record.run});
    if(q) {
      this.activeKey = JSON.stringify([q.conversation,q.run,q.version]);
      const key = this.activeKey;
      const draft = this.drafts.get(key) || {choice:'', note:''};
      this.drafts.set(key,draft);
      const a=card('待答任务',q.prompt);
      make(a,'time','jr-stamp',stamp(q.asked));
      make(a,'p','jr-context','Windows 上的原任务正在等你的答复。');
      const choices=make(a,'div','jr-choices');
      const durations = q.choices || (/评审/.test(q.prompt) && /多少分钟|多长时间|多久|时长/.test(q.prompt) ? ['30 分钟','45 分钟','60 分钟'] : []);
      const chips=[];
      for(const value of durations){
        const chip=button(choices,value,()=>{
          draft.choice=draft.choice===value?'':value;
          for(const c of chips)c.setAttribute('aria-pressed',String(c.textContent===draft.choice));
          enable();
        }, 'choice');
        chip.setAttribute('aria-pressed',String(draft.choice===value));chips.push(chip);
      }
      const note=make(a,'textarea','jr-note');
      note.placeholder=durations.length?'自行填写时长，或补充说明…':'填写答复…';
      note.setAttribute('aria-label','自行补充');note.rows=2;note.maxLength=4000;note.value=draft.note;
      const actions=make(a,'div','jr-actions');
      const answer=()=>[draft.choice,draft.note.trim()].filter(Boolean).join('，');
      const send=button(actions,'回复原任务',()=>{
        if (send.disabled) return;
        send.disabled = true;
        Promise.resolve(this.action({type:'answer',conversation:q.conversation,run:q.run,version:q.version,text:answer()}))
          .finally(() => { if (send.isConnected) enable(); });
      } ,'primary');
      function enable(){send.disabled=!data.online || data.busy || !answer() || answer().length>4000}
      note.oninput=()=>{draft.note=note.value;enable()};enable();
      button(actions,'查看上下文',open);
      if(editing && previousKey===key){note.focus({preventScroll:true});note.setSelectionRange(...selection)}
      for(const other of data.questions.slice(1)){
        button(content,other.prompt,()=>this.action({type:'select',run:other.run,version:other.version}));
      }
    } else if(record) {
      const a=card(receivedToday?'任务回执':'上次的事',receivedToday?'Windows 收到了你的答复':record.title);
      make(a,'strong','jr-answer',record.answer + (record.truncated ? '…' : ''));
      make(a,'p','jr-context',record.day+'  '+stamp(record.accepted)+' · 原任务已接收');
      button(a,'打开原会话',open);
    }
    if(record && state!=='quiet'){
      const a=card('项目进展',q?'任务走到了确认这一步':'这轮答复如何回到电脑');
      const rail=make(a,'ol','jr-rail');
      for(const [label,time] of [['开始任务',record.created],['发来追问',record.asked],['收到答复',record.accepted]]){
        const item=make(rail,'li',label==='收到答复' && q?'is-pending':'');
        make(item,'b','',label);make(item,'small','',stamp(time)||(label==='收到答复'&&q?'等待中':''));
      }
    }
    if(record){
      const a=card('简报记录',record.title);
      button(a,'查看来源会话 ↗',open);
    }
    for(const section of data.sections || []){
      const a=card('今日手记',section.title);
      if(!section.rows.length)make(a,'p','jr-context',section.empty || '暂无符合偏好的记录。');
      for(const row of section.rows)button(a,row.title,()=>this.action({type:'source',conversation:row.conversation,run:row.source}));
    }
  }
}
globalThis.TodayJournal = TodayJournal;
