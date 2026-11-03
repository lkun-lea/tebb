"""Freeze one account directory before importing the backend composition root."""
import os
from pathlib import Path
import runpy

from .account_store import AccountStore, LOCAL, profile_root
from .resource_lock import ResourceLock

_home_lease = None
_initialized = False
_initialization_error = None


def bind_runtime(home, store=None):
    home = Path(home).resolve()
    value = (store or AccountStore(home)).read()
    key = value['selected']
    data = profile_root(home,key)
    data.mkdir(parents=True,exist_ok=True)
    os.environ['DESK_COMPANION_HOME_DIR'] = str(home)
    os.environ['DESK_COMPANION_ACCOUNT_KEY'] = key
    os.environ['DESK_COMPANION_DATA_DIR'] = str(data)
    return key,data


def initialize_runtime(*, only_marked=False):
    global _initialization_error
    if _initialization_error is not None:
        raise _initialization_error
    if _initialized or only_marked and os.environ.get('DESK_COMPANION_ACCOUNT_BOOTSTRAP')!='1':
        return
    try:
        _initialize()
    except Exception as exc:
        _initialization_error = exc
        raise


def _initialize():
    global _home_lease,_initialized
    from .paths import data_root
    from .runtime_instance import InstanceInUse, INSTANCE_MESSAGE
    home = Path(os.environ.get('DESK_COMPANION_HOME_DIR') or data_root()).resolve()
    _home_lease = ResourceLock('account-home-process',directory=home/'account-control'/'locks')
    if not _home_lease.acquire(blocking=False):
        raise InstanceInUse(INSTANCE_MESSAGE)
    key,data = bind_runtime(home)
    os.environ.pop('DESK_COMPANION_ACCOUNT_BOOTSTRAP',None)
    if key != LOCAL:
        # Rust's bootstrap log stays at home; all account stdout/stderr goes into
        # that account before any services or task recovery are imported.
        with (data/'backend.log').open('ab',buffering=0) as log:
            os.dup2(log.fileno(),1)
            os.dup2(log.fileno(),2)
    _initialized = True

def launch():
    initialize_runtime()
    runpy.run_module('desk_companion.local_api.server',run_name='__main__')
