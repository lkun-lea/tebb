"""连接错误分类：保留原因类别，不把 CLI 原始输出或凭证回显给界面。"""
from __future__ import annotations

import json


class ConnectionFailure(RuntimeError):
    def __init__(self, kind: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable


def classify(value, *, verification=False, exit_code=None) -> ConnectionFailure:
    if isinstance(value, ConnectionFailure):
        return value
    if isinstance(value, dict):
        data = value.get("error") or value
        text = json.dumps(data, ensure_ascii=False).lower()
    else:
        text = str(value).lower()
        # _run_lark 的异常包含前缀，业务错误信封仍按结构识别。
        for index, char in enumerate(text):
            if char == "{":
                try:
                    envelope, _ = json.JSONDecoder().raw_decode(text[index:])
                except ValueError:
                    continue
                if isinstance(envelope, dict) and isinstance(envelope.get("error"), dict):
                    return classify(envelope, verification=verification, exit_code=exit_code)
    if any(x in text for x in ("invalid_client", "client secret is invalid", "invalid app_secret", "invalid app secret")):
        return ConnectionFailure("credentials", "飞书应用 App Secret 无效，请在「长连接设置」更新所选应用的密钥，再检查连接并重新接入。")
    if "missing_scope" in text or "permission denied" in text or "insufficient_scope" in text:
        return ConnectionFailure("permission", "机器人缺少权限，请在所选应用后台开通需要的权限并发布；用户登录不能代替机器人授权。")
    if any(x in text for x in ("not_configured", "bot capability", "bot is not enabled", "机器人能力未开启", "没有配置应用")):
        return ConnectionFailure("configuration", "飞书应用配置或机器人能力未就绪，请检查所选 CLI 应用、开启机器人能力并发布。")
    if "failed_precondition" in text or "remote exists" in text:
        return ConnectionFailure("occupied", "这个应用已有其他服务的长连接。请停止原服务，等待平台连接数归零后重试；本机 CLI 无法远程停止它。")
    if any(x in text for x in ("rate_limit", "rate limit", "too many requests", '"status": 429', '"code": 429')):
        return ConnectionFailure("rate_limit", "飞书暂时限流，等待后重试连接。", True)
    if any(x in text for x in ("network", "timeout", "timed out", "超时", "fetch failed", "econn", "enotfound", "eai_again",
                               "socket", "tls", "ssl", "eof", "connection reset", "connection refused", "connection closed",
                               "deadline exceeded", "temporarily unavailable", "internal server error", "service unavailable",
                               "server_error", "internal_error", '"type": "internal"', '"status": 500', '"status": 502',
                               '"status": 503', '"status": 504')) or exit_code in (4, 5):
        return ConnectionFailure("network", "飞书连接暂时失败，可能是网络、TLS 握手或服务暂不可用。", True)
    if verification:
        return ConnectionFailure("verification", "飞书 CLI 暂未通过机器人身份校验，尚不能判断为凭证或机器人配置失效。", True)
    return ConnectionFailure("setup", "飞书监听无法启动，请检查所选应用配置、事件订阅和机器人权限。")
