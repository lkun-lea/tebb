"""Supabase personalization contract client; never opens local user data or tools.

Tokens are supplied for one client lifetime, stay in memory, and are verified with
GoTrue rather than interpreted as trusted JWT claims. Account/session persistence
and desktop account switching belong to the later account integration step.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
import ipaddress
import json
import os
import re
from urllib.parse import urlsplit
from uuid import UUID

import httpx

CONTRACT = 'tebb.personalization.v1'


class CloudError(RuntimeError):
    """Safe error code/message; never includes server bodies or auth headers."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _uuid(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        return str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise CloudError('invalid_id', '账号、记录或操作编号格式无效。') from None


@dataclass(frozen=True)
class CloudConfig:
    url: str
    publishable_key: str = field(repr=False)

    def __post_init__(self):
        try:
            if not isinstance(self.url, str) or len(self.url) > 2048 or any(c.isspace() for c in self.url):
                raise ValueError()
            url = self.url.rstrip('/')
            parsed = urlsplit(url)
            local = parsed.hostname == 'localhost'
            if not local:
                try:
                    local = ipaddress.ip_address(parsed.hostname or '').is_loopback
                except ValueError:
                    pass
            if (not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
                    or not parsed.port and ':' in parsed.netloc and not parsed.netloc.endswith(']')
                    or parsed.scheme != 'https' and not (parsed.scheme == 'http' and local)):
                raise ValueError()
            if 'YOUR_PROJECT_REF' in url.upper():
                raise ValueError()
        except (ValueError, TypeError):
            raise CloudError('invalid_config', '请配置 Supabase HTTPS 项目地址；HTTP 仅允许本机测试地址。') from None
        key = self.publishable_key
        valid_key = isinstance(key, str) and len(key) <= 4096 and bool(re.fullmatch(r'sb_publishable_[A-Za-z0-9_-]{16,}', key))
        if not valid_key and isinstance(key, str) and len(key) <= 4096 and len(key.split('.')) == 3:
            try:
                payload = key.split('.')[1]
                claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
                # This rejects privileged key *configuration*, not JWT verification.
                valid_key = claims.get('role') == 'anon' and bool(re.fullmatch(r'[A-Za-z0-9_.-]+', key))
            except (ValueError, TypeError, AttributeError):
                pass
        if not valid_key or 'REPLACE_ME' in key:
            raise CloudError('invalid_config', '请配置 publishable 或旧版 anon key，不能使用服务端密钥。')
        object.__setattr__(self, 'url', url)

    @classmethod
    def from_env(cls, env=None):
        env = os.environ if env is None else env
        if not env.get('TEBB_CLOUD_URL') or not env.get('TEBB_CLOUD_PUBLISHABLE_KEY'):
            raise CloudError('needs_configuration', '尚未配置云端项目地址和公开客户端密钥。')
        return cls(env['TEBB_CLOUD_URL'], env['TEBB_CLOUD_PUBLISHABLE_KEY'])


