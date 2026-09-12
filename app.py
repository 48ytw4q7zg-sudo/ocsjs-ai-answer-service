# -*- coding: utf-8 -*-
"""
EduBrain AI - 智能题库系统 v2026.6.10.1739
基于 Anthropic 兼容协议的智能题库服务，支持 ccswitch 动态配置
优先通过 ccswitch 代理调用 API，自动读取 Claude Code 的实时配置
作者：QXW
版本：2026.6.10.1739
"""
from flask import Flask, request, jsonify, render_template
import time
import logging
import secrets
import hashlib
import hmac
import inspect
import ssl
import anthropic
from itsdangerous import BadSignature, URLSafeTimedSerializer
from urllib.parse import urlsplit
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import threading
from contextlib import contextmanager
import sys
from html import escape

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stderr)] if sys.stderr is not None else [logging.NullHandler()])

from config import Config, reload_config
from utils import (
    SimpleCache,
    extract_answer,
    format_answer_for_ocs,
    normalize_options,
    normalize_question_type,
    parse_question_and_options,
)
from logger import setup_logger
from provider_clients import IncompleteResponseError, portable_anthropic_headers, require_final_state

level = getattr(logging, Config.LOG_LEVEL, logging.INFO)
logger = setup_logger('ai_answer_service', log_dir=Config.LOG_DIR, level=level)

logger.info(f"配置来源: {Config.CONFIG_SOURCE}")
logger.info(f"AI 模型: {Config.ANTHROPIC_MODEL}, Base URL: {Config.ANTHROPIC_BASE_URL}")
if Config.CCSWITCH_RAW_MODEL and Config.CCSWITCH_RAW_MODEL != Config.ANTHROPIC_MODEL:
    logger.info(f"模型名已净化: '{Config.CCSWITCH_RAW_MODEL}' -> '{Config.ANTHROPIC_MODEL}'")

app = Flask(__name__)
# No CORS wildcard: OCS uses GM_xmlhttpRequest (CORS-exempt); the bundled UI is same-origin.

_BROWSER_SESSION_SECONDS = 3600
_browser_session_secret = secrets.token_bytes(32)
_browser_session_serializer = URLSafeTimedSerializer(_browser_session_secret, salt='edubrain-browser-v1')

_runtime_lock = threading.RLock()
_records_lock = threading.Lock()
cache = None
client = None
_runtime_init_error = None
_client_generations = {}
_cache_epoch = 0

MAX_RECORDS = 100
qa_records = deque(maxlen=MAX_RECORDS)
start_time = time.time()

SYSTEM_PROMPT = (
    "你是一个考试答题助手，为在线答题系统提供精准答案。\n"
    "\n"
    "## 核心规则\n"
    "1. 必须基于用户提供的具体选项来回答，不要凭记忆作答\n"
    "2. 同一道题的选项顺序可能被打乱，必须仔细比对选项内容\n"
    "3. 只输出最终答案，不要任何解释、分析、推理过程\n"
    "4. 不要输出「答案：」「答案是」「我认为」等前缀\n"
    "\n"
    "## 输出格式\n"
    "- 单选题：输出正确选项的完整文本内容（如「北京」），不是选项字母\n"
    "- 多选题：用#分隔每个正确选项的完整文本（如 北京#上海#广州）\n"
    "- 判断题：只输出「正确」或「错误」\n"
    "- 填空题：直接输出填空处的答案文本"
)

_SERVER_VERSION = "2026.6.10.1739"
_SENSITIVE_CONFIG_MARKER = "已隐藏"
_SENSITIVE_CONFIG_TERMS = (
    "TOKEN", "KEY", "SECRET", "PASSWORD", "PASS", "AUTH", "CREDENTIAL"
)
_QUESTION_FIELD_ALIASES = ('title', 'question', 'q', 'content', 'text')
_QUESTION_TYPE_FIELD_ALIASES = (
    'type', 'questionType', 'question_type', 'qtype', 'category', 'kind'
)
_OPTIONS_FIELD_ALIASES = (
    'options', 'choices', 'answers', 'answerOptions', 'option', 'opts'
)


