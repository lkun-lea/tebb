"""Run one native team against the frozen #208 project using the controller on PYTHONPATH."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import zipfile

from eval_native_development import trial
from desk_companion import model_catalog, model_network

BASE = '1494d1c52c07e419d55f79265d77d75807a4a342'
FIX = '88bf75853e7882567e8ab396c97e826098d4d594'
GOAL = """处理 tebb #208。项目工具可能返回 JSON 包装的 Flask 启动日志，包含换行、ANSI 控制序列、正常 URL、畸形 IPv6 或非法端口。坏 URL 不应中断来源登记或引用审阅，原始日志和未确认的外部操作必须保留。正常 HTTP(S)、合法 IPv6 和 Markdown 链接应正常提取，JSON 转义和控制字符不能成为地址的一部分。普通日志不能成为正文证据，未读取链接不能标记为已读取。请先运行最小失败样例，在输出中展示期望与实际，再实现修改并验证。已有回归入口 python3 -m unittest tests.test_web_sources。只做所需源码和本地测试。禁止联网查历史实现、提交、推送或外部业务写入。"""


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    tests = {name:git(args.repo,'show',sha+':tests/'+name+'.py').decode() for name,sha in
             [('test_tool_url_parsing',FIX),('test_web_sources',BASE)]}
    holdout = """import io, json, sys, types, unittest
rows = {}
class Result(unittest.TextTestResult):
    def startTest(self,t): rows[t.id()]=False; super().startTest(t)
    def addSuccess(self,t): rows[t.id()]=True; super().addSuccess(t)
for name,source in TESTS.items():
    m=types.ModuleType(name)
    sys.modules[name]=m
    exec(compile(source,name,'exec'),m.__dict__)
    unittest.TextTestRunner(stream=io.StringIO(),resultclass=Result).run(unittest.defaultTestLoader.loadTestsFromModule(m))
print(json.dumps(rows))
sys.exit(0 if len(rows)==12 and all(rows.values()) else 1)
""".replace('TESTS.items()',repr(tests)+'.items()')
    def seed(folder):
        with zipfile.ZipFile(io.BytesIO(git(args.repo,'archive','--format=zip',BASE))) as archive:
            archive.extractall(folder)

    cursors = {}
    def observe(service, started):
        with (out/'events.jsonl').open('a', encoding='utf-8') as stream:
            for name,manager in service.managers.items():
                with manager.db() as db:
                    for e in db.execute("SELECT seq,ts,task,kind,data FROM events WHERE seq>? AND kind IN ('tool_start','tool_end','file_change','verification') ORDER BY seq",(cursors.get(name,0),)):
                        json.dump(dict(seconds=round(e['ts']-started,2), task=e['task'],kind=e['kind'],data=json.loads(e['data'])),stream,ensure_ascii=False)
                        stream.write('\n')
                        cursors[name]=e['seq']

    result = trial('team',out,model_catalog.require_active(),model_network.load(),
                   seed=seed,goal=GOAL,holdout=holdout,observe=observe)
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    print(result['delivery'],result['checks'],flush=True)


if __name__=='__main__':
    main()
