"""SDK-free provider settings shared by config, ccswitch, portable settings and provider clients.

Kept apart from provider_clients.py so that importing config (for example from healthcheck.py)
does not load the anthropic/httpx/pydantic stack.
"""
import re
from urllib.parse import urlsplit


# 模型名后缀净化规则（表驱动）：去掉 ccswitch/客户端附加的上下文长度标记，如 [1M]、[200K]、[128k]。
MODEL_SUFFIX_PATTERNS = (
    re.compile(r'\s*\[\d+(?:\.\d+)?\s*[KM]?\]', re.I),
)


# 服务端 .env 与便携版设置共用的可选值与取值范围，两边不再各写一份校验规则。
SUPPORTED_PROTOCOLS = ('anthropic', 'openai_chat', 'openai_responses')
REASONING_EFFORTS = ('auto', 'low', 'medium', 'high', 'xhigh', 'max')
SETTING_LIMITS = {
    'max_tokens': (1, 131072),
    'temperature': (0, 2),
    'timeout': (1, 600),
    'max_retries': (0, 10),
    'cache_expiration': (60, 31536000),
}
_BASE_URL_HINT = '请填写完整的 HTTP/HTTPS API 基础地址（含 http:// 或 https://），不要在地址中放入密钥或查询参数'


def base_url_problem(url):
    """接口基础地址的问题描述；合法时返回 None（服务端配置与便携设置共用）。"""
    if not isinstance(url, str) or not url.strip() or len(url) > 2048 or any(ord(c) < 32 for c in url):
        return 'API 地址格式无效'
    try:
        parsed = urlsplit(url.strip())
        parsed.port
    except ValueError:
        return _BASE_URL_HINT
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        return _BASE_URL_HINT
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return _BASE_URL_HINT
    return None


def sanitize_model_name(model):
    """返回服务商可识别的模型名；原始值由调用方另行记录（raw_model）。"""
    cleaned = str(model or '')
    for pattern in MODEL_SUFFIX_PATTERNS:
        cleaned = pattern.sub('', cleaned)
    return cleaned.strip()
