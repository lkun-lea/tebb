"""Bounded source navigation and revision-checked edits in a granted workspace."""
import ast
from collections import Counter
from difflib import get_close_matches
import hashlib
import io
import os
import re
from pathlib import Path

from desk_companion.projects import project_workspace as workspace

TEXT_SUFFIXES = {'.py', '.pyi', '.js', '.ts', '.jsx', '.tsx', '.rs', '.go', '.java',
                 '.kt', '.cs', '.c', '.cpp', '.h', '.html', '.css', '.vue', '.svelte',
                 '.md', '.json', '.yml', '.yaml', '.toml', '.sql', '.sh', '.ps1'}


TS_SUFFIXES = {'.ts', '.tsx', '.mts', '.cts'}
TS_DECLARATION = re.compile(
    r'^\s*(?:(?:export|default|declare|abstract|async)\s+)*'
    r'(?:function\s*\*?|class|interface|type|enum|namespace|const|let|var)\s+([$\w]+)'
)


def _declaration_doc(lines, index):
    """Return only a complete, directly preceding short JSDoc block."""
    if not index or not lines[index - 1].strip().endswith('*/'):
        return None
    for start in range(index - 1, max(-1, index - 10), -1):
        line = lines[start].strip()
        if line.startswith('/**'):
            body = ''.join(lines[start:index])
            if len(body) <= 440:
                return dict(start_line=start + 1, end_line=index, text=body)
            break
        if not line.startswith('*'):
            break
    return None


def typescript_declarations(text):
    """Line-oriented declaration candidates. No inferred body boundaries."""
    for number, line in enumerate(io.StringIO(text, newline=''), 1):
        match = TS_DECLARATION.match(line)
        if match:
            yield match.group(1), number, ' '.join(match.group().split())


SOURCE_REVIEW_GUIDE = (
    '常规仓库先按路径读取 README.md，不要把文件名或项目名当内容全仓搜索；入口缺失时再查目录。根据文档中实际列出的核心模块、职责与标识符，'
    '在该模块源码内定位代表性实现，并行读取有关文档和代码。解释运行循环时一次读齐循环入口、主体和出口。'
    '概览到此即可，不为扩写旁支再读其他客户端文档。依赖方向须有包清单或 import 逐边作证；未核实时只介绍各自职责。'
    '示例只说明一种用法。每个行为引用实际执行它的语句，独立片段分别给出完整路径和行号。'
)


