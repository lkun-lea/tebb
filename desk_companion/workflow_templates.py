"""Editable examples without credentials, implicit schedules or publication."""


def templates():
    def node(ident,kind,config,x=300,y=0):return dict(id=ident,kind=kind,config=config,position=dict(x=x,y=y))
    def example(ident,name,description,steps):
        nodes=[node('trigger','trigger',dict(text=''),0,0),*steps]
        return dict(id=ident,name=name,description=description,graph=dict(nodes=nodes,edges=[dict(source=a['id'],target=b['id'],branch='') for a,b in zip(nodes,nodes[1:])]))
    return [
        example('tech-news','大厂开源与技术动向','核实官方来源→整理5条报告。复用现有核实规则；不自动生成海报或发布。可追加独立文档、表格或群消息节点。',[
            node('sources','news_sources',dict(topics='AI agent 开源项目\n大厂模型 推理 工具',lookback_days=3,source_limit=8)),
            node('report','news_report',dict(candidates='{{sources.candidates}}',day='{{sources.day}}'),600)]),
        example('video-notes','视频学习笔记','触发输入填写YouTube/Bilibili视频链接；只基于实际取得字幕，明确完整性，不自动归档。',[
            node('video','video',dict(url='{{trigger.text}}')),
            node('note','ai',dict(prompt='根据以下实际字幕整理学习笔记，保留时间点，区分作者观点与分析；完整字幕状态为 {{video.complete}}，false时必须说明覆盖缺口。\n标题：{{video.title}}\n来源：{{video.url}}\n{{video.text}}',model_id=''),600)]),
        example('feishu-document','飞书文档发布','触发输入作为正文；保存后逐步检查，明确确认目标后才创建文档。',[
            node('document','document',dict(title='自动化笔记',content='{{trigger.text}}',parent_token='',profile=''))]),
        example('feishu-message','飞书群消息','先填写固定群ID；模板不能直接运行，目标不会从AI回答自动取得。',[
            node('message','message',dict(chat_id='',text='{{trigger.text}}',profile=''))]),
        example('feishu-base','飞书多维表格','先填写Base、表、文本字段和独立去重字段；不自动建表或改变字段。',[
            node('record','base',dict(base_token='',table_id='',fields={'内容':'{{trigger.text}}'},key_field='',profile=''))]),
    ]