def _extract_access_token(req):
    """从请求头、查询参数、表单及 JSON Body 中提取访问令牌。"""
    token = req.headers.get('X-Access-Token')
    if token:
        return token.strip()

    auth_header = req.headers.get('Authorization')
    if auth_header:
        if auth_header.startswith('Bearer '):
            token = auth_header[7:].strip()
        else:
            token = auth_header.strip()
        if token:
            return token

    token = req.args.get('token') or req.args.get('access_token')
    if token:
        return str(token).strip()

    token = req.form.get('token') or req.form.get('access_token')
    if token:
        return str(token).strip()

    if req.is_json:
        data = req.get_json(silent=True)
        if isinstance(data, dict):
            token = data.get('token') or data.get('access_token')
            if token:
                return str(token).strip()
    return None


class _ClientGeneration:
    def __init__(self, active_client):
        self.client = active_client
        self.active_calls = 0
        self.retired = False


def _close_ai_client(active_client):
    if active_client is None or not hasattr(active_client, 'close'):
        return
    try:
        active_client.close()
    except Exception as exc:
        logger.warning("AI client close failed: %s", type(exc).__name__)


@contextmanager
def _client_lease():
    # Register the call before releasing the lock, including attribute lookup
    # and request construction. Network I/O itself remains concurrent.
    with _runtime_lock:
        active_client = client
        if active_client is None:
            raise RuntimeError("AI runtime is unavailable")
        key = id(active_client)
        generation = _client_generations.get(key)
        if generation is None:
            generation = _ClientGeneration(active_client)
            _client_generations[key] = generation
        generation.active_calls += 1
        active_model = Config.ANTHROPIC_MODEL
    try:
        yield active_client, active_model
    finally:
        close_client = None
        with _runtime_lock:
            generation.active_calls -= 1
            if generation.retired and generation.active_calls == 0:
                _client_generations.pop(key, None)
                close_client = generation.client
        _close_ai_client(close_client)


def _retire_client(active_client):
    # The caller holds the runtime lock while publishing the replacement.
    generation = _client_generations.get(id(active_client))
    if generation is None:
        _close_ai_client(active_client)
        return
    generation.retired = True
    if generation.active_calls == 0:
        _client_generations.pop(id(active_client), None)
        _close_ai_client(active_client)


def _runtime_initialize():
    """Publish a complete runtime, then retire the previous client."""
    global _runtime_init_error, client, cache, _cache_epoch
    with _runtime_lock:
        candidate_client = None
        try:
            candidate_client = build_ai_client()
            candidate_cache = SimpleCache(Config.CACHE_EXPIRATION) if Config.ENABLE_CACHE else None
        except Exception as exc:
            if candidate_client is not client:
                _close_ai_client(candidate_client)
            if client is None:
                _runtime_init_error = type(exc).__name__
            logger.error("运行时重建失败: %s", type(exc).__name__)
            raise
        previous_client = client
        client, cache = candidate_client, candidate_cache
        _cache_epoch += 1
        _runtime_init_error = None
        if previous_client is not None and previous_client is not client:
            _retire_client(previous_client)


def _initialize_runtime_if_needed() -> bool:
    """按需重建运行时组件，失败时返回 False。"""
    with _runtime_lock:
        if _is_runtime_ready():
            return True
        try:
            _runtime_initialize()
            return client is not None
        except Exception as exc:
            logger.error("AI 运行时当前不可用: %s", type(exc).__name__)
            return False


def _is_runtime_ready() -> bool:
    return client is not None and _runtime_init_error is None


def _runtime_info():
    """返回运行时状态摘要。"""
    with _runtime_lock:
        with _records_lock:
            records = list(qa_records)
        return {
            'ready': _is_runtime_ready(),
            'error': _runtime_init_error,
            'model': Config.ANTHROPIC_MODEL,
            'base_url': Config.ANTHROPIC_BASE_URL,
            'config_source': Config.CONFIG_SOURCE,
            'config_loaded_at': Config.CONFIG_LOADED_AT,
            'cache_enabled': Config.ENABLE_CACHE,
            'cache_size': len(cache) if cache is not None else 0,
            'uptime_seconds': round(time.time() - start_time, 2),
            'ccswitch': _build_ccswitch_payload(),
            'is_proxy': Config.CCSWITCH_IS_PROXY,
            'records': records,
        }


def _error_response(message: str, status_code: int = 400):
    return jsonify({'code': 0, 'msg': message}), status_code


def _browser_cookie_name(req):
    return 'edubrain_session_' + hashlib.sha256(req.host.encode('utf-8')).hexdigest()[:12]


