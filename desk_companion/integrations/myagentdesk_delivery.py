"""Account-scoped device pairing, explicit local approval and durable receipt replay."""
from base64 import b64decode, b64encode
from pathlib import Path
from secrets import token_hex
from shlex import join
from tempfile import NamedTemporaryFile
from urllib.parse import urlparse
from uuid import UUID, uuid5
import json
import os
import re

from desk_companion.accounts.account_store import WindowsAccountCipher
from desk_companion.infrastructure.resource_lock import ResourceLock
from desk_companion.integrations.myagentdesk_snapshot import prepare
from desk_companion.projects.project_workspace import clean_root


ACTIVE = {'starting', 'running', 'stopping'}


def write_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    file = NamedTemporaryFile(dir=path.parent, delete=False)
    pending = Path(file.name)
    try:
        with file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        pending.replace(path)
    finally:
        pending.unlink(missing_ok=True)


def plain(data):
    return json.dumps(data, ensure_ascii=False).encode()


def canonical_origin(value):
    url = urlparse(value)
    if (not url.hostname or url.username or url.password or url.params or url.query or url.fragment
            or url.path not in ('', '/') or not (url.scheme == 'https' or
            url.scheme == 'http' and url.hostname in ('localhost', '127.0.0.1', '::1'))):
        raise ValueError('工作台地址须使用 HTTPS 或本机 HTTP。')
    return f'{url.scheme}://{url.netloc}'


def remote(connection, method, path, body=None):
    import httpx

    origin = connection['origin']
    headers = {'Authorization': 'Bearer ' + connection['credential'], 'Origin': origin, 'X-MAD-Request': '1'}
    with httpx.Client(base_url=origin, headers=headers, timeout=5, trust_env=False) as client:
        result = client.request(method, path, json=body)
        result.raise_for_status()
        return result.json()


def commands_for(request, recipe_text):
    if len(recipe_text) > 20000:
        raise ValueError('命令清单最多 20,000 个字符。')
    recipe = json.loads(recipe_text)
    frozen = request['input']
    keys = ([f'criterion:{i+1}' for i in range(len(frozen['criteria']))]
            + [f'check:{i+1}' for i in range(len(frozen['checks']))]) if request['stage'] == 'testing' else ['implementation']
    if not isinstance(recipe, dict) or set(recipe) != set(keys):
        raise ValueError('本机命令清单必须覆盖冻结的用例和必过项。')
    commands = []
    for key in keys:
        argv = recipe[key]
        if not isinstance(argv, list) or not argv or not all(isinstance(item, str) and item and '\0' not in item for item in argv):
            raise ValueError('命令清单必须使用非空参数数组。')
        command = join(argv)
        if len(command) > 4000:
            raise ValueError('单条本机命令最多 4,000 个字符。')
        commands.append({'key': key, 'command': command})
    return commands


def result_evidence(terminal, job, key, environment):
    output, offset = bytearray(), 0
    while len(output) <= 15000:
        page = terminal.read(job['id'], offset)
        output.extend(b64decode(page['data']))
        if offset == page['offset']:
            break
        offset = page['offset']
    text = bytes(output[:15000]).decode('utf-8', 'replace')
    if len(output) > 15000:
        text += '\n[output truncated]'
    return {'key': key, 'run': job['id'], 'command': job['command'], 'environment': environment,
            'exit_code': job['exit_code'] if job['exit_code'] is not None else -1, 'output': text}