def overview_kind(question):
    question = question.lower()
    if not any(term in question for term in ('架构', '解读', '概览', 'architecture', 'overview')):
        return ''
    if any(term in question for term in ('实现', '初始化', 'implementation', 'initialization')):
        return 'implementation'
    return 'architecture'


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
    # Call expressions and member accesses are text queries in TypeScript.
    # Preserve Python's qualified-name lookup in directories and Python files.
    requested_mode = mode
    if mode == 'symbol' and ('(' in query or (Path(relative).suffix.lower() in TS_SUFFIXES and '.' in query)):
        mode = 'text'
    target,_ = workspace.resolve(root,relative,config)
    base,_ = workspace.resolve(root,'',config)
    if not target.exists():
        raise ValueError('搜索路径不存在')
    limited = False
    skipped=Counter();stops=[]
    # For source queries, defer prose and fixtures until production code has had
    # a chance to fill the bounded result page. Explicit file scopes stay exact.
    code_query = mode == 'symbol' or bool(re.search(r'[(){};]|\b(?:while|for|class|def|function|import)\b|[a-z][A-Z]', query))
    secondary_dirs = {'docs', 'doc', 'tests', 'test', 'examples', 'fixtures', '__tests__'}

    def paths():
        nonlocal limited
        if target.is_file():
            yield target
            return
        deferred = []
        visited = 0
        for parent,dirs,files in os.walk(target,followlinks=False):
            visited += len(dirs)+len(files)
            if visited>10000:
                limited = True
                stops.append('directory_scan_limit')
                break
            allowed = []
            for name in sorted(dirs):
                try:
                    workspace.resolve(root,(Path(parent)/name).relative_to(base).as_posix(),config)
                except (OSError,ValueError):
                    skipped['unavailable_directory']+=1
                    continue
                allowed.append(name)
            dirs[:] = sorted(allowed, key=lambda d: d not in {'src', 'lib'}) if code_query else allowed
            parent_path = Path(parent)
            secondary = bool(secondary_dirs.intersection(parent_path.relative_to(target).parts))
            for name in sorted(files):
                file = parent_path / name
                if code_query and (secondary or file.suffix.lower() in {'.md', '.json', '.yaml', '.yml', '.toml'}):
                    deferred.append(file)
                else:
                    yield file
        yield from deferred

    exact, partial = [], []
    hit_count = 0
    preview = {}
    count, size = 0, 0
    needle = query.casefold()
    supported = ({'.py', '.pyi'} if mode == 'symbol' else TEXT_SUFFIXES) | TS_SUFFIXES
    for file in paths():
        if file.suffix.lower() not in supported:
            skipped['unsupported_type']+=1
            continue
        path = file.relative_to(base).as_posix()
        try:
            safe,_ = workspace.resolve(root,path,config)
            length = safe.stat().st_size
            if length>workspace.MAX_FILE or not safe.is_file():
                skipped['size_or_nonfile']+=1
                continue
            if count>=2000 or size+length>24*workspace.MAX_FILE:
                limited = True
                stops.append('file_scan_limit')
                break
            count += 1
            size += length
            with safe.open('rb') as stream:
                raw = stream.read(workspace.MAX_FILE+1)
            if len(raw)>workspace.MAX_FILE or b'\0' in raw:
                skipped['size_or_binary']+=1
                continue
            text = raw.decode('utf-8')
            if mode == 'symbol' and file.suffix.lower() in TS_SUFFIXES:
                source_lines = list(io.StringIO(text, newline=''))
                for name, number, declaration in typescript_declarations(text):
                    if needle not in name.casefold() and needle not in declaration.casefold():
                        continue
                    hit_count += 1
                    group = exact if needle == name.casefold() or declaration.casefold().endswith(' ' + needle) else partial
                    if len(group) < 25:
                        hit = dict(path=path, symbol=name, start_line=number, end_line=number)
                        if 'class ' in declaration:
                            doc = _declaration_doc(source_lines, number - 1)
                            if doc:
                                hit['declaration_doc'] = doc
                        group.append(hit)
                    else:
                        limited = True
                continue
            if mode=='symbol':
                definitions = symbols(text)
                if file==target:
                    definitions = list(definitions)
                for name,start,end,_ in definitions:
                    if needle in name.casefold():
                        hit_count += 1
                        group = exact if needle in (name.casefold(),name.split('.')[-1].casefold()) else partial
                        if len(group)<25:
                            group.append(dict(path=path,symbol=name,start_line=start,end_line=end))
                        else:
                            limited = True
            else:
                for line_no,line in enumerate(io.StringIO(text,newline=''),1):
                    pos = line.casefold().find(needle)
                    if pos>=0:
                        hit_count += 1
                        partial.append(dict(path=path,start_line=line_no,text=line[max(0,pos-60):pos+140]))
                        if len(partial)>25:
                            break
                definitions = ()
                if file==target and query.isidentifier() and file.suffix.lower() in {'.py','.pyi'}:
                    definitions = symbols(text)
            if file == target and mode == 'text' and not partial and file.suffix.lower() in TS_SUFFIXES:
                # A field and its getter may share a stem but be different symbols.
                # Keep the literal miss intact and offer line evidence from this file.
                parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', query).replace('_', ' ').split()
                if len(parts) > 1 and len(parts[0]) >= 4 and query.isidentifier():
                    stem = parts[0].casefold()
                    related = []
                    for line_no, line in enumerate(io.StringIO(text, newline=''), 1):
                        if stem in line.casefold() and not line.lstrip().startswith(('/', '*')):
                            related.append(dict(path=path, start_line=line_no, text=line.strip()[:180]))
                            if len(related) == 3:
                                break
                    if related:
                        preview['related_lines'] = related
            if file==target:
                matches = [row for row in definitions if needle in (row[0].casefold(),row[0].split('.')[-1].casefold())]
                if len(matches)==1:
                    name,start,end,is_function = matches[0]
                    if is_function and query in (name,name.split('.')[-1]):
                        try:
                            preview = dict(symbol=name, **_page(path,hashlib.sha256(raw).hexdigest(),list(io.StringIO(text,newline='')),start,end))
                        except ValueError as exc:
                            preview = dict(preview_error=str(exc))
        except UnicodeDecodeError:
            skipped['encoding']+=1
            continue
        except (SyntaxError,RecursionError):
            skipped['parser']+=1
            continue
        except (OSError,ValueError):
            skipped['unavailable_file']+=1
            continue
        if mode=='text' and len(partial)>25:
            break
    hits = exact+partial
    limited=limited or len(hits)>25
    if len(hits)>25 or hit_count>25:stops.append('result_limit')
    coverage=dict(scope='仅当前root/path下支持的文件类型和可读取编码',scanned_files=count,scanned_bytes=size,
        skipped=dict(skipped),stop_reasons=list(dict.fromkeys(stops)),complete=not limited and not skipped,
        hit_count_scope='observed_scan',next_action='缩小path或用限定名/行号读取；本次未命中不证明范围外不存在。')
    if requested_mode != mode:
        preview['effective_mode'] = mode
    if not hits:
        preview['reason'] = 'no_matches' if coverage['complete'] else 'incomplete_search'
    return dict(ok=True,matches=hits[:25],hit_count=hit_count,limited=limited,coverage=coverage,**preview)


