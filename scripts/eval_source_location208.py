"""Paired, offline source-location and patch replay on the frozen #208 file."""
import json
import os
from collections import Counter
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

from desk_companion import project_workspace, workspace_source
BASE = '1494d1c52c07e419d55f79265d77d75807a4a342'


# Independently labelled definition lines in the frozen file, including nested methods.
DEFINITIONS = {
    'urls':24, 'url_key':38, 'public_url':43, '_resolved_url':47, '_addresses':62,
    'PageText.__init__':75, 'PageText.handle_starttag':81, 'PageText.handle_endtag':91,
    'PageText.handle_data':98, 'PageText.content':105, 'PageResponse.__init__':112,
    'PageResponse.__getattr__':114, 'PageResponse.__enter__':115, 'PageResponse.__exit__':116,
    'PageResponse.close':117, '_open':121, '_open.PinnedConnection.connect':136,
    'fetch_page':167, '_fetch_page':181, 'search_ledger':239, 'evidence_sources':246,
    'source_catalog':254, 'render_citations':278, 'render_citations.render':284,
    'render_citations.prose':292, 'render_citations.prose.replace':293, 'check_citations':303,
}
# Target line + original snippet. Some repeat in another function, some are unique.
EDITS = [
    ('urls',35,'return out'), ('url_key',39,'p = urlsplit(url)'),
    ('_resolved_url',50,'p = urlsplit(url)'), ('urls',27,'piece=[];depth=0'),
    ('public_url',44,'return _resolved_url'), ('PageText.__init__',79,'self.links=[]'),
    ('PageResponse.__init__',113,'self.response=response'),
    ('PageText.handle_data',99,'if self.skip: return'),
]


def run():
    repo = Path(__file__).resolve().parents[1]
    raw = subprocess.check_output(['git','-C',str(repo),'show',BASE+':desk_companion/web_sources.py'])
    with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, DESK_COMPANION_DATA_DIR=tmp):
        root = Path(tmp)/'project'
        root.mkdir()
        file = root/'web_sources.py'
        file.write_bytes(raw)
        cfg = project_workspace.save(str(root),[],True)['workspace']
        locations = []
        for name,line in DEFINITIONS.items():
            short = name.split('.')[-1]
            for arm,mode,query in [('text','text',short),('text_def','text','def '+short+'('),
                                   ('ast','symbol',short),('ast_qualified','symbol',name)]:
                result = workspace_source.search('main',file.name,query,mode,config=cfg)
                hits = [r['start_line'] for r in result['matches'] if mode=='text' or
                        (r['symbol']==name if arm=='ast_qualified' else r['symbol'].split('.')[-1]==short)]
                locations.append(dict(arm=arm,target=name,truth=line,first=hits[0] if hits else None,
                                      unique=hits==[line] and not result['limited']))
        edits = []
        for name,line,old in EDITS:
            lines = raw.splitlines(keepends=True)
            needle = old.encode()
            assert lines[line-1].count(needle)==1, (name,line)
            replacement = old+' '
            lines[line-1] = lines[line-1].replace(needle,replacement.encode())
            expected = b''.join(lines)
            for arm,symbol in [('file',None),('function',name)]:
                file.write_bytes(raw)
                rev = project_workspace.read('main',file.name,config=cfg)['revision']
                try:
                    workspace_source.patch(file.name,old,replacement,rev,symbol=symbol,config=cfg)
                except ValueError as exc:
                    outcome = str(exc).split()[0] if file.read_bytes()==raw else 'wrong'
                else:
                    outcome = 'correct' if file.read_bytes()==expected else 'wrong'
                edits.append(dict(arm=arm,target=name,line=line,outcome=outcome))
    location_summary = {}
    for arm in ('text','text_def','ast','ast_qualified'):
        cases = [row for row in locations if row['arm']==arm]
        location_summary[arm] = dict(total=len(cases), first_correct=sum(row['first']==row['truth'] for row in cases),
                                     unique_correct=sum(row['unique'] for row in cases))
    edit_summary = {arm:Counter(row['outcome'] for row in edits if row['arm']==arm)
                    for arm in ('file','function')}
    return dict(base=BASE,location_summary=location_summary,edit_summary=edit_summary,locations=locations,edits=edits)


if __name__=='__main__':
    print(json.dumps(run(), indent=2))
