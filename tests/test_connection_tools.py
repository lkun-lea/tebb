import json
from contextlib import closing
import sqlite3
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from desk_companion.collaboration.tebb_operations import execute
from desk_companion.local_api.bridge import Bridge


class ConnectionToolsTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / 'workspace.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE workspace(id INTEGER PRIMARY KEY,data TEXT)')
            db.execute('INSERT INTO workspace VALUES (1,?)', (json.dumps({'runs': [
                {'id':'run','agent':'tebb','state':'running','kind':'task'}]}),))
        self.host = SimpleNamespace(collaboration=SimpleNamespace(path=path,lock=threading.Lock()))
        self.host.bridge = Bridge(self.host)

    def test_video_credentials_stay_out_of_tool_receipt(self):
        with patch.object(self.host.bridge,'load_video_login',return_value={'items':[
                {'platform':'Bilibili','state':'saved','saved_at':1,'cookies':'secret'}]}):
            status = execute(self.host,'run','connection_status',{'service':'Bilibili'})
        self.assertEqual(status['state'],'saved')
        self.assertNotIn('secret',str(status))
        receipt=execute(self.host,'run','connection_authorize',{'service':'Bilibili'})
        self.assertEqual(receipt['state'],'needs_confirmation')

    def test_authorization_requires_active_agent_and_keeps_device_code_local(self):
        with patch.object(self.host.bridge,'feishu_login',return_value={'ok':True,'url':'sensitive'}) as login:
            self.assertFalse(execute(self.host,'missing','connection_authorize',{'service':'feishu'})['ok'])
            login.assert_not_called()
            receipt=execute(self.host,'run','connection_authorize',{'service':'feishu'})
            login.assert_called_once()
        self.assertTrue(receipt['ok'])
        self.assertNotIn('sensitive',str(receipt))

    @unittest.skipUnless(sys.platform == "win32", "Windows native account window")
    def test_github_interactive_commands_use_fixed_arguments(self):
        from desk_companion.integrations.github import client
        with patch.object(client,'_gh_bin',return_value='gh.exe'), patch.object(client.subprocess,'Popen') as launch:
            client.open_account_dialog('login')
            self.assertEqual(launch.call_args.args[0],['gh.exe','auth','login','--hostname','github.com','--web'])
            with self.assertRaises(ValueError):
                client.open_account_dialog('arbitrary')
            self.assertEqual(launch.call_count,1)
