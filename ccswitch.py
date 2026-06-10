# -*- coding: utf-8 -*-
"""
ccswitch 配置读取模块
从 Claude Code settings.json 中读取当前 API 设置，
支持 ccswitch 本地代理和直连 API 两种模式。
"""
import json
from pathlib import Path
from typing import Optional, Dict

import logging

logger = logging.getLogger(__name__)


def _find_settings_path() -> Optional[Path]:
    """查找 Claude Code settings.json 路径（优先 settings.json，回退 settings.local.json）"""
    for name in ("settings.json", "settings.local.json"):
        p = Path.home() / ".claude" / name
        if p.is_file():
            return p
    return None


def get_ccswitch_config() -> Optional[Dict[str, str]]:
    """
    从 Claude Code settings.json 读取 API 配置。

    支持两种模式：
    1. ccswitch 本地代理 (127.0.0.1:15721)
    2. 直连 API (如 api.deepseek.com)

    返回 None 表示未检测到有效配置，应回退到 .env。
    返回 Dict 包含 api_key, base_url, model 三个字段。

    模型选择优先级：
    1. env.ANTHROPIC_MODEL — 通用模型名（DeepSeek 直连模式优先使用）
    2. env.ANTHROPIC_DEFAULT_{OPUS|SONNET|HAIKU}_MODEL — 按当前选定模型取专用名
    3. env.ANTHROPIC_DEFAULT_{OPUS|SONNET|HAIKU}_MODEL_NAME — 模型显示名
    4. 硬回退 — 默认值
    """
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

    model = _resolve_model(settings, env)

    is_local = "127.0.0.1" in base_url or "localhost" in base_url
    proxy_tag = "ccswitch代理" if is_local else "直连"
    logger.info(
        f"从 settings.json 加载配置 ({proxy_tag}): "
        f"model={model}, base_url={base_url}"
    )

    return {"api_key": api_key, "base_url": base_url, "model": model}


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
