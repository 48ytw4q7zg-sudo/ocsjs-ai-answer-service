# -*- coding: utf-8 -*-
"""
配置模块
优先从 ccswitch (Claude Code settings.json) 读取 API 设置，
未检测到有效配置时自动回退到 .env 文件。
"""
import os
from dotenv import load_dotenv

from ccswitch import get_ccswitch_config

# 强制覆盖加载 .env
load_dotenv(override=True)

# 尝试从 ccswitch 获取配置（优先）
_ccswitch = get_ccswitch_config()


class Config:
    """应用配置"""

    # ---- 服务配置 ----
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "5000"))
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"

    # ---- AI API 配置 ----
    if _ccswitch and _ccswitch.get('api_key'):
        ANTHROPIC_API_KEY = _ccswitch['api_key']
        ANTHROPIC_BASE_URL = _ccswitch['base_url']
        ANTHROPIC_MODEL = _ccswitch['model']
        CONFIG_SOURCE = 'ccswitch'
    else:
        ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
        ANTHROPIC_BASE_URL = os.getenv(
            "ANTHROPIC_BASE_URL",
            "https://api.deepseek.com/anthropic",
        )
        ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "deepseek-v4-pro")
        CONFIG_SOURCE = '.env'

    # ---- AI 客户端配置 ----
    API_TIMEOUT = float(os.getenv("API_TIMEOUT", "30.0"))
    API_MAX_RETRIES = int(os.getenv("API_MAX_RETRIES", "2"))

    # ---- 日志配置 ----
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

    # ---- 安全配置 ----
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", None)

    # ---- AI 响应配置 ----
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "500"))
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))

    # ---- 缓存配置 ----
    ENABLE_CACHE = os.getenv("ENABLE_CACHE", "True").lower() == "true"
    CACHE_EXPIRATION = int(os.getenv("CACHE_EXPIRATION", "86400"))

    # ---- 输入验证 ----
    MAX_QUESTION_LENGTH = int(os.getenv("MAX_QUESTION_LENGTH", "2000"))