class DesktopDelivery:
    def __init__(self, folder, terminal, workspace, *, cipher=None, transport=remote, snapshot=prepare):
        self.folder = Path(folder)
        self.device_file = self.folder / 'pairing.dpapi'
        self.lock = ResourceLock('myagentdesk-delivery', directory=self.folder)
        self.cipher = cipher or WindowsAccountCipher()
        self.terminal = terminal
        self.workspace = workspace
        self.request = transport
        self.snapshot = snapshot
        self.queue = []
        self.connection_status = 'offline'

    def connection(self):
        if not self.device_file.is_file():
            return None
        return json.loads(self.cipher.open(self.device_file.read_bytes()))

    def save_connection(self, connection):
        write_bytes(self.device_file, self.cipher.seal(plain(connection)))

    def rows(self):
        return [json.loads(file.read_bytes()) for file in (self.folder / 'runs').glob('*.json')]

    def save(self, row):
        write_bytes(self.folder / 'runs' / (row['request']['id'] + '.json'), plain(row))

    def pair(self, package):
        value = json.loads(package)
        platform = canonical_origin(value['origin'])
        identifier = str(UUID(value['id']))
        code = value['code']
        if not re.fullmatch(r'[a-f0-9]{64}', code):
            raise ValueError('配对码格式无效。')
        with self.lock:
            current = self.connection()
            if current and current['id'] == identifier and current['origin'] == platform:
                return
            if current and any(row['device'] == current['id'] and row['phase'] not in {'uploaded','blocked'}
                               for row in self.rows()):
                raise ValueError('本机仍有未送达的执行记录，请先核对原设备。')
            self.save_connection({'origin': platform, 'id': identifier, 'code': code, 'credential': token_hex(32)})
            self.queue = []
            self.connection_status = 'pairing'

    def approve(self, identifier, directory, recipe):
        identifier = str(UUID(identifier))
        with self.lock:
            connection = self.connection()
            if not connection or 'code' in connection:
                raise ValueError('先完成设备配对。')
            if (self.folder / 'runs' / (identifier + '.json')).exists():
                return
            request = next((item for item in self.queue if item['id'] == identifier), None)
            if request is None:
                raise ValueError('当前派发不可领取，请刷新任务。')
            root = str(clean_root(directory))
            self.save({'request': request, 'device': connection['id'], 'directory': root,
                       'commands': commands_for(request, recipe), 'phase': 'authorized', 'checks': []})

    def status(self):
        connection = self.connection()
        jobs = self.rows()
        known = {row['request']['id'] for row in jobs}
        return {'device': ({'id': connection['id'], 'origin': connection['origin'], 'label': connection.get('label')}
                           if connection else None),
                'connection': self.connection_status,
                'queue': [item for item in self.queue if item['id'] not in known],
                'runs': [{**{key: row['request'][key] for key in ('id', 'title', 'stage', 'input', 'source')},
                          'phase': row['phase'], 'receipt_status': row.get('receipt', {}).get('status'),
                          'runs': [item['run'] for item in row['checks']] + ([row['job']] if row.get('job') else []),
                          'error': row.get('error', '')} for row in jobs]}

    def task_receipt(self, row, outcome):
        frozen = row['request']['input']
        share = outcome == 'succeeded' and row['request']['stage'] == 'development'
        row['receipt'] = {'device': row['device'], 'commit': frozen['commit'], 'status': outcome,
                          'digest': row.get('digest'), 'artifact': row.get('artifact') if share else None,
                          'checks': row['checks']}
        row['phase'] = 'outbox'
        row.pop('artifact', None)
        row.pop('job', None)
        self.save(row)

    def reconcile(self, row):
        try:
            job = self.terminal.find_request(row['intent'])
        except (ValueError, OSError):
            job = None
        if job is None or job['session'] != row['session'] or job['command'] != row['commands'][len(row['checks'])]['command']:
            self.task_receipt(row, 'needs_review')
            return
        row['job'] = job['id']
        if job['state'] in ACTIVE:
            self.save(row)
            return
        try:
            evidence = result_evidence(self.terminal, job, row['commands'][len(row['checks'])]['key'], row['environment'])
        except (ValueError, OSError):
            self.task_receipt(row, 'needs_review')
            return
        row['checks'].append(evidence)
        row.pop('job', None)
        outcome = {'succeeded': 'succeeded', 'failed': 'failed', 'cancelled': 'cancelled'}.get(job['state'], 'needs_review')
        if outcome == 'succeeded' and (evidence['exit_code'] != 0 or not evidence['output'].strip()):
            outcome = 'needs_review'
        if outcome == 'succeeded' and len(row['checks']) < len(row['commands']):
            row['phase'] = 'ready'
            self.save(row)
        else:
            self.task_receipt(row, outcome)

    def _advance(self, connection, row, eligible):
        identifier = row['request']['id']
        path = f'/api/executor/{identifier}'
        phase = row['phase']
        if phase == 'intent':
            self.reconcile(row)
        elif phase == 'outbox':
            response = self.request(connection, 'PUT', path + '/receipt', row['receipt'])
            row.update(phase='uploaded', receipt_status=response['status'], error='')
            self.save(row)
        elif phase in {'authorized', 'claimed', 'ready'}:
            if phase == 'authorized':
                claimed = self.request(connection, 'POST', path + '/claim', {'device': row['device']})
                if claimed['status'] != 'running' or claimed['input'] != row['request']['input']:
                    row.update(phase='blocked', error='派发范围或状态已变更。')
                else:
                    row['phase'] = 'claimed'
                self.save(row)
            elif identifier not in eligible:
                row.update(phase='blocked', error='派发或阶段授权已失效。')
                self.save(row)
            elif phase == 'claimed':
                sandbox = self.terminal.status()
                if not sandbox['ready']:
                    row['error'] = 'tebb 沙箱未就绪，请检查终端设置。'
                    self.save(row)
                    return
                row['session'] = 'mad-desktop-' + UUID(identifier).hex
                patch, digest = self.snapshot(clean_root(row['directory']), row['request']['input'], self.workspace(row['session']))
                row.update(phase='ready', digest=digest, artifact=b64encode(patch).decode(),
                           environment=f"{sandbox['provider']} / {sandbox['distro']}", error='')
                self.save(row)
            else:
                # Revalidate the actor and frozen dispatch online before each new command.
                current = self.request(connection, 'POST', path + '/claim', {'device': row['device']})
                if current['status'] != 'running' or current['input'] != row['request']['input']:
                    row.update(phase='blocked', error='派发范围或状态已变更。')
                    self.save(row)
                    return
                command = row['commands'][len(row['checks'])]
                row.update(phase='intent', intent=uuid5(UUID(identifier), command['key']).hex)
                self.save(row)
                self.terminal.start(command['command'], row['session'], timeout=90, request_id=row['intent'])

    def sync_once(self):
        if not self.device_file.is_file():
            return
        import httpx

        with self.lock:
            connection = self.connection()
            if not connection:
                return
            try:
                device = connection['id']
                if 'code' in connection:
                    activated = self.request(connection, 'POST', f'/api/executor/devices/{device}/activate',
                                              {'code': connection['code'], 'credential': connection['credential']})
                    connection['label'] = activated['label']
                    connection.pop('code')
                    self.save_connection(connection)
                queue = self.request(connection, 'GET', f'/api/executor/devices/{device}/dispatches')['dispatches']
                self.queue = queue
                self.connection_status = 'online'
                eligible = {item['id'] for item in queue}
            except httpx.HTTPStatusError:
                self.connection_status = 'denied'
                self.queue = []
                eligible = set()
            except httpx.RequestError:
                self.connection_status = 'offline'
                self.queue = []
                eligible = set()
            for row in self.rows():
                if row['device'] != connection['id'] or row['phase'] in {'uploaded', 'blocked'}:
                    continue
                if self.connection_status != 'online' and row['phase'] != 'intent':
                    continue
                try:
                    self._advance(connection, row, eligible)
                except httpx.RequestError:
                    self.connection_status = 'offline'
                except httpx.HTTPStatusError:
                    if row['phase'] == 'outbox':
                        row['error'] = '工作台未接收回执，请核对账号、设备或派发状态。'
                    else:
                        row.update(phase='blocked', error='其他设备已领取，或本机的领取权限已失效。')
                    self.save(row)
                except Exception:
                    row['error'] = '需核对本机仓库、命令或原 tebb 运行记录。'
                    self.save(row)

    def operation(self, action='status', package='', identifier='', directory='', recipe=''):
        if action == 'pair':
            self.pair(package)
        elif action == 'approve':
            self.approve(identifier, directory, recipe)
        elif action != 'status':
            raise ValueError('不支持的交付操作。')
        return self.status()
