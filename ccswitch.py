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


def _sanitize_model_name(model: str) -> str:
    """去除模型名中的上下文长度后缀（如 [1M]、[200K]、[128K]）。

    DeepSeek API 不识别带方括号后缀的模型名。
    例如：'deepseek-v4-pro[1M]' → 'deepseek-v4-pro'
    """
    return re.sub(r"\[\d+K?M?\]", "", model).strip()


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
    env = settings.get("env")
    if not isinstance(env, dict):
        return {}
    result = {}
    for key in _ENV_KEYS:
        val = (env.get(key) or "").strip()
        if val:
            result[key] = val
    return result


def _load_full_config(config: dict) -> dict:
    """为配置字典附加完整 env 信息（extract_all_env）。

    在 get_ccswitch_config() 和 reload_ccswitch_config() 中复用，
    确保启动和重载两种场景都获取完整 env。
    """
    settings_path = Path(config["source_file"])
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        config["extra_env"] = extract_all_env(settings)
    except Exception:
        config["extra_env"] = {}
    return config


def get_ccswitch_config(settings_path: Optional[Path] = None) -> Optional[Dict[str, str]]:
    """
    从 Claude Code settings.json 读取 API 配置。

    支持两种模式：
    1. ccswitch 本地代理 (127.0.0.1:15721)
    2. 直连 API (如 api.deepseek.com)

    返回 None 表示未检测到有效配置，应回退到 .env。
    返回 Dict 包含 api_key, base_url, model, meta 四个字段。

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
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"读取 settings.json 失败: {e}")
        return None

    env = settings.get("env")
    if not isinstance(env, dict) or not env:
        logger.debug("settings.json 中无 env 配置")
        return None

    api_key = (env.get("ANTHROPIC_AUTH_TOKEN") or "").strip()
    base_url = (env.get("ANTHROPIC_BASE_URL") or "").strip()

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
    return _load_full_config(config)


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
    direct = (env.get("ANTHROPIC_MODEL") or "").strip()
    if direct:
        return direct

    # 第 2-3 级：按当前 model 选择对应的专用名称
    selected = settings.get("model", "opus")
    key_map = {
        "opus":   ("ANTHROPIC_DEFAULT_OPUS_MODEL_NAME", "ANTHROPIC_DEFAULT_OPUS_MODEL"),
        "sonnet": ("ANTHROPIC_DEFAULT_SONNET_MODEL_NAME", "ANTHROPIC_DEFAULT_SONNET_MODEL"),
        "haiku":  ("ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME", "ANTHROPIC_DEFAULT_HAIKU_MODEL"),
    }
    keys = key_map.get(selected, key_map["opus"])
    for k in keys:
        val = (env.get(k) or "").strip()
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
        val = (env.get(k) or "").strip()
        if val:
            return val

    # 第 5 级：硬回退
    return "deepseek-v4-pro"


def reload_ccswitch_config() -> Optional[Dict[str, str]]:
    """运行时重新加载 ccswitch 配置（用于 /api/config/reload 端点）。

    与 get_ccswitch_config() 的功能完全相同，都会附加完整 env。
    保留此函数作为语义化入口，方便未来扩展（如添加缓存失效逻辑）。
    """
    return get_ccswitch_config()
