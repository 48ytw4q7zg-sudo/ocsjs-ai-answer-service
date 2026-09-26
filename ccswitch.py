# -*- coding: utf-8 -*-
"""
ccswitch 配置读取模块 v2026.6.10.1739
从 Claude Code settings.json 中读取当前 API 设置，
支持 ccswitch 本地代理和直连 API 两种模式。
新增：模型名净化（去除 [1M] 等后缀）、完整 env 提取、运行时重新加载。
"""
import json
import re
from pathlib import Path
from typing import Optional, Dict

import logging

from provider_clients import sanitize_model_name

logger = logging.getLogger(__name__)

# 需要从 settings.json env 中提取的所有字段
_ENV_KEYS = (
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL",
    "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_REASONING_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME",
    "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
    "CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK",
    "CLAUDE_CODE_EFFORT_LEVEL",
    "ENABLE_TOOL_SEARCH",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS",
)

# 仪表盘/接口展示配置时需要隐藏值的键名片段（与 app.py 共用同一张表）。
SENSITIVE_KEY_TERMS = (
    "TOKEN", "KEY", "SECRET", "PASSWORD", "PASS", "AUTH", "CREDENTIAL",
    "PRIVATE", "BEARER", "COOKIE", "SESSION", "SIGNATURE", "CERT",
)
_MAX_DISPLAY_VALUE_LENGTH = 200


def is_sensitive_key(key: str) -> bool:
    upper_key = str(key).upper()
    return any(part in upper_key for part in SENSITIVE_KEY_TERMS)


def _is_sensitive_env_key(key: str) -> bool:
    return is_sensitive_key(key)


def _display_value(value):
    text = str(value)
    return text if len(text) <= _MAX_DISPLAY_VALUE_LENGTH else text[:_MAX_DISPLAY_VALUE_LENGTH] + "…"


def sanitize_env_for_display(env: Dict[str, str]) -> Dict[str, str]:
    return {
        key: "<hidden>" if is_sensitive_key(key) else _display_value(value)
        for key, value in env.items()
    }


def _sanitize_model_name(model: str) -> str:
    """去除模型名中的上下文长度后缀（如 [1M]、[200K]、[128K]）。

    DeepSeek API 不识别带方括号后缀的模型名。
    例如：'deepseek-v4-pro[1M]' → 'deepseek-v4-pro'
    """
    return sanitize_model_name(model)


def _find_settings_path() -> Optional[Path]:
    """查找 Claude Code settings.json 路径（优先 settings.json，回退 settings.local.json）"""
    for name in ("settings.json", "settings.local.json"):
        p = Path.home() / ".claude" / name
        if p.is_file():
            return p
    return None


def extract_all_env(settings: dict) -> Dict[str, str]:
    """从 settings.json 中提取所有 _ENV_KEYS 列表中的环境变量。

    用于完整展示 ccswitch 当前配置，方便调试和仪表盘展示。
    """
    if not isinstance(settings, dict):
        return {}
    env = settings.get("env")
    if not isinstance(env, dict):
        return {}
    result = {}
    for key in _ENV_KEYS:
        val = _text_value(env.get(key))
        if val:
            result[key] = val
    return sanitize_env_for_display(result)


class CcswitchUnreadableError(RuntimeError):
    """settings.json 存在但暂时无法读取或解析（常见于 cc-switch 正在写入）。"""


def _load_full_config(config: dict, settings: Optional[dict] = None) -> dict:
    """为配置字典附加完整 env 信息（extract_all_env）。

    直接复用已解析的 settings，避免二次读取时撞上 cc-switch 半写的文件。
    """
    if settings is None:
        try:
            settings = json.loads(Path(config["source_file"]).read_text(encoding="utf-8"))
        except Exception:
            settings = {}
    config["extra_env"] = extract_all_env(settings)
    return config


def _text_value(value) -> str:
    return value.strip() if isinstance(value, str) else ''


