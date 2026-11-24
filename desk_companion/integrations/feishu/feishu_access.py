"""This tebb profile's opt-in, separate from the machine-wide CLI login."""
import json
import uuid
from desk_companion.infrastructure.paths import data_root
from desk_companion.infrastructure.resource_lock import ResourceLock


class NotConnected(RuntimeError):
    pass


def connection_id():
    path = data_root() / 'feishu-connection.json'
    try:
        state = json.loads(path.read_text('utf-8'))
        if state.get('connected') is True:
            ident = state.get('connection_id')
            return ident if isinstance(ident, str) and ident else 'connected'
    except (OSError, ValueError, AttributeError):
        pass
    return ''


def connected():
    return bool(connection_id())


def save(value):
    from desk_companion.infrastructure import storage
    with ResourceLock('feishu-connection'):
        storage.atomic_write(data_root() / 'feishu-connection.json',
                             dict(version=1, connected=bool(value), connection_id=uuid.uuid4().hex if value else ''))


def require_connection():
    if not connected():
        raise NotConnected('此 tebb 数据目录尚未连接飞书。请到设置 → 外部连接 → 飞书，明确连接本机账户；未读取外部资料。')
