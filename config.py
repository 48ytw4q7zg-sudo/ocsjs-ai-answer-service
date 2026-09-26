# -*- coding: utf-8 -*-
"""
配置模块 v2026.6.10.1739
优先从 ccswitch (Claude Code settings.json) 读取 API 设置，
未检测到有效配置时自动回退到 .env 文件。
新增：运行时重载、配置来源时间戳、DeepSeek 优化参数。
"""
import os
import time
import logging
import math
from dotenv import load_dotenv

from ccswitch import CcswitchUnreadableError, get_ccswitch_config, reload_ccswitch_config
from portable_paths import is_portable, data_root

logger = logging.getLogger(__name__)

PORTABLE_MODE = is_portable()

if not PORTABLE_MODE:
    load_dotenv(override=True)


def _environment_value(name):
    return None if PORTABLE_MODE else os.getenv(name)


def _ccswitch_enabled() -> bool:
    """服务模式默认读取 ~/.claude/settings.json；CCSWITCH_ENABLED=false 可关闭。便携模式从不读取。"""
    if PORTABLE_MODE:
        return False
    value = _environment_value("CCSWITCH_ENABLED")
    return value is None or str(value).strip().lower() not in {"0", "false", "no", "off", "n"}


def request_budget_seconds(api_timeout: float, max_retries: int) -> float:
    """一次 /api/search 最坏耗时：两轮提示词 × (1 + SDK 重试次数) × 单次超时。

    gunicorn worker 超时与便携控制器的等待时间都以此为基准再加余量，保持同一张超时表。
    """
    return float(api_timeout) * (int(max_retries) + 1) * 2


# 尝试从 ccswitch 获取配置（优先）
_ccswitch = get_ccswitch_config() if _ccswitch_enabled() else None
_config_loaded_at = time.time()


def _env_str(name: str, default: str) -> str:
    value = _environment_value(name)
    return value.strip() if isinstance(value, str) and value.strip() else default


def _env_bool(name: str, default: bool) -> bool:
    value = _environment_value(name)
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on", "y"}:
        return True
    if normalized in {"0", "false", "no", "off", "n"}:
        return False
    logger.warning(
        "配置项 %s 的值 %r 无法解析为布尔类型，已使用默认值 %s",
        name,
        value,
        default,
    )
    return default


