"""Account operations: one frozen runtime and one encrypted registry owner."""
import hashlib
import json
import os
import re
import time
from uuid import UUID

from .account_auth import AccountAuth
from .account_store import AccountRuntime, AccountStore, LOCAL, account_key
from .personalization_cloud import CloudConfig, CloudError


class AccountService:
    def __init__(self, runtime=None, *, store=None, auth=None, env=None):
        self.runtime = runtime or AccountRuntime.current()
        self.store = store or AccountStore(self.runtime.home)
        self.auth = auth or AccountAuth()
        self.env = os.environ if env is None else env

    def _config(self, state):
        managed = bool(self.env.get('TEBB_CLOUD_URL') or self.env.get('TEBB_CLOUD_PUBLISHABLE_KEY'))
        config = CloudConfig.from_env(self.env) if managed else CloudConfig(**state['config']) if state['config'] else None
        if config and state['accounts'] and state['config']['url'] != config.url:
            raise CloudError('project_mismatch','启动项目与已保存账号不匹配，未切换到其他项目。')
        return config,managed

    @staticmethod
    def _receipt(operation):
        return {k:v for k,v in operation.items() if k!='digest'}

    def status(self, operation_id=''):
        state = self.store.read()
        error = ''
        try:
            config,managed = self._config(state)
        except CloudError as exc:
            config,managed,error = None,True,str(exc)
        if self.runtime.key!=LOCAL and self.runtime.key not in state['accounts']:
            raise CloudError('account_binding_mismatch','当前账号记录与后台空间不匹配，未采用其他账号。')
        accounts = []
        for key,item in state['accounts'].items():
            session = item.get('session')
            health = 'reauth_required' if item.get('refresh_state') in {'pending','reauth_required'} or not session else \
                     'expired' if session['expires_at']<=time.time() else 'signed_in'
            accounts.append(dict(id=key,email=item['email'],state=health,current=key==self.runtime.key))
        current = next((item for item in accounts if item['current']),None)
        challenge = next((dict(id=key,email=value['email'],expires_at=value['expires_at'])
                          for key,value in reversed(list(state['challenges'].items()))
                          if value['state']=='sent' and value['expires_at']>time.time()),None)
        operation = state['operations'].get(operation_id) if operation_id else None
        return dict(ok=True,version=state['version'],runtime=dict(key=self.runtime.key,
                    mode='local' if self.runtime.key==LOCAL else 'account',email=current['email'] if current else ''),
                    configured=config is not None,config_managed=managed,url=config.url if config else '',
                    config_error=error,accounts=accounts,selected=state['selected'],
                    restart_required=state['selected']!=self.runtime.key,challenge=challenge,
                    operation=self._receipt(operation) if operation else None)

    def action(self, payload):
        if not isinstance(payload,dict):
            raise CloudError('invalid_action','账号操作必须为对象。')
        kind = payload.get('type')
        if kind not in {'configure','send_code','verify_code','activate','check_session','logout','cancel_switch','acknowledge'}:
            raise CloudError('invalid_action','账号操作不存在。')
        try:
            op_id = str(UUID(payload.get('request_id','')))
        except (ValueError,TypeError,AttributeError):
            raise CloudError('invalid_action','请保留有效的账号操作编号。') from None
        digest = hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if not self.store.actions.acquire(blocking=False):
            return {**self.status(),'ok':False,'code':'busy','error':'已有账号操作正在处理，请读取原操作状态。'}
        try:
            old = self.store.read()['operations'].get(op_id)
            if old:
                if old['digest']!=digest:
                    raise CloudError('operation_conflict','同一操作编号不能用于不同的账号请求。')
                return {**self.status(op_id),'ok':old['state']=='complete',
                        'code':'unconfirmed' if old['state']=='pending' else old.get('code',''),
                        'error':old.get('error','原请求结果未确认；不会再次发送。') if old['state']!='complete' else ''}
            try:
                return self._perform(op_id,kind,digest,payload)
            except CloudError as exc:
                accepted=op_id in self.store.read()['operations']
                return {**self.status(op_id),'ok':False,'code':exc.code,'error':str(exc),'accepted':accepted}
        finally:
            self.store.actions.__exit__()

    def _perform(self, op_id, kind, digest, payload):
        context = {}
        with self.store.transaction() as state:
            if type(payload.get('version')) is not int or payload['version']!=state['version']:
                return {**self.status(),'ok':False,'code':'version_conflict','error':'账号状态已变化，请刷新后再操作。'}
            local_action = kind in {'logout','cancel_switch','acknowledge'} or kind=='activate' and payload.get('account_id')==LOCAL
            try:
                config,managed = self._config(state)
            except CloudError:
                if not local_action:
                    raise
                config,managed = None,True
            if kind=='configure':
                if managed:
                    raise CloudError('managed_config','云项目由启动配置管理，请在部署环境中修改。')
                config = CloudConfig(payload.get('url',''),payload.get('publishable_key','') or (config.publishable_key if config else ''))
                if state['accounts'] and config.url!=state['config']['url']:
                    raise CloudError('project_mismatch','已有账号时不能直接更换云项目。')
                if state['config']!=dict(url=config.url,publishable_key=config.publishable_key):
                    for challenge in state['challenges'].values():
                        challenge['state']='retired'
                state['config'] = dict(url=config.url,publishable_key=config.publishable_key)
            elif not local_action:
                if config is None:
                    raise CloudError('needs_configuration','请先准备云端项目配置。')
                state['config'] = dict(url=config.url,publishable_key=config.publishable_key)
            if kind=='send_code':
                email = payload.get('email','')
                if not isinstance(email,str) or len(email)>320 or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',email.strip()):
                    raise CloudError('invalid_email','请输入有效邮箱。')
                email = email.strip().casefold()
                if any(c['email']==email and time.time()-c['created_at']<60 for c in state['challenges'].values()):
                    raise CloudError('rate_limited','请稍后再获取验证码，不会重复发送原请求。')
                project=hashlib.sha256((config.url+'\0'+config.publishable_key).encode()).hexdigest()
                state['challenges'][op_id] = dict(email=email,state='pending',created_at=time.time(),expires_at=time.time()+600,project=project)
                context['email'] = email
            elif kind=='verify_code':
                challenge = state['challenges'].get(payload.get('challenge_id'))
                code = payload.get('code','')
                if not challenge or challenge['state']!='sent' or challenge['expires_at']<=time.time():
                    raise CloudError('invalid_challenge','验证码请求无效或已过期，请重新获取。')
                if challenge['project']!=hashlib.sha256((config.url+'\0'+config.publishable_key).encode()).hexdigest():
                    raise CloudError('invalid_challenge','项目配置已变化，请重新获取验证码。')
                if not isinstance(code,str) or not re.fullmatch(r'\d{6}',code,re.ASCII):
                    raise CloudError('invalid_code','请输入六位验证码。')
                challenge['state'] = 'verifying'
                context.update(email=challenge['email'],code=code,challenge_id=payload['challenge_id'])
            elif kind in {'activate','check_session','logout'}:
                key = payload.get('account_id') if kind=='activate' else self.runtime.key
                if key==LOCAL and kind=='activate':
                    context['local'] = True
                else:
                    account = state['accounts'].get(key)
                    if not account:
                        raise CloudError('unknown_account','当前账号不存在。')
                    session = account.get('session')
                    context.update(key=key,account=account.copy(),session=session)
                    if kind=='logout':
                        account.update(session=None,refresh_state='reauth_required')
                        state['selected'] = LOCAL
                    else:
                        if not session or account.get('refresh_state') in {'pending','reauth_required'}:
                            raise CloudError('needs_login','此账号需要重新输入验证码登录。')
                        context['refresh'] = session['expires_at']<=time.time()+60
                        if context['refresh']:
                            account['refresh_state'] = 'pending'
            elif kind=='cancel_switch':
                state['selected'] = self.runtime.key
            elif kind=='acknowledge':
                try:
                    target=str(UUID(payload.get('operation_id','')))
                except (ValueError,TypeError,AttributeError):
                    raise CloudError('invalid_action','缺少要核对的原操作编号。') from None
                if target==op_id:
                    raise CloudError('invalid_action','核对操作必须使用新的编号。')
                original=state['operations'].get(target)
                if original is None or original['state']=='pending':
                    original=original or dict(id=target,type='unknown',digest=None)
                    original.update(state='unconfirmed',code='acknowledged_unknown',error='原操作结果仍未确认，已结束本机核对，不会重放。')
                    state['operations'][target]=original
                    account=state['accounts'].get(original.get('account_id'))
                    if account and account.get('refresh_state')=='pending':
                        account.update(session=None,refresh_state='reauth_required')
                    for key in (target,original.get('challenge_id')):
                        if key in state['challenges']:
                            state['challenges'][key]['state']='unconfirmed'
            state['operations'][op_id] = dict(id=op_id,type=kind,digest=digest,state='pending')
            for field in ('key','challenge_id'):
                if field in context:
                    state['operations'][op_id]['account_id' if field=='key' else field]=context[field]
        outcome,error = {},None
        try:
            if kind=='send_code':
                self.auth.send_code(config,context['email'])
            elif kind=='verify_code':
                session = self.auth.verify(config,context['email'],context['code'])
                if session['email'].casefold()!=context['email']:
                    raise CloudError('identity_mismatch','验证返回的账号与申请邮箱不一致，未保存。')
                outcome['session'] = session
            elif kind in {'activate','check_session'} and not context.get('local'):
                old = context['session']
                session = self.auth.refresh(config,old['refresh_token']) if context['refresh'] else self.auth.check(config,old)
                if session['user_id']!=context['account']['user_id']:
                    raise CloudError('identity_mismatch','核实身份与原账号不一致，未切换。')
                outcome['session'] = session
            elif kind=='logout' and context['session']:
                if config is None:
                    raise CloudError('needs_configuration','远端项目配置不可用。')
                self.auth.logout(config,context['session']['access_token'])
        except CloudError as exc:
            error = exc
        with self.store.transaction() as state:
            operation = state['operations'][op_id]
            operation.update(state='failed' if error else 'complete')
            if error:
                operation.update(code=error.code,error=str(error))
            if kind=='send_code':
                state['challenges'][op_id]['state'] = 'unconfirmed' if error else 'sent'
            elif kind=='verify_code':
                state['challenges'][context['challenge_id']]['state'] = 'sent' if error and error.code=='invalid_otp' else 'unconfirmed' if error else 'used'
                if not error:
                    session = outcome['session']
                    key = account_key(config.url,session['user_id'])
                    state['accounts'][key] = dict(url=config.url,user_id=session['user_id'],email=session['email'],
                                                session=session,refresh_state='ready')
                    state['selected'] = key
                    operation['account_id'] = key
            elif kind in {'activate','check_session'}:
                if context.get('local'):
                    state['selected'] = LOCAL
                elif error:
                    if context['refresh'] or error.code in {'identity_mismatch','needs_login'}:
                        state['accounts'][context['key']].update(session=None,refresh_state='reauth_required')
                else:
                    state['accounts'][context['key']].update(session=outcome['session'],email=outcome['session']['email'],refresh_state='ready')
                    if kind=='activate':
                        state['selected'] = context['key']
            elif kind=='logout':
                operation.update(state='complete',remote_status='unconfirmed' if error else 'confirmed' if context['session'] else 'not_requested')
                operation['notice'] = '本机登录已移除。'+('远端注销未确认。' if error else '')+'重启后返回本机空间。'
        result = self.status(op_id)
        if error and kind!='logout':
            result.update(ok=False,code=error.code,error=str(error))
        return result
