"""Real task worker; a local proposal gate proves no calendar IO/lease is retained."""
from pathlib import Path
import json
import runpy
import sys
import time
from unittest.mock import patch

from gui_import_guard import NoGui, assert_no_gui
sys.meta_path.insert(0, NoGui())
from desk_companion import board_data
from desk_companion import calendar_proposals
from desk_companion.paths import data_root


original_build=calendar_proposals.build
def proposal(*args,**kwargs):
    (data_root()/'calendar.ready').touch();deadline=time.monotonic()+20
    while not(data_root()/'calendar.go').exists():
        if time.monotonic()>deadline:raise RuntimeError('fixture not released')
        time.sleep(.01)
    return original_build(*args,**kwargs)


with patch.object(board_data, '_run_lark', side_effect=AssertionError('proposal must not call calendar CLI')), \
        patch.object(calendar_proposals,'build',side_effect=proposal), \
        patch.object(board_data, 'today_date', return_value='2026-10-20'):
    runpy.run_path(str(Path(__file__).with_name('worker_fixture.py')), run_name='__main__')
assert_no_gui()
