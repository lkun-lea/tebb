from urllib.parse import urlsplit


def validate_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise RuntimeError("API 地址格式不正确，请使用服务商提供的 Base URL。") from exc
    if parts.scheme not in {"http", "https"} or not parts.hostname or any(c.isspace() for c in url):
        raise RuntimeError("API 地址必须是完整的 http:// 或 https:// 地址。")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise RuntimeError("API 地址不能包含账号、密码、查询参数或锚点，Key 请填入 API Key。")
    if parts.path.endswith(("/chat/completions", "/responses")):
        raise RuntimeError("这里填写 Base URL，请去掉末尾的 /chat/completions 或 /responses。")
    return url