def _browser_request_is_local_origin(req):
    fetch_site = req.headers.get('Sec-Fetch-Site')
    if fetch_site and fetch_site not in ('same-origin', 'none'):
        return False
    if fetch_site == 'none' and req.method not in ('GET', 'HEAD'):
        return False
    origin = req.headers.get('Origin')
    if origin:
        try:
            parsed = urlsplit(origin)
            if parsed.scheme not in ('http', 'https') or parsed.netloc.lower() != req.host.lower():
                return False
            if req.is_secure and parsed.scheme != 'https':
                return False
        except ValueError:
            return False
    return True


def _browser_session_binding(token):
    return hmac.new(_browser_session_secret, str(token).encode('utf-8'), hashlib.sha256).hexdigest()


def _verify_browser_session(req, expected):
    if not _browser_request_is_local_origin(req):
        return False
    try:
        cookie = req.cookies.get(_browser_cookie_name(req))
        if not cookie:
            return False
        value = _browser_session_serializer.loads(cookie, max_age=_BROWSER_SESSION_SECONDS)
        return (isinstance(value, dict) and value.get('host') == req.host
                and isinstance(value.get('binding'), str)
                and secrets.compare_digest(value['binding'], _browser_session_binding(expected)))
    except (BadSignature, UnicodeError, ValueError, TypeError):
        return False


def verify_access_token(req):
    expected = Config.ACCESS_TOKEN
    if expected:
        token = _extract_access_token(req)
        if token is None:
            return _verify_browser_session(req, expected)
        if not isinstance(token, str) or not token:
            return False
        try:
            return secrets.compare_digest(token.encode('utf-8'), str(expected).encode('utf-8'))
        except UnicodeEncodeError:
            return False
    return True


@app.route('/api/session', methods=['POST'])
def create_browser_session():
    if not _browser_request_is_local_origin(request):
        return _error_response('仅允许当前网页建立浏览器会话', 403)
    with _runtime_lock:
        if not verify_access_token(request):
            return _error_response('无效的访问令牌', 403)
        response = jsonify({'code': 1, 'msg': '浏览器会话已建立'})
        response.headers['Cache-Control'] = 'no-store'
        if Config.ACCESS_TOKEN:
            # The cookie contains a run-specific proof, never the reusable token.
            value = _browser_session_serializer.dumps({
                'host': request.host, 'binding': _browser_session_binding(Config.ACCESS_TOKEN),
            })
            response.set_cookie(_browser_cookie_name(request), value, max_age=_BROWSER_SESSION_SECONDS,
                                httponly=True, secure=request.is_secure, samesite='Strict')
        return response


def _mask_sensitive_config(config_values):
    safe_values = {}
    for key, value in (config_values or {}).items():
        upper_key = str(key).upper()
        if any(term in upper_key for term in _SENSITIVE_CONFIG_TERMS):
            safe_values[key] = _SENSITIVE_CONFIG_MARKER
        else:
            safe_values[key] = value
    return safe_values


def _build_ccswitch_payload():
    if Config.CONFIG_SOURCE != 'ccswitch':
        return None

    extra_env = _mask_sensitive_config(Config.EXTRA_ENV) if Config.EXTRA_ENV else {}
    model_sanitized = bool(
        Config.CCSWITCH_RAW_MODEL and Config.CCSWITCH_RAW_MODEL != Config.ANTHROPIC_MODEL
    )
    return {
        'raw_model': Config.CCSWITCH_RAW_MODEL,
        'sanitized_model': Config.ANTHROPIC_MODEL,
        'is_proxy': Config.CCSWITCH_IS_PROXY,
        'model_sanitized': model_sanitized,
        'config_keys': list(extra_env.keys()) if extra_env else [],
        'extra_env': extra_env,
    }


def _first_non_empty_value(values, *keys):
    for key in keys:
        value = values.get(key, '')
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return value
    return ''


