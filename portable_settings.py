"""Portable preferences and opt-in, password-encrypted credentials."""
from dataclasses import asdict, dataclass
import base64
import json
import math
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

_ASSOCIATED_DATA = b'EduBrain portable profile v1'
_MAX_PROFILE_BYTES = 65536


@dataclass
class Preferences:
    protocol: str = 'anthropic'
    base_url: str = 'https://api.deepseek.com/anthropic'
    model: str = 'deepseek-v4-pro'
    port: int = 5000
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: float = 30.0
    max_retries: int = 2
    cache_enabled: bool = True
    cache_expiration: int = 86400
    reasoning_effort: str = 'auto'

    @classmethod
    def from_mapping(cls, values):
        if not isinstance(values, dict):
            raise ValueError('配置必须是对象')
        allowed = cls.__dataclass_fields__
        result = cls(**{key: value for key, value in values.items() if key in allowed})
        result.validate()
        return result

    def validate(self):
        if self.protocol not in ('anthropic', 'openai_chat', 'openai_responses'):
            raise ValueError('请选择受支持的接口格式')
        if not isinstance(self.base_url, str) or len(self.base_url) > 2048 or any(ord(c) < 32 for c in self.base_url):
            raise ValueError('API 地址格式无效')
        try:
            url = urlsplit(self.base_url.strip())
            valid_url = url.scheme in ('http', 'https') and bool(url.hostname) and not url.username and not url.password and not url.query and not url.fragment
            url.port
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError('请填写完整的 HTTP/HTTPS API 基础地址，不要在地址中放入密钥或查询参数')
        self.base_url = self.base_url.strip().rstrip('/')
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 200 or any(ord(c) < 32 for c in self.model):
            raise ValueError('模型名称无效')
        self.model = self.model.strip()
        for name, lower, upper in (('port',0,65535),('max_tokens',1,131072),('max_retries',0,10),('cache_expiration',60,31536000)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise ValueError(f'{name} 超出允许范围')
        for name, lower, upper in (('temperature',0,2),('timeout',1,600)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
                raise ValueError(f'{name} 超出允许范围')
        if not isinstance(self.cache_enabled, bool):
            raise ValueError('缓存开关必须为布尔值')
        if self.reasoning_effort not in ('auto','low','medium','high','xhigh','max'):
            raise ValueError('推理档位无效')


def write_json_atomic(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent,
                                         prefix='.profile-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class ProfileStore:
    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        if not self.path.exists():
            return {'version': 1, 'preferences': {}}
        if self.path.stat().st_size > _MAX_PROFILE_BYTES:
            raise ValueError('配置文件过大')
        try:
            value = json.loads(self.path.read_text(encoding='utf-8'))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('配置文件损坏') from exc
        if not isinstance(value, dict) or value.get('version') != 1:
            raise ValueError('不支持的配置文件版本')
        return value

    def load_preferences(self):
        return Preferences.from_mapping(self._read().get('preferences', {}))

    def has_credentials(self):
        return 'encrypted_credentials' in self._read()

    @staticmethod
    def _key(password, salt):
        if not isinstance(password, str) or not 8 <= len(password) <= 256:
            raise ValueError('便携密码长度必须在 8 到 256 个字符之间')
        return Scrypt(salt=salt, length=32, n=2**17, r=8, p=1).derive(password.encode('utf-8'))

    def save(self, preferences, credentials=None, password=None):
        preferences.validate()
        result = {'version': 1, 'preferences': asdict(preferences)}
        if credentials:
            if not isinstance(credentials, dict) or set(credentials) - {'api_key','access_token'}:
                raise ValueError('凭据字段无效')
            if any(not isinstance(value, str) or len(value) > 4096 for value in credentials.values()):
                raise ValueError('凭据格式无效')
            salt, nonce = os.urandom(16), os.urandom(12)
            encrypted = AESGCM(self._key(password, salt)).encrypt(
                nonce, json.dumps(credentials).encode('utf-8'), _ASSOCIATED_DATA)
            result['encrypted_credentials'] = {
                'salt': base64.b64encode(salt).decode('ascii'),
                'nonce': base64.b64encode(nonce).decode('ascii'),
                'data': base64.b64encode(encrypted).decode('ascii'),
            }
        write_json_atomic(self.path, result)

    def unlock(self, password):
        encrypted = self._read().get('encrypted_credentials')
        if encrypted is None:
            return {}
        try:
            salt = base64.b64decode(encrypted['salt'], validate=True)
            nonce = base64.b64decode(encrypted['nonce'], validate=True)
            data = base64.b64decode(encrypted['data'], validate=True)
            if len(salt) != 16 or len(nonce) != 12 or len(data) > 16384:
                raise ValueError('Invalid encrypted profile')
            plaintext = AESGCM(self._key(password, salt)).decrypt(nonce, data, _ASSOCIATED_DATA)
            result = json.loads(plaintext)
            if not isinstance(result, dict) or set(result) - {'api_key','access_token'} or any(not isinstance(value, str) for value in result.values()):
                raise ValueError('Invalid credential data')
            return result
        except (InvalidTag, ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ValueError('便携密码错误，或加密配置已损坏') from exc
