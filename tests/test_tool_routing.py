import unittest

from desk_companion.pi_runtime.tool_routing import ToolRouter, search_receipt


def tool(name, purpose):
    return dict(name=name, description=purpose, collection='示例')


class ToolRoutingTests(unittest.TestCase):
    def test_normalized_exact_name_wins_over_other_descriptions(self):
        calendar = tool('calendar_query', '查询日程。返回开始和结束时间')
        router = ToolRouter([tool('other', '配合 calendar_query 使用'), calendar])
        self.assertEqual(router.search(' ＣＡＬＥＮＤＡＲ＿ＱＵＥＲＹ '), [calendar])
        self.assertEqual(search_receipt([calendar])['tools'], [
            dict(name='calendar_query', description='查询日程')])

    def test_weather_alias_requires_an_authorized_weather_tool(self):
        weather = tool('get_forecast', '按位置和日期读取气象信息')
        self.assertEqual(ToolRouter([weather]).search('出门要带伞吗'), [weather])
        self.assertEqual(ToolRouter([tool('calendar_query', '读取日程')]).search('出门要带伞吗'), [])

    def test_ambiguous_results_are_bounded_and_stable(self):
        tools = [tool('item_'+str(i), '查看项目记录') for i in range(8)]
        self.assertEqual(ToolRouter(tools).search('项目'), tools[:3])
        self.assertEqual(ToolRouter(tools[::-1]).search('项目'), tools[:3])
        for query in ['', '   ', '不存在的火山', '？']:
            self.assertEqual(ToolRouter(tools).search(query), [])


    def test_action_and_domain_route_even_when_neither_is_a_tool_name(self):
        search = tool('web_search', '检索互联网')
        directory = tool('workspace_list', '列出授权目录')
        chart = tool('build_chart', '渲染图表')
        calendar = tool('calendar_query', '取得已有事件')
        router = ToolRouter([search, directory, chart, calendar])
        for query, target in [('帮我了解最近发生的新闻', search), ('梳理这套代码库', directory),
                              ('帮我画个折线图', chart), ('安排一个会议', calendar)]:
            self.assertIn(target, router.search(query))
        for query in ['再试一次', '帮我整理下', '我正在创建目录']:
            self.assertNotIn(search, router.search(query))


    def test_workspace_scope_uses_user_intent_even_if_search_mentions_github(self):
        from desk_companion.pi_runtime.tool_routing import local_project_request
        local = tool('workspace_list', '列出目录')
        remote = tool('github_repository', '浏览 GitHub 仓库')
        router = ToolRouter([local, remote])
        for query in ('仓库结构', 'github_repository'):
            self.assertEqual(router.search(query, prefer_workspace=local_project_request('解读仓库的实现')), [local])
        self.assertEqual(router.search('github_repository', prefer_workspace=local_project_request('查看 GitHub 仓库')), [remote])


    def test_source_queries_route_to_the_requested_operations(self):
        names = ('workspace_search', 'workspace_list', 'workspace_read', 'web_search')
        router = ToolRouter([tool(name, '搜索关键词') for name in names])
        for query, expected in [('读取工作区文件 列出目录', ['workspace_list','workspace_read']),
                                ('README.md', ['workspace_read']),
                                ('grep 搜索关键词', ['workspace_search']),
                                ('read file list directory search code', ['workspace_list','workspace_search','workspace_read'])]:
            self.assertEqual([d['name'] for d in router.search(query, prefer_workspace=True)], expected)

    def test_discovery_miss_requests_one_rephrase_and_resets_after_hit(self):
        import tempfile
        from pathlib import Path
        from desk_companion.observability.tool_monitor import ToolMonitor
        from desk_companion.pi_runtime.tool_loading import SEARCH, ToolLoading
        with tempfile.TemporaryDirectory() as tmp:
            loader = ToolLoading([dict(name='workspace_list', description='列出目录', parameters={})],
                                 session='example', store=ToolMonitor(Path(tmp)/'audit.db'), user_input='查看项目架构')
            def find(query):
                return loader.execute(SEARCH, {'query': query}, query)
            first = find('xyzzpq')
            self.assertEqual(first['tools'], [])
            self.assertIn('再搜一次', first['next_action'])
            self.assertIn('缺口', find('qzzzqq')['next_action'])
            self.assertEqual(find('列出目录')['tools'][0]['name'], 'workspace_list')
            self.assertIn('再搜一次', find('xzzzxx')['next_action'])


    def test_stable_discovery_keeps_wire_signatures_and_drops_previous_run_grants(self):
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from desk_companion.observability.tool_monitor import ToolMonitor
        from desk_companion.pi_runtime.tool_loading import ToolLoading, SEARCH, CALL
        specs=[dict(name=name,description=name,parameters={'type':'object'}) for name in ('one','two')]
        with TemporaryDirectory() as tmp:
            options=dict(store=ToolMonitor(Path(tmp)/'events.db'),session='test',stable=True)
            loader=ToolLoading(specs,**options)
            self.assertEqual([s['name'] for s in loader.specs()],[SEARCH])
            for name in ('one','two'):
                result=loader.execute(SEARCH,{'query':name},name)
                self.assertEqual(result['tools'][0]['parameters'],specs[0]['parameters'])
                self.assertEqual([s['name'] for s in loader.specs()],[SEARCH,CALL])
            self.assertEqual(ToolLoading(specs,**options).loaded,[])