def get_ccswitch_config(settings_path: Optional[Path] = None, *, strict: bool = False) -> Optional[Dict[str, str]]:
    """
    从 Claude Code settings.json 读取 API 配置。

    支持两种模式：
    1. ccswitch 本地代理 (127.0.0.1:15721)
    2. 直连 API (如 api.deepseek.com)

    返回 None 表示未检测到有效配置，应回退到 .env。
    返回 Dict 包含 api_key, base_url, model, meta 四个字段。
    strict=True 时，文件存在但读取/解析失败会抛出 CcswitchUnreadableError，
    供运行时重载区分“没有 ccswitch 配置”和“配置正在写入”。

    模型选择优先级（含净化）：
    1. env.ANTHROPIC_MODEL — 通用模型名（DeepSeek 直连模式优先使用）
    2. env.ANTHROPIC_DEFAULT_{OPUS|SONNET|HAIKU}_MODEL — 按当前选定模型取专用名
    3. env.ANTHROPIC_DEFAULT_{OPUS|SONNET|HAIKU}_MODEL_NAME — 模型显示名
    4. 硬回退 — 默认值
    5. 所有模型名经过 _sanitize_model_name() 净化
    """
    if settings_path is None:
        settings_path = _find_settings_path()
    if not settings_path:
        logger.debug("未找到 Claude Code settings.json")
        return None

    try:
        content = settings_path.read_text(encoding="utf-8")
        settings = json.loads(content)
    except (json.JSONDecodeError, OSError, UnicodeError) as e:
        logger.warning("读取 settings.json 失败: %s", type(e).__name__)
        if strict:
            raise CcswitchUnreadableError("settings.json 暂时无法读取或解析") from None
        return None

    if not isinstance(settings, dict):
        logger.warning('settings.json 必须是 JSON 对象')
        return None
    env = settings.get("env")
    if not isinstance(env, dict) or not env:
        logger.debug("settings.json 中无 env 配置")
        return None

    api_key = _text_value(env.get("ANTHROPIC_AUTH_TOKEN"))
    base_url = _text_value(env.get("ANTHROPIC_BASE_URL"))

    if not api_key:
        logger.debug("settings.json 中 ANTHROPIC_AUTH_TOKEN 为空")
        return None
    if not base_url:
        logger.debug("settings.json 中 ANTHROPIC_BASE_URL 为空")
        return None

    raw_model = _resolve_model(settings, env)
    model = _sanitize_model_name(raw_model)

    is_local = "127.0.0.1" in base_url or "localhost" in base_url
    proxy_tag = "ccswitch代理" if is_local else "直连"

    if raw_model != model:
        logger.info(f"模型名已净化: '{raw_model}' → '{model}'")

    logger.info(
        f"从 settings.json 加载配置 ({proxy_tag}): "
        f"model={model}, base_url={base_url}"
    )

    config = {
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "raw_model": raw_model,
        "is_proxy": is_local,
        "source_file": str(settings_path),
    }
    return _load_full_config(config, settings)


def _resolve_model(settings: dict, env: dict) -> str:
    """多级回退解析模型名。

    优先级：
    1. env.ANTHROPIC_MODEL
    2. env.ANTHROPIC_DEFAULT_{OPUS|SONNET|HAIKU}_MODEL（按 settings.model 选择）
    3. env.ANTHROPIC_DEFAULT_{OPUS|SONNET|HAIKU}_MODEL_NAME（显示名称回退）
    4. env.ANTHROPIC_DEFAULT_OPUS_MODEL / SONNET / HAIKU（兜底）
    5. 硬编码默认值
    """
    # 第 1 级：通用模型名
    direct = _text_value(env.get("ANTHROPIC_MODEL"))
    if direct:
        return direct

    # 第 2-3 级：按当前 model 选择对应的专用名称
    selected = _text_value(settings.get("model")) or 'opus'
    key_map = {
        "opus":   ("ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL_NAME"),
        "sonnet": ("ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL_NAME"),
        "haiku":  ("ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME"),
    }
    keys = key_map.get(selected, key_map["opus"])
    for k in keys:
        val = _text_value(env.get(k))
        if val:
            return val

    # 第 4 级：遍历所有可能的后备模型键
    backup_keys = [
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_REASONING_MODEL",
    ]
    for k in backup_keys:
        val = _text_value(env.get(k))
        if val:
            return val

    # 第 5 级：硬回退
    return "deepseek-v4-pro"


def reload_ccswitch_config(*, strict: bool = False) -> Optional[Dict[str, str]]:
    """运行时重新加载 ccswitch 配置（用于 /api/config/reload 端点）。

    strict=True 时，文件存在但暂不可读会抛出 CcswitchUnreadableError，
    调用方据此保留当前配置，而不是误回退到 .env。
    """
    return get_ccswitch_config(strict=strict)
