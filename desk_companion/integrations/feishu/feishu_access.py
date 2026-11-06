"""This tebb profile's opt-in, separate from the machine-wide CLI login."""
import json
from desk_companion.infrastructure.paths import data_root
from desk_companion.infrastructure.resource_lock import ResourceLock


class NotConnected(RuntimeError):
    pass


def connected():
    path = data_root() / 'feishu-connection.json'
    try:
        return json.loads(path.read_text('utf-8')).get('connected') is True
    except (OSError, ValueError, AttributeError):
        return False


def save(value):
    from desk_companion.infrastructure import storage
    with ResourceLock('feishu-connection'):
        storage.atomic_write(data_root() / 'feishu-connection.json', dict(version=1, connected=bool(value)))


def require_connection():
    if not connected():
        raise NotConnected('此 tebb 数据目录尚未连接飞书。请到设置 → 连接与网络 → 飞书，明确连接本机账户；未读取外部资料。')