def _numbered_excerpt(receipt, path):
    if 'start_line' not in receipt or not isinstance(receipt.get('text'), str):
        return receipt
    numbered = ''.join(f'{n}|{line}' for n, line in enumerate(
        io.StringIO(receipt['text'], newline=''), receipt['start_line']))
    view = {**{k: v for k, v in receipt.items() if k != 'text'}, 'numbered_text': numbered}
    if path and receipt.get('end_line'):
        view['citation'] = f"{path}:L{receipt['start_line']}-L{receipt['end_line']}"
    return view


def _cite_declarations(rows, default_path=None):
    return [
        {**row, 'declaration_doc': _numbered_excerpt(row['declaration_doc'], row.get('path', default_path))}
        if isinstance(row, dict) and row.get('declaration_doc') else row
        for row in rows
    ]


def overview_receipt(name, arguments, result, seen_locations, *, implementation=False):
    """Compact navigation metadata for overview answers while retaining source excerpts."""
    if not isinstance(result, dict) or not result.get('ok'):
        return result
    if name == 'workspace_list' and 'entries' in result:
        view = {key: value for key, value in result.items() if key != 'entries'}
        view['path'] = arguments.get('path') or '.'
        view['directories'] = [entry['name'] for entry in result['entries'] if entry['directory']]
        view['files'] = [entry['name'] for entry in result['entries'] if not entry['directory']]
        return view
    if name == 'workspace_search' and result.get('matches'):
        result = {**result, 'matches': _cite_declarations(result['matches']),
                  'next_action': '直接按命中 path 与行号读取；调用点按正文出现的标识符查找。'}
    if name == 'workspace_search' and len(result.get('matches', [])) > 6:
        return {**result, 'matches': result['matches'][:6], 'more_matches': True,
                'next_action': '已列出前六个候选；直接按相关源码的 path 与行号读取，多义时再缩小范围。'}
    if name == 'workspace_read_symbol':
        if implementation and result.get('initializer_excerpt'):
            result = {**result, 'initializer_excerpt': _numbered_excerpt(result['initializer_excerpt'], result.get('path'))}
        elif 'initializer_excerpt' in result:
            result = {k: v for k, v in result.items() if k != 'initializer_excerpt'}
        if 'start_line' in arguments and 'end_line' in arguments and 'locations' in result:
            result = {k:v for k,v in result.items() if k != 'locations'}
        result = _numbered_excerpt(result, result.get('path'))
        if result.get('closing_excerpt'):
            result['closing_excerpt'] = _numbered_excerpt(result['closing_excerpt'], result.get('path'))
    if name == 'workspace_read_symbol' and result.get('locations') and result.get('revision'):
        key = (arguments.get('root', 'main'), result['path'], result['revision'])
        if key in seen_locations:
            return {k: v for k, v in result.items() if k != 'locations'}
        seen_locations.add(key)
        result = {**result, 'locations': _cite_declarations(result['locations'], result['path'])}
    if name == 'workspace_read_symbol' and result.get('citation'):
        spans = [result['citation']]
        if result.get('closing_excerpt'):
            spans.append(result['closing_excerpt']['citation'])
        guidance = '作答时逐段引用：' + '、'.join(spans) + '。只概括这些证据支持的行为。'
        tail = result.get('closing_excerpt', result)
        exits = [line.split('|', 1)[0] for line in tail.get('numbered_text', '').splitlines()
                 if re.fullmatch(r'\d+\|\s*break;?\s*', line)]
        if exits:
            guidance += ' 解释 break 时引 ' + '、'.join(f"{result['path']}:L{n}" for n in exits)
            guidance += '；按缩进区分回合末仍在循环内的读取和退出循环后的读取。'
        initializer = result.get('initializer_excerpt', {})
        body = result.get('numbered_text', '') + initializer.get('numbered_text', '')
        if initializer:
            guidance += ' 初始化调用点对应的同文件函数原文见 ' + initializer['citation'] + '。'
        if re.search(r'\|\s*get \w+\(', body) and re.search(r'\|\s*set \w+\(', body):
            guidance += ' 答案逐项写明：初始化如何取得或复制数组，setter 如何赋值，getter 实际 return 哪个对象（原数组还是副本），并引函数体。'
        if Path(result['path']).suffix.lower() == '.md':
            guidance += ' 直接按文档已指明的核心包路径读包说明与代表性源码。CLI README 只在用户询问客户端或需要核实客户端行为时读取，不为扩写概览而读。只陈述文档列出的职责，不推导全仓依赖图。'
            if re.search(r'agent runtime|stateful agent', body, re.I):
                guidance += ' 对此运行时，直接读核心包 README，同时在其 src 内 text 搜 while。从外层循环命中行开始一次读 110 行及出口。'
            if implementation and re.search(r'stateful|state management|状态管理', body, re.I):
                guidance += ' 文档明确提到状态管理：在该模块源码并行定位状态初始化（符号词 State）及主控制流，读取初始化函数体与实际循环。'
        if exits:
            polls = re.findall(r'^([0-9]+)\|[^\n]*?\bawait\s+\w+\.(\w+)\??\.?(?=\()', tail['numbered_text'], re.M)
            if polls and tail.get('enclosing_loops'):
                for line, name in polls[-3:]:
                    enclosing = [loop for loop in tail['enclosing_loops']
                                 if loop['header_line'] < int(line) < loop['closing_brace_line']]
                    if enclosing:
                        loop = enclosing[-1]
                        guidance += f" L{line} 的 {name} 在 L{loop['header_line']} 循环体内，其右花括号在 L{loop['closing_brace_line']}。"
            if polls:
                guidance += ' 出口附近实际调用：' + '、'.join(f'{name} L{line}' for line, name in polls[-3:]) + '。'
            guidance += ' 总结本段时列出内层每轮末与内层退出后的两个读取动作，各给实际调用行；最后再给 break 行。'
            if not implementation:
                guidance += ' 若项目说明与这个核心实现已经回答架构问题，现在直接给最终答案。按原文解释控制流，省去重画循环的伪代码、客户端使用方式和推荐阅读清单。'
        result['next_action'] = guidance
    return result