def build_ai_client():
    if not Config.ANTHROPIC_API_KEY:
        raise ValueError('未配置 AI API 密钥')
    if Config.API_PROTOCOL != 'anthropic':
        from provider_clients import OpenAICompatibleClient
        return OpenAICompatibleClient(
            api_key=Config.ANTHROPIC_API_KEY, base_url=Config.ANTHROPIC_BASE_URL,
            protocol=Config.API_PROTOCOL, timeout=Config.API_TIMEOUT,
            max_retries=Config.API_MAX_RETRIES, reasoning_effort=Config.REASONING_EFFORT,
        )
    extra = {}
    if Config.IS_PORTABLE:
        import certifi
        extra['http_client'] = anthropic.DefaultHttpxClient(
            verify=ssl.create_default_context(cafile=certifi.where()), trust_env=False)
        # Explicit auth and public header omissions are per-client settings;
        # the host environment is never temporarily rewritten.
        extra['auth_token'] = ''
        extra['default_headers'] = portable_anthropic_headers(Config.ANTHROPIC_API_KEY)
    try:
        return anthropic.Anthropic(
            api_key=Config.ANTHROPIC_API_KEY,
            base_url=Config.ANTHROPIC_BASE_URL,
            timeout=Config.API_TIMEOUT,
            max_retries=Config.API_MAX_RETRIES,
            **extra,
        )
    except Exception:
        _close_ai_client(extra.get('http_client'))
        raise


def _extract_text_from_response(response):
    """从 AI 响应中安全提取文本内容。

    遍历所有 content block，返回第一个 TextBlock 的文本。
    兼容 DeepSeek Anthropic 层可能返回非标准 block 结构的情况。
    """
    require_final_state(getattr(response, 'stop_reason', None), ('end_turn', 'stop_sequence'))
    require_final_state(getattr(response, 'status', None), ('completed',))
    content = response.content
    if not content:
        logger.warning("AI 响应 content 为空列表")
        return None
    # A text block before a tool request is not a completed text-only answer.
    if any(getattr(block, 'type', None) == 'tool_use' for block in content):
        raise IncompleteResponseError()
    for i, block in enumerate(content):
        block_type = getattr(block, 'type', 'unknown')
        if hasattr(block, 'text') and block.text and block.text.strip():
            if i > 0:
                logger.info(f"从 content[{i}] 获取文本 (type={block_type})")
            return block.text.strip()
        elif block_type != 'text':
            logger.debug(f"跳过非文本 block[{i}]: type={block_type}")
    logger.warning("AI 响应所有 block 均无有效文本")
    return None


def _safe_http_status(exc):
    status = getattr(exc, 'status_code', None)
    return status if isinstance(status, int) and not isinstance(status, bool) and 100 <= status <= 599 else None


def _call_ai(prompt: str, max_tokens=None):
    """Call the current client with a lease covering the complete operation."""
    if not _initialize_runtime_if_needed():
        raise RuntimeError("AI 运行时未就绪")
    with _runtime_lock:
        token_limit = Config.MAX_TOKENS if max_tokens is None else max_tokens
        base_temperature = Config.TEMPERATURE
    for attempt in range(2):
        try:
            current_prompt = _build_simple_prompt(prompt) if attempt else prompt
            current_temperature = 0.3 if attempt else base_temperature
            with _client_lease() as (active_client, active_model):
                create_message = active_client.messages.create
                parameters = inspect.signature(create_message).parameters
                message_arguments = {
                    'model': active_model, 'max_tokens': token_limit,
                    'system': SYSTEM_PROMPT,
                    'messages': [{"role": "user", "content": current_prompt}],
                }
                # SDKs that removed temperature must not receive it.
                if 'temperature' in parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in parameters.values()):
                    message_arguments['temperature'] = current_temperature
                response = create_message(**message_arguments)
                text = _extract_text_from_response(response)
                if text:
                    return text
        except (anthropic.APIStatusError, anthropic.APITimeoutError, anthropic.APIConnectionError) as exc:
            logger.warning("API call failed (attempt=%s, type=%s, status=%s)",
                           attempt + 1, type(exc).__name__, _safe_http_status(exc))
            if attempt == 1:
                raise
        if attempt == 0:
            logger.warning("第 1 次调用无有效文本，1 秒后重试...")
            time.sleep(1)
    return None


def _build_simple_prompt(original_prompt: str) -> str:
    """从复杂提示词中提取题目和选项，构建极简版提示。

    当完整提示词无法获得有效回答时使用，去除所有复杂指令。
    """
    # 提取【题型】行和选项行
    lines = original_prompt.split('\n')
    simple = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # 跳过复杂指令段落
        if any(skip in stripped for skip in [
            '请仔细阅读', '注意：', '不要输出', '只输出',
            '这是一道', '用 # 号', '不是字母', '候选选项',
        ]):
            continue
        simple.append(stripped)

    result = '\n'.join(simple) if simple else original_prompt
    if result != original_prompt:
        logger.debug(f"简化提示词: {result[:120]}...")
    return result


