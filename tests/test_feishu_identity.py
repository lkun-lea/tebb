import unittest
import json
from unittest.mock import patch
from desk_companion import feishu_auth as auth


class FeishuIdentityTests(unittest.TestCase):
    def test_native_status_shape_retains_verified_user_identity_without_tokens(self):
        native=dict(appId='app-one',brand='feishu',identity='user',verified=True,identities=dict(user=dict(available=True,verified=True,openId='user-one',userName='隔离用户',scope='task:task:write')))
        with patch.object(auth,'_lark_bin'),patch.object(auth,'_run_lark',return_value=json.dumps(native))as cli,patch('desk_companion.feishu_access.connected',return_value=True):
            value=auth.feishu_status(timeout=20)
        self.assertEqual(value['user_open_id'],'user-one');self.assertTrue(value['user_verified']);self.assertEqual(value['app_id'],'app-one')
        cli.assert_called_once_with(['auth','status','--json','--verify'],timeout=20)

    def status(self,**extra):
        return dict(ok=True,logged_in=True,identity='user',verified=True,user_verified=True,
            app_id='app-one',brand='feishu',user_open_id='user-one',user_name='隔离用户',**extra)

    def test_requires_verified_user_app_and_account_and_returns_no_credentials(self):
        with patch('desk_companion.feishu_access.require_connection'),patch.object(auth,'feishu_status',return_value=self.status())as read:
            value=auth.verified_user_identity();read.assert_called_once_with(timeout=20)
        self.assertEqual(value['open_id'],'user-one');self.assertEqual(set(value),{'identity','verified','app_id','brand','open_id','user_name'})
        for key,value in [('identity','bot'),('verified',False),('user_verified',False),('app_id',''),('user_open_id','')]:
            status=self.status();status[key]=value
            with patch('desk_companion.feishu_access.require_connection'),patch.object(auth,'feishu_status',return_value=status),self.assertRaises(RuntimeError):auth.verified_user_identity()

    def test_account_comparison_ignores_display_name_but_rejects_changed_app_or_user(self):
        value=dict(identity='user',verified=True,app_id='app-one',brand='feishu',open_id='user-one',user_name='名字')
        self.assertTrue(auth.same_user_identity(value,{**value,'user_name':'改名'}))
        for key in ('open_id','app_id','brand','identity'):
            self.assertFalse(auth.same_user_identity(value,{**value,key:'different'}))
        self.assertFalse(auth.same_user_identity(value,{**value,'verified':False}))