def excerpt_for_question(result):
    """Keep the first 40 returned source lines and an accurate continuation cursor."""
    if not result.get('ok') or 'start_line' not in result or not isinstance(result.get('text'),str):
        return result
    lines = list(io.StringIO(result['text'], newline=''))
    if len(lines)<=40:
        return result
    end = result['start_line']+39
    return {**result, 'text':''.join(lines[:40]), 'end_line':end,'next_line':end+1}


def discovery_preview(result):
    """Give read-only agents locations before sending long file bodies."""
    text = result.get('text')
    if not isinstance(text, str) or len(text) <= 1800:
        return result
    import re
    lines = text.splitlines()
    anchors = []
    for line_no, line in enumerate(lines, 1):
        if re.match(r'^\s*(?:#{1,4} |(?:export (?:default )?)?(?:async )?(?:class|function|interface|def|fn|struct) )', line):
            anchors.append(dict(line=line_no, heading=line.strip()[:100]))
            if len(anchors) >= 12:
                break
    metadata = {k:v for k,v in result.items() if k!='text'}
    return dict(**metadata, line_count=len(lines), locations=anchors, preview_only=True,
                next_action='用 workspace_read_symbol 按 start_line/end_line 读关键段（约20行）；也可用 workspace_search 的 text 模式定位。')


def _resolve_symbol(text, symbol):
    rows = [(name,start,end) for name,start,end,_ in symbols(text)]
    matches = [r for r in rows if r[0]==symbol] or [r for r in rows if r[0].split('.')[-1]==symbol]
    if len(matches)==1:
        return matches[0]
    names = get_close_matches(symbol,[r[0] for r in rows],n=5,cutoff=0.35)
    choices = matches or [row for row in rows if row[0] in names] or rows
    hints = '；'.join(f'{name[:90]} ({a}–{b})' for name,a,b in choices[:5])
    raise ValueError(f'符号不存在或不唯一。可用限定名及行号：{hints or "无定义"}。可用行号重新读取。')


