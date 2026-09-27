"""Text-only OpenAI protocol adapters with the service's Anthropic-shaped interface."""
import re
import os
import time
from types import SimpleNamespace
from urllib.parse import urlsplit

import anthropic
import certifi
import httpx


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


class IncompleteResponseError(RuntimeError):
    def __init__(self):
        super().__init__("Provider response was incomplete")


class ProviderResponseError(anthropic.APIConnectionError):
    """上游返回了无法解析的响应（非 JSON 或结构不对），多半是接口地址或协议选错；重试没有意义。"""


def require_final_state(state, allowed):
    """Missing optional markers are compatible; explicit states fail closed."""
    if state is not None and (not isinstance(state, str) or state not in allowed):
        raise IncompleteResponseError()


def portable_anthropic_headers(api_key):
    """Replace SDK environment headers using its public omission mechanism."""
    required = {
        'x-api-key': api_key,
        'authorization': anthropic.omit,
        'proxy-authorization': anthropic.omit,
        'anthropic-version': '2023-06-01',
        'content-type': 'application/json',
        'accept': 'application/json',
    }
    headers = {}
    # Replace each original spelling, including duplicate case variants, so
    # constructor dictionary ordering cannot restore an ambient credential.
    for line in os.environ.get('ANTHROPIC_CUSTOM_HEADERS', '').split('\n'):
        if ':' in line:
            name = line.split(':', 1)[0].strip()
            headers[name] = required.get(name.lower(), anthropic.omit)
    headers.update(required)
    return headers


class OpenAICompatibleClient:
    def __init__(self, api_key, base_url, protocol, timeout=30, max_retries=2,
                 reasoning_effort='auto', http_client=None):
        if protocol not in ('openai_chat', 'openai_responses'):
            raise ValueError('Unsupported API protocol')
        self.protocol = protocol
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.max_retries = max(0, min(10, int(max_retries)))
        self.reasoning_effort = reasoning_effort
        self._client = http_client or httpx.Client(timeout=timeout, verify=certifi.where(), trust_env=False)

    @property
    def messages(self):
        return self

    def create(self, *, model, max_tokens, temperature, system, messages):
        model = sanitize_model_name(model)
        if self.protocol == 'openai_responses':
            url = self.base_url + '/responses'
            payload = {'model': model, 'input': messages, 'instructions': system,
                       'max_output_tokens': max_tokens, 'store': False}
            if self.reasoning_effort != 'auto':
                payload['reasoning'] = {'effort': self.reasoning_effort}
        else:
            url = self.base_url + '/chat/completions'
            payload = {'model': model, 'messages': [{'role': 'system', 'content': system}, *messages]}
            reasoning_model = model.split('/')[-1].startswith(('gpt-5', 'gpt-6', 'o1', 'o3', 'o4'))
            payload['max_completion_tokens' if reasoning_model else 'max_tokens'] = max_tokens
            if not reasoning_model:
                payload['temperature'] = temperature
            if self.reasoning_effort != 'auto':
                payload['reasoning_effort'] = self.reasoning_effort

        request = httpx.Request('POST', url)
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.post(url, json=payload,
                                             headers={'Authorization': 'Bearer ' + self.api_key})
                if response.status_code >= 400:
                    error = anthropic.APIStatusError(f'Upstream HTTP {response.status_code}',
                                                     response=response, body=None)
                    if attempt < self.max_retries and (response.status_code == 429 or response.status_code >= 500):
                        time.sleep(min(0.5 * 2 ** attempt, 4))
                        continue
                    raise error
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError('Unexpected response shape')
                text = self._extract_text(data)
                return SimpleNamespace(content=[SimpleNamespace(type='text', text=text)] if text else [])
            except httpx.TimeoutException as exc:
                error = anthropic.APITimeoutError(request=request)
                if attempt == self.max_retries:
                    raise error from exc
            except httpx.RequestError as exc:
                error = anthropic.APIConnectionError(message='Unable to reach the configured provider', request=request)
                if attempt == self.max_retries:
                    raise error from exc
            except ValueError as exc:
                raise ProviderResponseError(message='Provider returned an invalid response', request=request) from exc
            time.sleep(min(0.5 * 2 ** attempt, 4))
        raise anthropic.APIConnectionError(message='Provider request exhausted retries', request=request)

    def _extract_text(self, data):
        if self.protocol == 'openai_chat':
            choices = data.get('choices') or []
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                return ''
            require_final_state(choices[0].get('finish_reason'), ('stop',))
            message = choices[0].get('message') or {}
            if not isinstance(message, dict):
                return ''
            if message.get('tool_calls') or message.get('function_call'):
                raise IncompleteResponseError()
            content = message.get('content')
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                return '\n'.join(part['text'] for part in content
                                 if isinstance(part, dict) and isinstance(part.get('text'), str)).strip()
            return ''
        require_final_state(data.get('status'), ('completed',))
        if data.get('incomplete_details'):
            raise IncompleteResponseError()
        parts = []
        for item in data.get('output') or []:
            if not isinstance(item, dict):
                continue
            require_final_state(item.get('status'), ('completed',))
            # These items hand work back to a caller; completing their arguments
            # does not complete the answer for this text-only adapter.
            if item.get('type') in (
                'function_call', 'custom_tool_call', 'computer_call',
                'local_shell_call', 'shell_call', 'apply_patch_call', 'mcp_approval_request',
            ):
                raise IncompleteResponseError()
            if item.get('type') != 'message':
                continue
            for part in item.get('content') or []:
                if isinstance(part, dict) and part.get('type') == 'output_text' and isinstance(part.get('text'), str):
                    parts.append(part['text'])
        if not parts and isinstance(data.get('output_text'), str):
            parts.append(data['output_text'])
        return '\n'.join(parts).strip()

    def close(self):
        self._client.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
