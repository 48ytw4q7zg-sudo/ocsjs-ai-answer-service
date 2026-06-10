# -*- coding: utf-8 -*-
"""
ccswitch 配置读取模块
从 Claude Code settings.json 中读取当前 ccswitch 的 API 代理设置，
实现 API 密钥和模型配置的动态获取，无需在 .env 中硬编码。
"""
import json
import os
import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)

# ccswitch 代理默认地址
CCSWITCH_DEFAULT_HOST = "127.0.0.1"
CCSWITCH_DEFAULT_PORT = 15721


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


def _is_ccswitch_proxy(base_url: str) -> bool:
    """判断 base_url 是否指向 ccswitch 代理"""
    return (f"{CCSWITCH_DEFAULT_HOST}:{CCSWITCH_DEFAULT_PORT}" in base_url or
            f"localhost:{CCSWITCH_DEFAULT_PORT}" in base_url)


def get_ccswitch_config() -> Optional[Dict[str, str]]:
    """
    从 Claude Code settings.json 读取 ccswitch 配置。

    返回 None 表示未检测到 ccswitch 代理配置，应回退到 .env 文件。
    返回 Dict 包含 api_key, base_url, model 三个字段。
    """
    settings_path = _find_settings_path()
    if not settings_path:
        logger.debug("未找到 Claude Code settings.json，跳过 ccswitch 配置读取")
        return None

    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            settings = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.warning(f"读取 settings.json 失败: {e}")
        return None

    env = settings.get('env', {})
    if not isinstance(env, dict):
        return None

    base_url = env.get('ANTHROPIC_BASE_URL', '')
    if not base_url or not _is_ccswitch_proxy(base_url):
        logger.debug("settings.json 中未检测到 ccswitch 代理配置")
        return None

    # 根据当前选择的模型取对应的模型名称
    selected_model = settings.get('model', 'opus')
    model_key_map = {
        'opus': 'ANTHROPIC_DEFAULT_OPUS_MODEL_NAME',
        'sonnet': 'ANTHROPIC_DEFAULT_SONNET_MODEL_NAME',
        'haiku': 'ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME',
    }
    model_key = model_key_map.get(selected_model, 'ANTHROPIC_DEFAULT_OPUS_MODEL_NAME')
    model = env.get(model_key) or 'deepseek-v4-pro'

    api_key = env.get('ANTHROPIC_AUTH_TOKEN', 'PROXY_MANAGED')
    if not api_key or not api_key.strip():
        logger.debug("ccswitch 配置中 ANTHROPIC_AUTH_TOKEN 为空")
        return None

    config = {
        'api_key': api_key,
        'base_url': base_url,
        'model': model,
    }

    logger.info(f"从 ccswitch 加载配置: model={model}, base_url={base_url}")
    return config
