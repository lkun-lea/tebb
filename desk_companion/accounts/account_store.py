"""One encrypted, versioned account registry for a local installation.

Workspace data stays in its own directory. This registry only owns login sessions,
explicit next-start selection, and receipts for account operations.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
from uuid import UUID

from desk_companion.accounts.personalization_cloud import CloudConfig, CloudError
from desk_companion.infrastructure.resource_lock import ResourceLock
from desk_companion.infrastructure import storage

LOCAL = 'local'


def account_key(url, user_id):
    subject = str(UUID(user_id))
    return hashlib.sha256((url+'\0'+subject).encode()).hexdigest()


def profile_root(home, key):
    home = Path(home).resolve()
    if key == LOCAL:
        return home
    if not isinstance(key,str) or not re.fullmatch(r'[a-f0-9]{64}',key):
        raise CloudError('invalid_account','账号空间标识无效。')
    expected = home/'accounts'/key/'data'
    result = expected.resolve()
    if result != expected:
        raise CloudError('invalid_account','账号空间路径无效。')
    return result


class WindowsAccountCipher:
    """Use the same OS protection as video login; there is no plaintext fallback."""
    def seal(self, raw):
        import win32crypt
        return win32crypt.CryptProtectData(raw,'tebb accounts',b'tebb.accounts.v1',None,None,1)

    def open(self, raw):
        import win32crypt
        return win32crypt.CryptUnprotectData(raw,b'tebb.accounts.v1',None,None,1)[1]


def empty_registry():
    return dict(version=0,config=None,selected=LOCAL,accounts={},operations={},challenges={})


class AccountStore:
    def __init__(self, home, *, cipher=None):
        self.home = Path(home).resolve()
        self.directory = self.home/'account-control'
        self.path = self.directory/'accounts.json'
        self.cipher = cipher or WindowsAccountCipher()
        self.lock = ResourceLock('account-registry',directory=self.directory/'locks')
        self.actions = ResourceLock('account-actions',directory=self.directory/'locks')

    def _read(self):
        if not self.path.exists():
            return empty_registry()
        try:
            envelope = json.loads(self.path.read_text('utf-8'))
            if envelope.get('format') != 1:
                raise ValueError()
            raw = self.cipher.open(base64.b64decode(envelope['encrypted'],validate=True))
            value = json.loads(raw)
            if (type(value['version']) is not int or value['version'] < 0
                    or any(not isinstance(value[k],dict) for k in ('accounts','operations','challenges'))):
                raise ValueError()
            config = CloudConfig(**value['config']) if value['config'] else None
            for key, account in value['accounts'].items():
                if (not config or account['url'] != config.url or account_key(account['url'],account['user_id']) != key
                        or not isinstance(account['email'],str)):
                    raise ValueError()
                profile_root(self.home,key)
                session=account.get('session')
                if session is not None and (not isinstance(session,dict) or session.get('user_id')!=account['user_id']
                    or type(session.get('expires_at')) not in (int,float) or not math.isfinite(session['expires_at'])
                    or any(not isinstance(session.get(k),str) or not session[k] or len(session[k])>16384 for k in ('access_token','refresh_token'))):
                    raise ValueError()
            if value['selected'] != LOCAL and value['selected'] not in value['accounts']:
                raise ValueError()
            return value
        except Exception:
            raise CloudError('account_store_unavailable','本机账号记录无法读取或解密，未切换空间；请保留记录并核查。') from None

    def read(self):
        with self.lock:
            return self._read()

    @contextmanager
    def transaction(self):
        with self.lock:
            value = self._read()
            previous = deepcopy(value)
            yield value
            if value != previous:
                value['version'] = previous['version']+1
                try:
                    encrypted = self.cipher.seal(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())
                    storage.atomic_write(self.path,dict(format=1,encrypted=base64.b64encode(encrypted).decode()))
                except Exception:
                    raise CloudError('account_save_unconfirmed','账号记录保存未确认，请读取原操作状态，不要重复登录或切换。') from None


@dataclass(frozen=True)
class AccountRuntime:
    home: Path
    key: str
    data: Path

    @classmethod
    def current(cls):
        from desk_companion.infrastructure.paths import data_root
        data = data_root().resolve()
        home = Path(os.environ.get('DESK_COMPANION_HOME_DIR') or data).resolve()
        key = os.environ.get('DESK_COMPANION_ACCOUNT_KEY',LOCAL)
        if profile_root(home,key) != data:
            raise CloudError('account_binding_mismatch','当前后台的账号和数据目录不匹配，已停止账号操作。')
        return cls(home,key,data)
