"""Portable preferences and opt-in, password-encrypted credentials."""
from dataclasses import asdict, dataclass
import base64
import json
import math
import os
from pathlib import Path
import tempfile

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from provider_clients import SETTING_LIMITS, base_url_problem

_ASSOCIATED_DATA = b'EduBrain portable profile v1'
_MAX_PROFILE_BYTES = 65536

FIELD_LABELS = {
    'protocol': '接口协议', 'base_url': '接口基础地址', 'model': '模型标识', 'port': '本地端口',
    'max_tokens': '输出上限', 'max_retries': '重试次数', 'cache_expiration': '缓存有效秒',
    'temperature': '温度', 'timeout': '单次超时秒', 'cache_enabled': '答案缓存开关',
    'reasoning_effort': '推理强度', 'cache_persist': '缓存保存到磁盘',
}


class PreferenceError(ValueError):
    """带字段名的校验错误，界面据此定位并高亮对应输入框。"""

    def __init__(self, field, message):
        super().__init__(message)
        self.field = field


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
    cache_persist: bool = False

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
            raise PreferenceError('protocol', '请选择受支持的接口格式')
        problem = base_url_problem(self.base_url)
        if problem:
            raise PreferenceError('base_url', problem)
        self.base_url = self.base_url.strip().rstrip('/')
        if not isinstance(self.model, str) or not self.model.strip() or len(self.model) > 200 or any(ord(c) < 32 for c in self.model):
            raise PreferenceError('model', '模型标识不能为空、不能超过 200 个字符，也不能包含控制字符')
        self.model = self.model.strip()
        integer_limits = [('port', 0, 65535)] + [
            (name, *SETTING_LIMITS[name]) for name in ('max_tokens', 'max_retries', 'cache_expiration')
        ]
        for name, lower, upper in integer_limits:
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not lower <= value <= upper:
                raise PreferenceError(name, f'{FIELD_LABELS[name]}（{name}）必须是 {lower}–{upper} 之间的整数')
        for name, lower, upper in ((name, *SETTING_LIMITS[name]) for name in ('temperature', 'timeout')):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not lower <= value <= upper:
                raise PreferenceError(name, f'{FIELD_LABELS[name]}（{name}）必须是 {lower}–{upper} 之间的数字')
        if not isinstance(self.cache_enabled, bool):
            raise PreferenceError('cache_enabled', '缓存开关必须为布尔值')
        if not isinstance(self.cache_persist, bool):
            raise PreferenceError('cache_persist', '缓存保存开关必须为布尔值')
        if self.reasoning_effort not in ('auto','low','medium','high','xhigh','max'):
            raise PreferenceError('reasoning_effort', '推理档位无效')


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
        # 主文件损坏、改用 profile.json.bak 读取时置位，界面据此提示用户重新保存一次。
        self.recovered_from_backup = False

    @property
    def backup_path(self):
        return self.path.with_name(self.path.name + '.bak')

    @staticmethod
    def _read_file(path):
        if not path.exists():
            return None
        if path.stat().st_size > _MAX_PROFILE_BYTES:
            raise ValueError('配置文件过大')
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError('配置文件损坏') from exc
        if not isinstance(value, dict) or value.get('version') != 1:
            raise ValueError('不支持的配置文件版本')
        return value

    def _read(self):
        try:
            value = self._read_file(self.path)
        except ValueError:
            try:
                backup = self._read_file(self.backup_path)
            except (ValueError, OSError):
                backup = None
            if backup is None:
                raise
            self.recovered_from_backup = True
            return backup
        return value if value is not None else {'version': 1, 'preferences': {}}

    def _backup_previous(self, keep_credentials):
        """覆盖前把上一份可读的配置留作 profile.json.bak。

        本次不保存凭据（用户选择删除已保存的密钥）时，备份里的加密凭据也一并去掉，不留副本。
        """
        backup = self.backup_path
        try:
            previous = self._read_file(self.path)
        except (ValueError, OSError):
            previous = None
        if previous is not None:
            if not keep_credentials:
                previous.pop('encrypted_credentials', None)
            write_json_atomic(backup, previous)
            return
        if keep_credentials or not backup.exists():
            return
        try:
            stale = self._read_file(backup)
        except (ValueError, OSError):
            stale = None
        if stale is None:
            backup.unlink(missing_ok=True)
        elif 'encrypted_credentials' in stale:
            stale.pop('encrypted_credentials')
            write_json_atomic(backup, stale)

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
        self._backup_previous(keep_credentials=bool(credentials))
        write_json_atomic(self.path, result)
        self.recovered_from_backup = False

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
