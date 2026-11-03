"""Bounded source navigation and revision-checked edits in a granted workspace."""
import ast
from difflib import get_close_matches
import hashlib
import io
import os
from pathlib import Path

from . import project_workspace as workspace

TEXT_SUFFIXES = {'.py', '.pyi', '.js', '.ts', '.jsx', '.tsx', '.rs', '.go', '.java',
                 '.kt', '.cs', '.c', '.cpp', '.h', '.html', '.css', '.vue', '.svelte',
                 '.md', '.json', '.yml', '.yaml', '.toml', '.sql', '.sh', '.ps1'}


def symbols(text):
    tree = ast.parse(text.removeprefix('\ufeff'))

    def walk(node, parents):
        for child in ast.iter_child_nodes(node):
            scope = parents
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                scope = (*parents, child.name)
                start = min([child.lineno, *(d.lineno for d in child.decorator_list)])
                yield '.'.join(scope), start, child.end_lineno, not isinstance(child,ast.ClassDef)
            yield from walk(child, scope)

    yield from walk(tree, ())


def search(root, relative, query, mode, *, config):
    if not isinstance(query, str) or not query.strip() or len(query)>200 or mode not in ('symbol','text'):
        raise ValueError('需要有效的搜索词和 symbol/text 模式')
    target,_ = workspace.resolve(root,relative,config)
    base,_ = workspace.resolve(root,'',config)
    if not target.exists():
        raise ValueError('搜索路径不存在')
    limited = False
    def paths():
        nonlocal limited
        if target.is_file():
            yield target
            return
        visited = 0
        for parent,dirs,files in os.walk(target,followlinks=False):
            visited += len(dirs)+len(files)
            if visited>10000:
                limited = True
                return
            allowed = []
            for name in sorted(dirs):
                try:
                    workspace.resolve(root,(Path(parent)/name).relative_to(base).as_posix(),config)
                except (OSError,ValueError):
                    continue
                allowed.append(name)
            dirs[:] = allowed
            yield from (Path(parent)/name for name in sorted(files))

    exact, partial = [], []
    hit_count = 0
    preview = {}
    count, size = 0, 0
    needle = query.casefold()
    for file in paths():
        if file.suffix.lower() not in ({'.py','.pyi'} if mode=='symbol' else TEXT_SUFFIXES):
            continue
        path = file.relative_to(base).as_posix()
        try:
            safe,_ = workspace.resolve(root,path,config)
            length = safe.stat().st_size
            if length>workspace.MAX_FILE or not safe.is_file():
                continue
            if count>=2000 or size+length>24*workspace.MAX_FILE:
                limited = True
                break
            count += 1
            size += length
            with safe.open('rb') as stream:
                raw = stream.read(workspace.MAX_FILE+1)
            if len(raw)>workspace.MAX_FILE or b'\0' in raw:
                continue
            text = raw.decode('utf-8')
            if mode=='symbol':
                single_function = None
                for name,start,end,is_function in symbols(text):
                    if needle in name.casefold():
                        hit_count += 1
                        group = exact if needle in (name.casefold(),name.split('.')[-1].casefold()) else partial
                        if file==target and is_function and query in (name,name.split('.')[-1]):
                            single_function = (start,end)
                        if len(group)<25:
                            group.append(dict(path=path,symbol=name,start_line=start,end_line=end))
                        else:
                            limited = True
                if single_function and len(exact)==1:
                    try:
                        preview = _page(path,hashlib.sha256(raw).hexdigest(),list(io.StringIO(text,newline='')),*single_function)
                    except ValueError as exc:
                        preview = dict(preview_error=str(exc))
            else:
                for line_no,line in enumerate(io.StringIO(text,newline=''),1):
                    pos = line.casefold().find(needle)
                    if pos>=0:
                        hit_count += 1
                        partial.append(dict(path=path,start_line=line_no,text=line[max(0,pos-60):pos+140]))
                        if len(partial)>25:
                            break
        except (OSError,ValueError,SyntaxError,RecursionError):
            continue
        if mode=='text' and len(partial)>25:
            break
    hits = exact+partial
    return dict(ok=True,matches=hits[:25],hit_count=hit_count,limited=limited or len(hits)>25,**preview)


def read_symbol(root, relative, symbol=None, start_line=None, end_line=None, *, config):
    doc = workspace.read(root,relative,config,utf8_only=True)
    text = doc['text']
    # Python line coordinates only count CR/LF; form feed can occur in legal source.
    lines = list(io.StringIO(text,newline=''))
    first,last = 1,len(lines)
    if symbol:
        rows = [(name,start,end) for name,start,end,_ in symbols(text)]
        matches = [r for r in rows if r[0]==symbol] or [r for r in rows if r[0].split('.')[-1]==symbol]
        if len(matches)!=1:
            names = get_close_matches(symbol,[r[0] for r in rows],n=5,cutoff=0.35)
            choices = matches or [row for row in rows if row[0] in names] or rows
            hints = '；'.join(f'{name[:90]} ({a}–{b})' for name,a,b in choices[:5])
            raise ValueError(f'符号不存在或不唯一。可用限定名及行号：{hints or "无定义"}。'
                             f'也可省略 symbol，传 start_line/end_line（文件共 {last} 行）。')
        _,first,last = matches[0]
    elif start_line is None:
        raise ValueError('需要符号名或起始行号')
    start = first if start_line is None else start_line
    end = last if end_line is None else end_line
    if type(start) is not int or type(end) is not int or not first<=start<=end<=last:
        raise ValueError('行号超出范围')
    return dict(ok=True,**_page(relative,doc['revision'],lines,start,end))


def _page(relative,revision,lines,start,end):
    stop, chars = start-1, 0
    for line in lines[start-1:min(end,start+119)]:
        if chars+len(line)>12000:
            break
        chars += len(line)
        stop += 1
    if stop<start:
        raise ValueError('单行超过片段上限，请使用完整文件读取')
    return dict(path=relative,revision=revision,start_line=start,end_line=stop,
                next_line=stop+1 if stop<end else None,text=''.join(lines[start-1:stop]))


def patch(relative, old, new, revision, *, config, locked=False):
    if not isinstance(old,str) or not old or not isinstance(new,str) or old==new:
        raise ValueError('提供非空唯一原文和不同的替换文本')
    doc = workspace.read('main',relative,config,utf8_only=True)
    if not doc['editable'] or doc['kind']!='text':
        raise ValueError('仅可修改授权主目录的 UTF-8 文本')
    if doc['revision']!=revision:
        raise ValueError('文件版本已变化，请重新读取')
    text = doc['text']
    pos = text.find(old)
    if pos<0 or text.find(old,pos+1)>=0:
        raise ValueError('原文未找到或不唯一，请重新读取并提供上下文')
    return workspace.write(relative,text[:pos]+new+text[pos+len(old):],revision,config=config,locked=locked)