@app.route('/api/search', methods=['GET', 'POST'])
def search():
    t_start = time.time()

    if not verify_access_token(request):
        return _error_response('无效的访问令牌', 403)

    try:
        if request.method == 'GET':
            question = _first_non_empty_value(request.args, *_QUESTION_FIELD_ALIASES)
            question_type = _first_non_empty_value(request.args, *_QUESTION_TYPE_FIELD_ALIASES)
            options = _first_non_empty_value(request.args, *_OPTIONS_FIELD_ALIASES)
        else:
            if request.is_json:
                data = request.get_json(silent=True)
                if data is None:
                    return _error_response('无效的JSON格式', 400)
                if not isinstance(data, dict):
                    return _error_response('JSON请求体必须是对象', 400)
                question = _first_non_empty_value(data, *_QUESTION_FIELD_ALIASES)
                question_type = _first_non_empty_value(data, *_QUESTION_TYPE_FIELD_ALIASES)
                options = _first_non_empty_value(data, *_OPTIONS_FIELD_ALIASES)
            else:
                question = _first_non_empty_value(request.form, *_QUESTION_FIELD_ALIASES)
                question_type = _first_non_empty_value(request.form, *_QUESTION_TYPE_FIELD_ALIASES)
                options = _first_non_empty_value(request.form, *_OPTIONS_FIELD_ALIASES)

        if isinstance(question, (dict, list, tuple, bool)):
            return _error_response('问题内容必须是文本', 400)
        question = "" if question is None else str(question).strip()
        if not question:
            logger.warning("未提供问题内容")
            return _error_response('未提供问题内容', 400)

        question_type = normalize_question_type(question_type)
        options = normalize_options(options)
        if len(question) > Config.MAX_QUESTION_LENGTH:
            return _error_response(f'问题内容过长，最大{Config.MAX_QUESTION_LENGTH}字符', 400)

        if not _initialize_runtime_if_needed():
            return _error_response('AI 运行时未就绪，请稍后重试', 503)

        logger.info("接收到问题 (长度: %s, 类型: %s, 有选项: %s)", len(question), question_type, bool(options))

        with _runtime_lock:
            request_cache = cache
            request_cache_epoch = _cache_epoch
        if request_cache is not None:
            cached_answer = request_cache.get(question, question_type, options)
            if cached_answer:
                elapsed = time.time() - t_start
                logger.info(f"从缓存获取答案 (耗时: {elapsed:.2f}秒)")
                return jsonify(format_answer_for_ocs(question, cached_answer))

        full_prompt = parse_question_and_options(question, options, question_type)
        logger.debug("AI 提示词长度: %s", len(full_prompt))

        ai_answer = _call_ai(full_prompt)
        if ai_answer is None:
            return _error_response('AI 未返回有效答案，请重试', 503)

        processed_answer = extract_answer(ai_answer, question_type, options)
        if not processed_answer:
            return _error_response('AI 未返回有效答案，请重试', 503)

        with _runtime_lock:
            if request_cache is cache and request_cache is not None and request_cache_epoch == _cache_epoch:
                request_cache.set(question, processed_answer, question_type, options)

        current_time = datetime.now(timezone.utc)
        with _records_lock:
            qa_records.append({
                'time': current_time.strftime('%Y-%m-%d %H:%M:%S'),
                'timestamp': current_time.isoformat(),
                'question': question,
                'type': question_type or '未指定',
                'options': options,
                'answer': processed_answer,
            })

        elapsed = time.time() - t_start
        logger.info("完成 (耗时: %.2f秒, 答案长度: %s)", elapsed, len(processed_answer))

        return jsonify(format_answer_for_ocs(question, processed_answer))

    except IncompleteResponseError:
        logger.warning("Provider response was incomplete")
        return jsonify({'code': 0, 'msg': 'AI回答未完成，请重试或调整输出上限',
                        'error_code': 'incomplete_response'}), 503

    except anthropic.APIStatusError as exc:
        status = _safe_http_status(exc)
        logger.error("API request failed (type=%s, status=%s)", type(exc).__name__, status)
        message = f'AI服务暂时不可用 (HTTP {status})' if status is not None else 'AI服务暂时不可用'
        return _error_response(message, 503)

    except anthropic.APITimeoutError:
        logger.error("API 请求超时")
        return _error_response('AI服务响应超时，请重试', 504)

    except anthropic.APIConnectionError:
        logger.error("API 连接失败")
        return _error_response('无法连接到AI服务', 502)

    except RuntimeError as e:
        logger.error("AI 运行时尚未就绪: %s", type(e).__name__)
        return _error_response('AI 运行时未就绪，请稍后重试', 503)

    except Exception as e:
        logger.error("处理问题时发生错误: %s", type(e).__name__)
        return jsonify({'code': 0, 'msg': '服务内部错误'}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    runtime_info = _runtime_info()
    status = 'ok' if runtime_info['ready'] else 'degraded'
    message = (
        'AI题库服务运行正常'
        if runtime_info['ready'] else
        'AI题库服务运行中，但 AI 运行时未就绪'
    )
    public_result = {
        'status': status,
        'message': message,
        'version': _SERVER_VERSION,
        'runtime_ready': runtime_info['ready'],
        'runtime_error': runtime_info['error'],
        'cache_enabled': runtime_info['cache_enabled'],
        'cache_size': runtime_info['cache_size'],
        'uptime_seconds': runtime_info['uptime_seconds'],
        'details': 'protected',
    }
    if verify_access_token(request):
        public_result.update({
            'config_source': runtime_info['config_source'],
            'config_loaded_at': runtime_info['config_loaded_at'],
            'model': runtime_info['model'],
            'base_url': runtime_info['base_url'],
        })
        del public_result['details']
        if runtime_info['config_source'] == 'ccswitch':
            ccswitch_payload = runtime_info['ccswitch']
            if ccswitch_payload:
                public_result['ccswitch'] = ccswitch_payload
                public_result['config_keys'] = ccswitch_payload.get('config_keys', [])
            else:
                public_result['config_keys'] = []
        else:
            public_result['config_keys'] = []
    return jsonify(public_result)


@app.route('/api/config/reload', methods=['POST'])
def config_reload():
    if not verify_access_token(request):
        return jsonify({'success': False, 'message': '无效的访问令牌'}), 403
    with _runtime_lock:
        previous_config = {key: value for key, value in vars(Config).items() if key.isupper()}
        try:
            loaded_from_ccswitch = reload_config()
            _runtime_initialize()
        except Exception as exc:
            for key, value in previous_config.items():
                setattr(Config, key, value)
            logger.error("配置重载失败，已保留原配置: %s", type(exc).__name__)
            return jsonify({
                'success': False,
                'message': '配置重载失败，已保留原配置和可用运行时',
                'config_source': Config.CONFIG_SOURCE,
                'runtime_ready': _is_runtime_ready(),
                'runtime_error': type(exc).__name__,
            }), 500

    runtime_info = _runtime_info()
    if runtime_info['config_source'] == 'portable':
        message = '已重新应用当前便携配置'
    elif loaded_from_ccswitch:
        logger.info(f"配置已重新加载: model={Config.ANTHROPIC_MODEL}, base_url={Config.ANTHROPIC_BASE_URL}")
        message = '配置已从 ccswitch 重新加载'
        if not runtime_info['ready']:
            message = '配置已从 ccswitch 重新加载，但运行时当前未就绪'
    else:
        logger.info(f"配置已回退到 .env 并重建客户端: model={Config.ANTHROPIC_MODEL}, base_url={Config.ANTHROPIC_BASE_URL}")
        message = 'ccswitch 不可用，已回退到 .env 配置'
        if not runtime_info['ready']:
            message = 'ccswitch 不可用，已回退到 .env 配置，但运行时当前未就绪'

    ccswitch_payload = runtime_info['ccswitch']

    return jsonify({
        'success': True, 'message': message,
        'config_source': runtime_info['config_source'],
        'model': runtime_info['model'],
        'base_url': runtime_info['base_url'],
        'sanitized_model': runtime_info['model'],
        'runtime_ready': runtime_info['ready'],
        'runtime_error': runtime_info['error'],
        'runtime_uptime_seconds': runtime_info['uptime_seconds'],
        'runtime_cache_size': runtime_info['cache_size'],
        'is_proxy': runtime_info['is_proxy'],
        'config_keys': ccswitch_payload.get('config_keys', []) if ccswitch_payload else [],
        'ccswitch': ccswitch_payload,
    })


@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    global _cache_epoch
    if not verify_access_token(request):
        return jsonify({'success': False, 'message': '无效的访问令牌'}), 403
    with _runtime_lock:
        active_cache = cache
        if active_cache is None:
            return jsonify({'success': False, 'message': '缓存未启用'}), 409
        count = active_cache.clear()
        _cache_epoch += 1
    return jsonify({'success': True, 'message': f'缓存已清除 ({count}条)', 'count': count})


@app.route('/api/stats', methods=['GET'])
def get_stats():
    if not verify_access_token(request):
        return jsonify({'success': False, 'message': '无效的访问令牌'}), 403
    runtime_info = _runtime_info()
    stats = {
        'version': _SERVER_VERSION,
        'config_source': runtime_info['config_source'],
        'uptime': runtime_info['uptime_seconds'],
        'runtime_ready': runtime_info['ready'],
        'runtime_error': runtime_info['error'],
        'model': runtime_info['model'],
        'config_loaded_at': runtime_info['config_loaded_at'],
        'base_url': runtime_info['base_url'],
        'cache_enabled': runtime_info['cache_enabled'],
        'cache_size': runtime_info['cache_size'],
        'qa_records_count': len(runtime_info['records']),
    }
    ccswitch_payload = runtime_info['ccswitch']
    if ccswitch_payload:
        stats['ccswitch'] = ccswitch_payload
        stats['config_keys'] = ccswitch_payload.get('config_keys', [])
    else:
        stats['config_keys'] = []
    return jsonify(stats)


@app.route('/dashboard', methods=['GET'])
def dashboard():
    if not verify_access_token(request):
        return '无效的访问令牌', 403

    uptime_seconds = time.time() - start_time
    runtime_info = _runtime_info()
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    uptime_str = f"{days}天{hours}小时{minutes}分钟"
    ccswitch_info = runtime_info['ccswitch']
    return render_template(
        'dashboard.html', version=_SERVER_VERSION, config_source=runtime_info['config_source'],
        cache_enabled=runtime_info['cache_enabled'],
        cache_size=runtime_info['cache_size'],
        runtime_ready=runtime_info['ready'],
        runtime_error=runtime_info['error'],
        runtime_uptime_seconds=runtime_info['uptime_seconds'],
        config_loaded_at=runtime_info['config_loaded_at'],
        runtime_model=runtime_info['model'],
        runtime_base_url=runtime_info['base_url'],
        model=runtime_info['model'], uptime=uptime_str, records=runtime_info['records'],
        ccswitch_info=ccswitch_info,
    )


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html', version=_SERVER_VERSION)


@app.route('/docs', methods=['GET'])
def docs():
    doc_path = Path(__file__).with_name('api_docs.md')
    try:
        content = doc_path.read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError) as exc:
        logger.error("加载 API 文档失败: %s", type(exc).__name__)
        return "API文档文件不存在或不可访问", 500

    try:
        import markdown
        # Local api_docs.md is trusted content; keep the no-markdown fallback escaped.
        html_content = markdown.markdown(content, extensions=['tables'])
        return f"""<html><head><title>AI题库服务 - API文档 v{_SERVER_VERSION}</title>
<style>body{{font-family:Arial,sans-serif;margin:40px;line-height:1.6}}h1,h2,h3{{color:#2c3e50}}.container{{max-width:800px;margin:0 auto}}code{{background:#e0e0e0;padding:2px 4px;border-radius:3px}}pre{{background:#f4f4f4;padding:10px;border-radius:4px;overflow-x:auto}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px}}th{{background-color:#f4f4f4}}</style></head>
<body><div class="container">{html_content}</div></body></html>"""
    except ImportError:
        return f"""<html><head><title>AI题库服务 - API文档 v{_SERVER_VERSION}</title>
<style>body{{font-family:Arial,sans-serif;margin:40px;line-height:1.6}}h1{{color:#333}}.container{{max-width:800px;margin:0 auto}}pre{{background:#f4f4f4;padding:10px;border-radius:4px;overflow-x:auto}}</style></head>
 <body><div class="container"><h1>AI题库服务 - API文档 v{_SERVER_VERSION}</h1><pre>{escape(content)}</pre></div></body></html>"""


_initialize_runtime_if_needed()

_LOOPBACK_HOSTS = {'127.0.0.1', 'localhost', '::1', '[::1]'}
if Config.HOST.strip('[]') not in _LOOPBACK_HOSTS and not Config.ACCESS_TOKEN:
    logger.warning(
        'HOST=%s 不是回环地址且未设置 ACCESS_TOKEN；请仅在可信网络使用，或设置 ACCESS_TOKEN',
        Config.HOST,
    )


if __name__ == '__main__':
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
