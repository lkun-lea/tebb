"""Local lexical routing over the definitions authorized for one run."""
import math
import re
import unicodedata
from collections import Counter

# Intent vocabulary, indexed only when the corresponding tool is available.
ALIASES = {
    'build_chart': ('流程图', '关系图', '时序图', '柱状图', '折线图', '画图', 'flowchart'),
    'get_weather': ('天气预报', '要带伞', '会不会下雨'),
    'get_forecast': ('天气预报', '要带伞', '会不会下雨'),
    'workspace_list': ('项目结构', '项目架构', '源码结构', '浏览目录', '列出目录', '目录结构', '列出文件', '文件夹里有什么', '文件夹下有什么'),
    'workspace_read': ('读取文件', '查看文件内容', '读源码'),
    'workspace_search': ('搜索代码', '搜索文件内容', '查找代码'),
    'github_recent': ('最近提交', '仓库最近改了什么'),
    'github_roadmap': ('项目路线图', '仓库下一步'),
    'calendar_query': ('查日程', '日程安排', '什么时候有空'),
    'get_today_agenda': ('今天的安排', '今日安排'),
    'get_open_tasks': ('待办事项', '未完成的任务'),
    'web_search': ('网上查找', '联网搜索', '搜网页', '网页搜索', '网络搜索', '网络检索', '互联网搜索', '搜索引擎', 'web search'),
    'read_video_transcript': ('视频字幕', '提取字幕'),
    'save_video_summary': ('保存视频笔记',),
    'capability_save': ('创建工具', '自定义工具'),
}
STOP = set('一个 什么 怎么 如何 一下 这个 那个 我想 希望 帮我 可以 是否 请问 需要 进行 用户 必须 用于 工具 使用 然后 对应 当前 的是 不是'.split())


def normalize(value):
    return unicodedata.normalize('NFKC', value).casefold().strip()


def terms(value):
    words = set(re.findall(r'[a-z0-9]+', value))
    for run in re.findall(r'[\u3400-\u9fff]+', value):
        words.update(run[i:i+2] for i in range(len(run)-1))
    return words - STOP


# Match an action together with its subject. A generic verb like “整理”
# alone does not identify a tool, and “再试试” requires conversation context.
INTENTS = {
    'web_search': (
        (('搜索', '查询', '寻找', '检索', '了解', '解读', '整理', '研究'),
         ('最新', '最近', '实时', '新闻', '资讯', '前沿', '相关信息', '互联网', '在线资料')),
    ),
    'workspace_list': (
        (('解读', '梳理', '了解', '研究', '分析', '查看'), ('架构', '源码', '实现', '代码库')),
    ),
    'calendar_query': (
        (('新建', '创建', '安排', '查询', '查看', '冲突', '空闲'), ('日程', '日历', '会议')),
    ),
    'calendar_propose': (
        (('新建', '创建', '添加'), ('日程', '会议')),
    ),
}


def matches_intent(name, query):
    return any(any(action in query for action in actions) and any(subject in query for subject in subjects)
               for actions, subjects in INTENTS.get(name, ()))


def local_project_request(text):
    text = normalize(text)
    remote = re.search(r'github|远[程端]|线上仓库|pull request|\b(?:pr|issues?)\b', text)
    return not remote and any(word in text for word in
                              ('项目', '仓库', '源码', '代码', '目录', '文件', '实现', '架构', 'repository', 'repo', 'codebase', 'workspace'))


class ToolRouter:
    def __init__(self, definitions):
        self.index = []
        self.frequency = Counter()
        for d in definitions:
            name = normalize(d['name'])
            aliases = ALIASES.get(name, ())
            text = normalize(' '.join((name, d['collection'], d['description'])))
            words = terms(text + ' ' + ' '.join(aliases))
            self.index.append((d, name, aliases, text, words))
            self.frequency.update(words)

    def search(self, query, *, prefer_workspace=False):
        query = normalize(query)
        if not query:
            return []
        if prefer_workspace:
            local = {name: d for d, name, *_ in self.index if name.startswith('workspace_')}
            mentioned = [local[n] for n in re.findall(r'\bworkspace_[a-z_]+\b',query) if n in local]
            if mentioned:
                return list({d['name']:d for d in mentioned}.values())[:3]
            intents = (
                ('workspace_read_symbol', ('符号', '行号', '行范围', '按行', '续读', 'read_symbol', 'line range')),
                ('workspace_list', ('列出目录', '列出文件', '列出工作区文件', '列出仓库文件', '目录结构', '项目结构', '代码结构', '仓库结构', '架构', 'list files', 'list directory', 'directory tree')),
                ('workspace_search', ('grep', 'search code', 'code search', '搜索代码', '代码搜索', '搜代码', '文件内搜索')),
                ('workspace_read', ('文件内容', '读文件', '读取文件', '读取工作区文件', '读取源码', '读源码', 'read file', 'read workspace', 'read source', 'readme')),
            )
            found = [local[name] for name, phrases in intents if name in local and any(p in query for p in phrases)]
            if found:
                return found[:3]
            if 'workspace_list' in local and re.search(r'github|仓库|repository|\brepo\b|源码|代码库|工作区|workspace', query):
                return [local['workspace_list']]
        exact = [d for d, name, _, _, _ in self.index if name == query]
        if exact:
            return exact
        aliases_exact = [d for d, _, aliases, _, _ in self.index if query in aliases]
        if aliases_exact:
            return aliases_exact[:3]
        tokens = terms(query)
        ranked = []
        for d, name, aliases, text, words in self.index:
            common = tokens & words
            alias = any(a in query for a in aliases)
            intent = matches_intent(name, query)
            phrase = len(query) >= 2 and query in text
            # A lone incidental bigram in a sentence is weak evidence.
            if not (alias or intent or phrase or len(common) >= 2):
                continue
            score = sum(math.log1p(len(self.index) / self.frequency[w]) for w in sorted(common))
            score += 12 * alias + 12 * intent + 4 * phrase + 4 * (query in name)
            ranked.append((score, name, d))
        ranked.sort(key=lambda row: (-row[0], row[1]))
        return [d for _, _, d in ranked[:3]]


def search_receipt(found):
    tools = []
    for d in found:
        sentence = re.split(r'[。；;\n]', d['description'].strip(), maxsplit=1)[0]
        summary = sentence if len(sentence) <= 42 else sentence[:41] + '…'
        tools.append(dict(name=d['name'], description=summary))
    return dict(ok=True, tools=tools)