def _env_int(name: str, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
    value = _environment_value(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        logger.warning("配置项 %s 的值 %r 无法解析为整数，已使用默认值 %s", name, value, default)
        return default
    if min_value is not None and parsed < min_value:
        logger.warning(
            "配置项 %s 的值 %s 小于下限 %s，已使用默认值 %s",
            name,
            parsed,
            min_value,
            default,
        )
        return default
    if max_value is not None and parsed > max_value:
        logger.warning(
            "配置项 %s 的值 %s 超过上限 %s，已使用默认值 %s",
            name,
            parsed,
            max_value,
            default,
        )
        return default
    return parsed


def _env_float(
    name: str,
    default: float,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    value = _environment_value(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError:
        logger.warning("配置项 %s 的值 %r 无法解析为浮点数，已使用默认值 %s", name, value, default)
        return default
    if not math.isfinite(parsed):
        logger.warning("配置项 %s 必须是有限数值，已使用默认值 %s", name, default)
        return default
    if min_value is not None and parsed < min_value:
        logger.warning(
            "配置项 %s 的值 %s 小于下限 %s，已使用默认值 %s",
            name,
            parsed,
            min_value,
            default,
        )
        return default
    if max_value is not None and parsed > max_value:
        logger.warning(
            "配置项 %s 的值 %s 超过上限 %s，已使用默认值 %s",
            name,
            parsed,
            max_value,
            default,
        )
        return default
    return parsed


def _env_log_level(name: str, default: str = "INFO") -> str:
    value = _env_str(name, default).upper()
    level = getattr(logging, value, None)
    if isinstance(level, int):
        return value
    logger.warning(
        "配置项 %s 的值 %r 无效，已回退到默认日志级别 %s",
        name,
        _environment_value(name),
        default,
    )
    return default


def _resolve_api_config(config: dict | None = None) -> dict:
    if config and config.get("api_key"):
        return {
            "api_key": config["api_key"],
            "base_url": config.get("base_url", ""),
            "model": config.get("model", "deepseek-v4-pro"),
            "source": "ccswitch",
            "raw_model": config.get("raw_model", config.get("model", "")),
            "is_proxy": bool(config.get("is_proxy", False)),
            "extra_env": config.get("extra_env", {}) or {},
        }
    return {
        "api_key": _env_str("ANTHROPIC_API_KEY", ""),
        "base_url": _env_str(
            "ANTHROPIC_BASE_URL",
            "https://api.deepseek.com/anthropic",
        ),
        "model": _env_str("ANTHROPIC_MODEL", "deepseek-v4-pro"),
        "source": "portable" if PORTABLE_MODE else ".env",
        "raw_model": "",
        "is_proxy": False,
        "extra_env": {},
    }


def reload_config() -> bool:
    """运行时重新加载配置。

    从 ccswitch settings.json 重新读取 API 配置，更新 Config 类属性。
    如果 ccswitch 不可用，回退到 .env。

    返回 True 表示加载成功，False 表示回退到 .env。
    """
    global _ccswitch, _config_loaded_at
    if PORTABLE_MODE:
        _config_loaded_at = time.time()
        Config.CONFIG_LOADED_AT = _config_loaded_at
        return False
    new_config = None
    if _ccswitch_enabled():
        try:
            new_config = reload_ccswitch_config(strict=True)
        except CcswitchUnreadableError:
            # cc-switch 可能正在写 settings.json：稍等重读一次，仍失败则保留当前配置，不误回退到 .env。
            time.sleep(0.2)
            new_config = reload_ccswitch_config(strict=True)
        if new_config is None and Config.CONFIG_SOURCE == "ccswitch":
            # 上次来自 ccswitch、这次文件却不存在：cc-switch 可能正在替换文件，稍等再读一次才回退 .env。
            time.sleep(0.2)
            new_config = reload_ccswitch_config(strict=True)
    if new_config and new_config.get("api_key"):
        _ccswitch = new_config
    else:
        _ccswitch = None

    resolved = _resolve_api_config(_ccswitch)
    Config.ANTHROPIC_API_KEY = resolved["api_key"]
    Config.ANTHROPIC_BASE_URL = resolved["base_url"]
    Config.ANTHROPIC_MODEL = resolved["model"]
    Config.CONFIG_SOURCE = resolved["source"]
    Config.CCSWITCH_RAW_MODEL = resolved["raw_model"]
    Config.CCSWITCH_IS_PROXY = resolved["is_proxy"]
    Config.EXTRA_ENV = resolved["extra_env"]
    Config.API_PROTOCOL = 'anthropic' if resolved['source'] == 'ccswitch' else _env_str('AI_API_PROTOCOL', 'anthropic')
    _config_loaded_at = time.time()
    Config.CONFIG_LOADED_AT = _config_loaded_at
    return resolved["source"] == "ccswitch"


class Config:
    """应用配置"""

    # ---- 服务配置 ----
    IS_PORTABLE = PORTABLE_MODE
    LOG_DIR = str(data_root() / 'logs') if PORTABLE_MODE else 'logs'
    # Loopback by default; Docker/LAN hosts must set HOST=0.0.0.0 explicitly.
    HOST = _env_str("HOST", "127.0.0.1")
    PORT = _env_int("PORT", 5000, min_value=1, max_value=65535)
    # Debug reloader/debugger stay off unless the operator opts in.
    DEBUG = _env_bool("DEBUG", False)

    # ---- AI API 配置 ----
    if _ccswitch and _ccswitch.get("api_key"):
        _api_cfg = _resolve_api_config(_ccswitch)
        ANTHROPIC_API_KEY = _api_cfg["api_key"]
        ANTHROPIC_BASE_URL = _api_cfg["base_url"]
        ANTHROPIC_MODEL = _api_cfg["model"]
        CONFIG_SOURCE = _api_cfg["source"]
        CCSWITCH_RAW_MODEL = _api_cfg["raw_model"]
        CCSWITCH_IS_PROXY = _api_cfg["is_proxy"]
        EXTRA_ENV = _api_cfg["extra_env"]
    else:
        _env_api_cfg = _resolve_api_config()
        ANTHROPIC_API_KEY = _env_api_cfg["api_key"]
        ANTHROPIC_BASE_URL = _env_api_cfg["base_url"]
        ANTHROPIC_MODEL = _env_api_cfg["model"]
        CONFIG_SOURCE = _env_api_cfg["source"]
        CCSWITCH_RAW_MODEL = _env_api_cfg["raw_model"]
        CCSWITCH_IS_PROXY = _env_api_cfg["is_proxy"]
        EXTRA_ENV = _env_api_cfg["extra_env"]

    # ---- AI 客户端配置 ----
    API_TIMEOUT = _env_float("API_TIMEOUT", 30.0, min_value=1.0, max_value=600.0)
    API_MAX_RETRIES = _env_int("API_MAX_RETRIES", 2, min_value=0, max_value=10)
    API_PROTOCOL = 'anthropic' if _ccswitch else _env_str('AI_API_PROTOCOL', 'anthropic')
    REASONING_EFFORT = _env_str('AI_REASONING_EFFORT', 'auto')

    # ---- 日志配置 ----
    LOG_LEVEL = _env_log_level("LOG_LEVEL", "INFO")

    # ---- 安全配置 ----
    ACCESS_TOKEN = _env_str("ACCESS_TOKEN", "") or None
    # 未设置 ACCESS_TOKEN 时默认只允许本机（回环地址）调用；局域网/Docker 请设置令牌，
    # 或显式 ALLOW_REMOTE_WITHOUT_TOKEN=true 接受“任何可达客户端都能调用”的风险。
    ALLOW_REMOTE_WITHOUT_TOKEN = _env_bool("ALLOW_REMOTE_WITHOUT_TOKEN", False)
    # 每个客户端每分钟最多触发的 AI 调用次数（缓存命中不计）；0 表示不限。
    RATE_LIMIT_PER_MINUTE = _env_int("RATE_LIMIT_PER_MINUTE", 60, min_value=0, max_value=100000)
    CCSWITCH_ENABLED = _ccswitch_enabled()

    # ---- AI 响应配置 ----
    MAX_TOKENS = _env_int("MAX_TOKENS", 500, min_value=1, max_value=4096)
    # 简答题需要完整句子，输出上限至少取该值，避免被截断后整题失败。
    SHORT_ANSWER_MAX_TOKENS = _env_int("SHORT_ANSWER_MAX_TOKENS", 1024, min_value=1, max_value=8192)
    TEMPERATURE = _env_float("TEMPERATURE", 0.7, min_value=0.0, max_value=2.0)
    # 单选/多选/判断/填空需要唯一解，温度不高于该上限；简答题沿用 TEMPERATURE。
    OBJECTIVE_TEMPERATURE_CAP = _env_float("OBJECTIVE_TEMPERATURE_CAP", 0.3, min_value=0.0, max_value=2.0)

    # ---- 缓存配置 ----
    ENABLE_CACHE = _env_bool("ENABLE_CACHE", True)
    CACHE_EXPIRATION = _env_int("CACHE_EXPIRATION", 86400, min_value=60)

    # ---- 输入验证 ----
    MAX_QUESTION_LENGTH = _env_int("MAX_QUESTION_LENGTH", 2000, min_value=20, max_value=10000)
    # 按带标号的选项计数（长选项折行不重复计），没有标号时按行计数。
    MAX_OPTIONS = _env_int("MAX_OPTIONS", 64, min_value=1, max_value=200)
    MAX_OPTIONS_LENGTH = _env_int("MAX_OPTIONS_LENGTH", 8000, min_value=100, max_value=100000)
    MAX_REQUEST_BYTES = _env_int("MAX_REQUEST_BYTES", 256 * 1024, min_value=4096, max_value=10 * 1024 * 1024)

    # ---- 配置加载时间 ----
    CONFIG_LOADED_AT = _config_loaded_at
