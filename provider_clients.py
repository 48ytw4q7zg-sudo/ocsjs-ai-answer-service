"""Text-only OpenAI protocol adapters with the service's Anthropic-shaped interface."""
import re
import time
from types import SimpleNamespace

import anthropic
import certifi
import httpx


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
        model = re.sub(r'\[\d+[KM]?\]$', '', model, flags=re.I)
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
                raise anthropic.APIConnectionError(message='Provider returned an invalid response', request=request) from exc
            time.sleep(min(0.5 * 2 ** attempt, 4))

    def _extract_text(self, data):
        if self.protocol == 'openai_chat':
            choices = data.get('choices') or []
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                return ''
            message = choices[0].get('message') or {}
            if not isinstance(message, dict):
                return ''
            content = message.get('content')
            if isinstance(content, str):
                return content.strip()
            if isinstance(content, list):
                return '\n'.join(part['text'] for part in content
                                 if isinstance(part, dict) and isinstance(part.get('text'), str)).strip()
            return ''
        parts = []
        for item in data.get('output') or []:
            if not isinstance(item, dict) or item.get('type') != 'message':
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
