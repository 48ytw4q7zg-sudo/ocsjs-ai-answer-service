# -*- coding: utf-8 -*-
"""
配置文件
优先从 ccswitch (Claude Code settings.json) 读取当前 API 代理设置，
未检测到 ccswitch 时自动回退到 .env 文件配置。
"""
import os
import logging
from dotenv import load_dotenv

from ccswitch import get_ccswitch_config

logger = logging.getLogger(__name__)

# 强制覆盖加载环境变量
load_dotenv(override=True)

# 尝试从 ccswitch 获取配置
_ccswitch = get_ccswitch_config()


class Config:
    # 服务配置
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", 5000))
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"

    # AI API 配置 — 优先使用 ccswitch，回退到 .env
    if _ccswitch and _ccswitch.get('api_key', '').strip():
        ANTHROPIC_API_KEY = _ccswitch['api_key']
        ANTHROPIC_BASE_URL = _ccswitch['base_url']
        ANTHROPIC_MODEL = _ccswitch['model']
        CONFIG_SOURCE = 'ccswitch'
    else:
        ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
        ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.deepseek.com/anthropic")
        ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "deepseek-v4-pro")
        CONFIG_SOURCE = '.env'

    # 日志配置
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # 安全配置（可选）
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", None)

    # 响应配置
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", 500))
    TEMPERATURE = float(os.getenv("TEMPERATURE", 0.7))

    # 缓存配置
    ENABLE_CACHE = os.getenv("ENABLE_CACHE", "True").lower() == "true"
    CACHE_EXPIRATION = int(os.getenv("CACHE_EXPIRATION", 86400))
