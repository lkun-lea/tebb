"""Official Supabase Auth SDK adapter. No auth algorithm or token store here."""
from contextlib import contextmanager
import time
from uuid import UUID

from .personalization_cloud import CloudError


class AccountAuth:
    def __init__(self, client_factory=None):
        self.client_factory = client_factory or self._http_client

    @staticmethod
    def _http_client():
        import httpx
        return httpx.Client(timeout=15, follow_redirects=False)

    @contextmanager
    def sdk(self, config):
        try:
            from supabase_auth import SyncGoTrueClient
        except ImportError:
            raise CloudError('auth_unavailable','当前运行环境缺少登录依赖，请更新依赖或修复安装。') from None
        client = self.client_factory()
        try:
            yield SyncGoTrueClient(url=config.url+'/auth/v1',headers={'apikey':config.publishable_key},
                                  http_client=client,auto_refresh_token=False,persist_session=False)
        except CloudError:
            raise
        except Exception as exc:
            # SDK errors can carry request bodies/emails. Expose only our fixed text.
            code = getattr(exc,'code','')
            safe = {'otp_expired':'验证码已过期或无效，请重新获取。',
                    'over_email_send_rate_limit':'请求过于频繁，请稍后再获取验证码。',
                    'email_not_confirmed':'邮箱尚未确认，请先完成账号准备。',
                    'refresh_token_not_found':'登录已失效，请重新登录。',
                    'refresh_token_already_used':'刷新结果需要核对，请重新登录。'}
            category = 'invalid_otp' if code=='otp_expired' else 'needs_login' if getattr(exc,'status',0) in {401,403} or code in {'refresh_token_not_found','refresh_token_already_used','bad_jwt','session_not_found'} else 'auth_failed'
            raise CloudError(category,safe.get(code,'认证请求未确认，请读取原操作状态；必要时重新登录。')) from None
        finally:
            client.close()

    @staticmethod
    def _session(sdk, response):
        session = response.session
        if session is None:
            raise CloudError('auth_failed','认证服务没有返回登录会话。')
        verified = sdk.get_user(session.access_token)
        if verified is None or verified.user is None:
            raise CloudError('auth_failed','登录身份未能核实。')
        user = verified.user
        subject = str(UUID(user.id))
        if subject != str(UUID(session.user.id)) or not user.email:
            raise CloudError('identity_mismatch','登录会话和核实身份不一致，未保存。')
        return dict(user_id=subject,email=user.email,access_token=session.access_token,
                    refresh_token=session.refresh_token,expires_at=session.expires_at or int(time.time())+session.expires_in,
                    verified_at=time.time())

    def send_code(self, config, email):
        with self.sdk(config) as sdk:
            sdk.sign_in_with_otp({'email':email,'options':{'should_create_user':False}})

    def verify(self, config, email, code):
        with self.sdk(config) as sdk:
            return self._session(sdk,sdk.verify_otp({'email':email,'token':code,'type':'email'}))

    def refresh(self, config, token):
        with self.sdk(config) as sdk:
            return self._session(sdk,sdk.refresh_session(token))

    def check(self, config, session):
        with self.sdk(config) as sdk:
            verified = sdk.get_user(session['access_token'])
            if verified is None or verified.user is None or str(UUID(verified.user.id))!=session['user_id']:
                raise CloudError('identity_mismatch','登录身份与原账号不一致。')
            return {**session,'email':verified.user.email or session['email'],'verified_at':time.time()}

    def logout(self, config, token):
        with self.sdk(config) as sdk:
            # The SDK's public sign_out suppresses AuthApiError. Use its actual
            # local-session logout request so a failed revocation stays visible.
            # This accepts a regular user JWT, never an administrative key.
            sdk.admin.sign_out(token,'local')
