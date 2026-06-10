# -*- coding: utf-8 -*-
"""
ccswitch 配置读取模块
从 Claude Code settings.json 中读取当前 API 设置，
支持 ccswitch 本地代理和直连 API 两种模式。
"""
import json
import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


def _find_settings_path() -> Optional[str]:
    """查找 Claude Code settings.json 路径"""
    paths = [
        os.path.expanduser("~/.claude/settings.json"),
        os.path.expanduser("~/.claude/settings.local.json"),
    ]
    for p in paths:
        if os.path.isfile(p):
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
    """
    settings_path = _find_settings_path()
    if not settings_path:
        logger.debug("未找到 Claude Code settings.json")
        return None

    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"读取 settings.json 失败: {e}")
        return None

    env = settings.get('env', {})
    if not isinstance(env, dict) or not env:
        logger.debug("settings.json 中无 env 配置")
        return None

    api_key = env.get('ANTHROPIC_AUTH_TOKEN', '').strip()
    base_url = env.get('ANTHROPIC_BASE_URL', '').strip()

    if not api_key:
        logger.debug("settings.json 中 ANTHROPIC_AUTH_TOKEN 为空")
        return None
    if not base_url:
        logger.debug("settings.json 中 ANTHROPIC_BASE_URL 为空")
        return None

    # 模型选择优先级: ANTHROPIC_MODEL > 模型特定名称 > 默认值
    model = (
        env.get('ANTHROPIC_MODEL', '').strip()
        or _get_model_by_selection(settings, env)
        or 'deepseek-v4-pro'
    )

    is_local = '127.0.0.1' in base_url or 'localhost' in base_url
    proxy_tag = 'ccswitch代理' if is_local else '直连'
    logger.info(
        f"从 settings.json 加载配置 ({proxy_tag}): "
        f"model={model}, base_url={base_url}"
    )

    return {'api_key': api_key, 'base_url': base_url, 'model': model}


def _get_model_by_selection(settings: dict, env: dict) -> Optional[str]:
    """根据 settings.json 中当前选择的模型取对应的模型名称"""
    selected = settings.get('model', 'opus')
    key_map = {
        'opus':   'ANTHROPIC_DEFAULT_OPUS_MODEL_NAME',
        'sonnet': 'ANTHROPIC_DEFAULT_SONNET_MODEL_NAME',
        'haiku':  'ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME',
    }
    key = key_map.get(selected, 'ANTHROPIC_DEFAULT_OPUS_MODEL_NAME')
    return env.get(key, '').strip() or None