class PersonalizationCloud:
    def __init__(self, config: CloudConfig, access_token: str = '', *, client: httpx.Client | None = None):
        if not isinstance(access_token, str) or len(access_token) > 16384 or any(c.isspace() for c in access_token):
            raise CloudError('invalid_session', '登录凭据格式无效。')
        self.config = config
        self._access_token = access_token
        self._owner = None
        self._own_client = client is None
        self._client = client or httpx.Client(timeout=httpx.Timeout(10, connect=5), follow_redirects=False)

    def close(self):
        if self._own_client:
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _request(self, method, path, body=None, *, authenticated=True):
        if authenticated and not self._access_token:
            raise CloudError('needs_login', '需要已登录的测试用户，不能用公开密钥代替登录。')
        headers = {'apikey': self.config.publishable_key, 'Accept': 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + self._access_token
        try:
            response = self._client.request(method, self.config.url + path, headers=headers, json=body,
                                            follow_redirects=False, timeout=10)
        except httpx.RequestError:
            raise CloudError('connection_failed', '云端连接失败；若写入结果不明，请先查询原操作编号。') from None
        if response.status_code in (401, 403):
            self._owner = None
            raise CloudError('unauthorized', '云端拒绝访问，请检查项目配置和测试用户登录状态。')
        if response.status_code == 404:
            raise CloudError('endpoint_missing', '云端接口不存在，请检查项目地址及数据库迁移。')
        if not 200 <= response.status_code < 300:
            raise CloudError('request_failed', f'云端请求未确认（HTTP {response.status_code}），请核对原操作。')
        try:
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise CloudError('invalid_response', '云端返回格式无效，不能据此确认成功。') from None

    def check_auth_endpoint(self):
        """Read-only reachability check. It neither sends OTPs nor signs anyone in."""
        settings = self._request('GET', '/auth/v1/settings', authenticated=False)
        if not isinstance(settings.get('external'), dict):
            raise CloudError('invalid_response', '项目认证接口返回格式不符。')
        return {'auth_reachable': True, 'email_enabled': settings['external'].get('email') is True}

    def verify_session(self):
        self._owner = None
        user = self._request('GET', '/auth/v1/user')
        self._owner = _uuid(user.get('id'))
        return self._owner

    def _rpc(self, method, payload):
        if self._owner is None:
            raise CloudError('needs_verification', '请先核实当前登录身份。')
        value = self._request('POST', '/rest/v1/rpc/tebb_personalization_' + method, payload)
        if value.get('user_id') != self._owner:
            self._owner = None
            raise CloudError('identity_mismatch', '云端回执不属于已核实账号，已停止采用。')
        return value

    def status(self):
        value = self._rpc('status', {})
        if value.get('contract') != CONTRACT or type(value.get('revision')) is not int or value['revision'] < 0:
            raise CloudError('contract_mismatch', '云端个性化接口版本或状态格式不匹配。')
        if value.get('pgvector') is not True:
            raise CloudError('missing_pgvector', '云端尚未启用 pgvector。')
        return value

    def pull(self, after=0, limit=100):
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise CloudError('invalid_cursor', '同步游标或每页数量无效。')
        value = self._rpc('pull', {'p_after': after, 'p_limit': limit})
        if (not isinstance(value.get('records'), list) or len(value['records']) > limit
                or type(value.get('cursor')) is not int or type(value.get('head')) is not int
                or not after <= value['cursor'] <= value['head'] or type(value.get('has_more')) is not bool
                or value['has_more'] and (value['cursor'] <= after or len(value['records']) != limit)
                or not value['has_more'] and value['cursor'] != value['head']):
            raise CloudError('invalid_response', '同步页格式或游标无效，未推进本机状态。')
        previous = after
        for row in value['records']:
            if (not isinstance(row, dict) or type(row.get('sequence')) is not int
                    or not previous < row['sequence'] <= value['cursor'] or type(row.get('version')) is not int or row['version'] < 1
                    or row.get('state') not in {'active', 'disabled', 'deleted'}
                    or row.get('kind') not in {'profile','preference','memory'}
                    or row.get('category') not in {'communication','knowledge','goal','project','other'}
                    or row.get('scope') not in {'user','project','companion'}
                    or not isinstance(row.get('scope_id'), str) or len(row['scope_id']) > 128
                    or row['scope'] == 'user' and row['scope_id'] != ''
                    or row['scope'] != 'user' and not row['scope_id'].strip()
                    or row['state'] != 'deleted' and (not isinstance(row.get('text'), str) or not 1 <= len(row['text'].strip()) <= 4000)
                    or row.get('state') == 'deleted' and any(row.get(k) is not None for k in ('text','source_ref','source_device_id'))):
                raise CloudError('invalid_response', '同步记录格式无效，未采用该页。')
            _uuid(row.get('id'))
            previous = row['sequence']
        if value['has_more'] and previous != value['cursor']:
            raise CloudError('invalid_response', '分页游标与最后一条记录不一致。')
        return value

    def operation(self, operation_id):
        operation_id = _uuid(operation_id)
        value = self._rpc('operation', {'p_operation_id': operation_id})
        if type(value.get('found')) is not bool or (not value['found'] and value.get('receipt') is not None):
            raise CloudError('invalid_response', '操作查询回执格式无效。')
        if value['found']:
            self._validate_receipt(value.get('receipt'), operation_id)
        return value

    def apply(self, operation_id, record_id, expected_version, action, payload=None):
        operation_id, record_id = _uuid(operation_id), _uuid(record_id)
        if type(expected_version) is not int or expected_version < 0 or action not in ('put','disable','delete'):
            raise CloudError('invalid_operation', '变更操作或预期版本无效。')
        if action == 'put' and not isinstance(payload, dict) or action != 'put' and payload is not None:
            raise CloudError('invalid_operation', '写入需要明确确认后的记录；停用/删除不接收正文。')
        value = self._rpc('apply', {'p_operation_id':operation_id,'p_record_id':record_id,
                                  'p_expected_version':expected_version,'p_action':action,'p_payload':payload})
        self._validate_receipt(value, operation_id)
        if value['record_id'] != record_id or value['action'] != action:
            raise CloudError('invalid_response', '回执与原操作不匹配，请查询原操作编号。')
        return value

    def _validate_receipt(self, value, operation_id):
        if (not isinstance(value, dict) or value.get('user_id') != self._owner
                or value.get('operation_id') != operation_id or value.get('status') not in {'applied','conflict','gone','not_found'}
                or type(value.get('version')) is not int or value['version'] < 0
                or type(value.get('cursor')) is not int or value['cursor'] < 0
                or value.get('status') == 'applied' and (value['version'] < 1 or value['cursor'] < 1)
                or value.get('action') not in {'put','disable','delete'}):
            raise CloudError('invalid_response', '变更回执格式无效，不能确认成功。')
        _uuid(value.get('record_id'))


def preflight(*, connect=False, env=None, client=None):
    """No network by default. Explicit connect is read-only and never loads facts."""
    env = os.environ if env is None else env
    config = CloudConfig.from_env(env)
    if not connect:
        return {'status':'configured', 'network_checked':False, 'deployment_checked':False}
    with PersonalizationCloud(config, env.get('TEBB_CLOUD_ACCESS_TOKEN',''), client=client) as cloud:
        auth = cloud.check_auth_endpoint()
        if not auth['email_enabled']:
            raise CloudError('email_disabled', '云端未启用邮箱登录，请先核对 Auth 配置。')
        if not env.get('TEBB_CLOUD_ACCESS_TOKEN'):
            return {'status':'needs_login', **auth, 'deployment_checked':False}
        cloud.verify_session()
        state = cloud.status()
        page = cloud.pull(0, 1)
        return {'status':'ready', **auth, 'deployment_checked':True, 'contract':state['contract'],
                'pgvector':True, 'has_records':bool(page['records']), 'read_only':True}
