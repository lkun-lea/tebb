"""当前账号的工具目录偏好与本机工具停用设置。观测记录由 ToolMonitor 独立保存。"""
from contextlib import closing
import sqlite3

from desk_companion.infrastructure.paths import data_root


def database():
    path = data_root() / 'memory' / 'tool-library.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("""CREATE TABLE IF NOT EXISTS entries(
        name TEXT PRIMARY KEY, title TEXT, summary TEXT, hidden INTEGER DEFAULT 0,
        disabled INTEGER DEFAULT 0)""")
    return db


def entries():
    with closing(database()) as db:
        return [dict(row) for row in db.execute('SELECT * FROM entries ORDER BY name')]


def update(name, changes):
    if not changes or changes.keys() - {'title', 'summary', 'hidden', 'disabled'}:
        raise ValueError('无效的目录操作')
    with closing(database()) as db, db:
        db.execute('INSERT OR IGNORE INTO entries(name) VALUES(?)', (name,))
        assignments = ', '.join(key + '=?' for key in changes)
        db.execute('UPDATE entries SET ' + assignments + ' WHERE name=?', (*changes.values(), name))


def disabled(name):
    path = data_root() / 'memory' / 'tool-library.sqlite3'
    if not path.exists():
        return False
    with closing(database()) as db:
        return bool(db.execute('SELECT 1 FROM entries WHERE name=? AND disabled=1', (name,)).fetchone())