def read_symbol(root, relative, symbol=None, start_line=None, end_line=None, *, config, include_initializer=False):
    doc = workspace.read(root,relative,config,utf8_only=True)
    text = doc['text']
    # Python line coordinates only count CR/LF; form feed can occur in legal source.
    lines = list(io.StringIO(text,newline=''))
    first,last = 1,len(lines)
    if symbol:
        symbol,first,last = _resolve_symbol(text,symbol)
    elif start_line is None and end_line is None and not lines:
        return dict(ok=True, path=relative, revision=doc['revision'], text='', reason='empty_file', next_line=None)
    start = first if start_line is None else start_line
    end = last if end_line is None else end_line
    if not symbol and type(end) is int:
        end = min(end,last)
    if type(start) is not int or type(end) is not int or not first<=start<=end<=last:
        raise ValueError('行号超出范围')
    default_window = not symbol and start_line is None and end_line is None
    page_end = min(end, start + 39) if default_window else end
    result = dict(ok=True,**_page(relative,doc['revision'],lines,start,page_end))
    if default_window and result['end_line'] < last:
        result['next_line'] = result['end_line'] + 1
    # Index the same snapshot for jumping between distant source windows.
    if end - start >= 40 and Path(relative).suffix in {'.ts', '.tsx', '.js', '.jsx'}:
        headings = []
        for number, line in enumerate(lines, 1):
            label = line.strip()
            if re.match(r'^(?:(?:export|default|async)\s+)*(?:function|class)\s+|^(?:while|for)\s*\(', label):
                heading = dict(line=number, text=label[:120])
                if number > 1 and lines[number - 2].strip().startswith('//'):
                    heading['comment'] = lines[number - 2].strip()[:120]
                if re.match(r'^(?:export )?(?:default )?(?:abstract )?class ', label):
                    doc = _declaration_doc(lines, number - 1)
                    if doc:
                        heading['declaration_doc'] = doc
                headings.append(heading)
            elif re.match(r'^(?:const|let)?\s*\w+(?:\s*:[^=]+)?\s*=\s*\(?await\s+\w+\.get\w+', label):
                headings.append(dict(line=number, text=label[:120]))
            if len(headings) >= 30:
                break
        if include_initializer:
            # An assignment to a local factory is a call site, not evidence of its defaults.
            # Offer a bounded, separately located excerpt from the same file snapshot.
            factories = set(re.findall(r'\bthis\.\w+\s*=\s*((?:create|init)\w*)\(', result['text']))
            for heading in headings:
                definition = re.match(r'^(?:export )?function (\w+)\(', heading['text'])
                if not definition or definition[1] not in factories:
                    continue
                offset = heading['line'] - 1
                # Ignore indented or ambiguous declarations; a name alone cannot
                # select one of several definitions in different scopes.
                if lines[offset][:1].isspace() or sum(
                        bool(re.search(r'\bfunction\s+' + re.escape(definition[1]) + r'\s*\(', line))
                        for line in lines) != 1:
                    continue
                if start <= offset + 1 <= result['end_line']:
                    continue
                stop = next((n for n in range(offset + 1, min(offset + 40, len(lines)))
                             if lines[n].rstrip() == '}'), None)
                if stop is not None:
                    fragment = ''.join(lines[offset:stop + 1])
                    if len(fragment) <= 1800:
                        result['initializer_excerpt'] = dict(start_line=offset + 1, end_line=stop + 1, text=fragment)
                        break
        result['locations'] = headings[:16]
        # A loop may span several pages. Return its actual closing branch alongside
        # the opening window, preserving original line numbers and indentation.
        for index in range(start - 1, min(result['end_line'], end)):
            opening = lines[index].rstrip()
            if not re.match(r'^\s*while\s*\(.*\)\s*\{$', opening):
                continue
            indent = opening[:len(opening) - len(opening.lstrip())]
            closing = next((n for n in range(index + 1, len(lines)) if lines[n].rstrip() == indent + '}'), None)
            # For a long explicit window, a nearby closing branch is useful even
            # when it is just beyond the requested end. Label it separately.
            context_end = max(end, index + 120) if not default_window else end
            if closing is not None and start + 39 <= closing < context_end:
                first = max(start + 39, closing - 15)
                tail = ''.join(lines[first:closing + 1])
                if len(tail) <= 1400:
                    result['closing_excerpt'] = dict(start_line=first + 1, end_line=closing + 1, text=tail)
                    # Locate simple same-style braced loops; keep the original
                    # source line for every scope so the model can verify it.
                    loops = []
                    for n in range(index, first):
                        if not re.match(r'^\s*while\s*\(.*\)\s*\{$', lines[n].rstrip()):
                            continue
                        prefix = lines[n][:len(lines[n]) - len(lines[n].lstrip())]
                        last_line = next((k for k in range(n + 1, closing + 1)
                                          if lines[k].rstrip() == prefix + '}'), None)
                        if last_line is not None and last_line >= first:
                            loops.append(dict(header_line=n+1, closing_brace_line=last_line+1,
                                              header=lines[n].strip()))
                    if loops:
                        result['closing_excerpt']['enclosing_loops'] = loops
                break
    if symbol:
        result['symbol'] = symbol
    return result


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


def _line_ending(text):
    """Return the sole newline sequence, '' for none, or None for mixed."""
    pairs = text.count('\r\n')
    styles = [style for style,count in (('\r\n',pairs),('\r',text.count('\r')-pairs),
                                        ('\n',text.count('\n')-pairs)) if count]
    return styles[0] if len(styles)==1 else (None if styles else '')


def _match_error(section, old, pos, first):
    lines = list(io.StringIO(section,newline=''))
    if pos < 0:
        anchor = next((line.strip()[:160] for line in old.splitlines() if line.strip()), '')
        excerpts = [line.strip()[:160] for line in lines]
        nearest = get_close_matches(anchor, excerpts, n=1, cutoff=0.4) if anchor else []
        index = excerpts.index(nearest[0]) if nearest else 0
        hints = ' | '.join(f'L{first+i} {lines[i].rstrip()[:160]}' for i in
                           range(max(0,index-1), min(len(lines),index+2)))
        return ValueError(f'old_not_found 原文未找到（0 处）。请按当前原文修改。参考片段：{hints}')
    count, offsets = 0, []
    while pos >= 0:
        count += 1
        if len(offsets)<3:
            offsets.append(pos)
        pos = section.find(old,pos+1)
    hints = []
    start = 0
    for i,line in enumerate(lines,first):
        while offsets and offsets[0] < start+len(line):
            column = offsets.pop(0)-start
            hints.append(f'L{i}:{column+1} {line[max(0,column-40):column+100].rstrip()}')
        if not offsets:
            break
        start += len(line)
    return ValueError(f'old_ambiguous 原文不唯一（{count} 处）。补充上下文或指定 symbol：'+' | '.join(hints))


def patch(relative, old, new, revision, *, config, locked=False, symbol=None):
    if not isinstance(old,str) or not old or not isinstance(new,str) or old==new:
        raise ValueError('提供非空唯一原文和不同的替换文本')
    doc = workspace.read('main',relative,config,utf8_only=True)
    if not doc['editable'] or doc['kind']!='text':
        raise ValueError('仅可修改授权主目录的 UTF-8 文本')
    if doc['revision']!=revision:
        raise ValueError('stale_revision 文件版本已变化，请重新读取目标片段')
    text = doc['text']
    section, start, first = text, 0, 1
    if symbol is not None:
        if not isinstance(symbol,str) or not symbol.strip() or Path(relative).suffix.lower() not in {'.py','.pyi'}:
            raise ValueError('symbol 需要 Python 文件和有效限定名')
        _,first,last = _resolve_symbol(text,symbol)
        lines = list(io.StringIO(text,newline=''))
        start = sum(map(len,lines[:first-1]))
        section = ''.join(lines[first-1:last])
    pos = section.find(old)
    if pos<0:
        target, supplied = _line_ending(text), _line_ending(old)
        if target and supplied and target!=supplied and _line_ending(new) in ('',supplied):
            old = old.replace(supplied,target)
            new = new.replace(supplied,target)
            pos = section.find(old)
    if pos<0 or section.find(old,pos+1)>=0:
        raise _match_error(section,old,pos,first)
    pos += start
    return workspace.write(relative,text[:pos]+new+text[pos+len(old):],revision,config=config,locked=locked)
