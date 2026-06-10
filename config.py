# -*- coding: utf-8 -*-
"""
配置模块 v2026.6.10.1739
优先从 ccswitch (Claude Code settings.json) 读取 API 设置，
未检测到有效配置时自动回退到 .env 文件。
新增：运行时重载、配置来源时间戳、DeepSeek 优化参数。
"""
import os
import time
from dotenv import load_dotenv

from ccswitch import get_ccswitch_config, reload_ccswitch_config

# 强制覆盖加载 .env
load_dotenv(override=True)

# 尝试从 ccswitch 获取配置（优先）
_ccswitch = get_ccswitch_config()
_config_loaded_at = time.time()


def reload_config() -> bool:
    """运行时重新加载配置。

    从 ccswitch settings.json 重新读取 API 配置，更新 Config 类属性。
    如果 ccswitch 不可用，回退到 .env。

    返回 True 表示加载成功，False 表示回退到 .env。
    """
    global _ccswitch, _config_loaded_at
    new_config = reload_ccswitch_config()
    if new_config and new_config.get("api_key"):
        _ccswitch = new_config
        Config.ANTHROPIC_API_KEY = new_config["api_key"]
        Config.ANTHROPIC_BASE_URL = new_config["base_url"]
        Config.ANTHROPIC_MODEL = new_config["model"]
        Config.CONFIG_SOURCE = "ccswitch"
        Config.CCSWITCH_RAW_MODEL = new_config.get("raw_model", new_config["model"])
        Config.CCSWITCH_IS_PROXY = new_config.get("is_proxy", False)
        Config.EXTRA_ENV = new_config.get("extra_env", {})
        _config_loaded_at = time.time()
        Config.CONFIG_LOADED_AT = _config_loaded_at
        return True
    else:
        Config.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
        Config.ANTHROPIC_BASE_URL = os.getenv(
            "ANTHROPIC_BASE_URL",
            "https://api.deepseek.com/anthropic",
        )
        Config.ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "deepseek-v4-pro")
        Config.CONFIG_SOURCE = ".env"
        Config.CCSWITCH_RAW_MODEL = ""
        Config.CCSWITCH_IS_PROXY = False
        Config.EXTRA_ENV = {}
        _config_loaded_at = time.time()
        Config.CONFIG_LOADED_AT = _config_loaded_at
        return False


class Config:
    """应用配置"""

    # ---- 服务配置 ----
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "5000"))
    DEBUG = os.getenv("DEBUG", "True").lower() == "true"

    # ---- AI API 配置 ----
    if _ccswitch and _ccswitch.get("api_key"):
        ANTHROPIC_API_KEY = _ccswitch["api_key"]
        ANTHROPIC_BASE_URL = _ccswitch["base_url"]
        ANTHROPIC_MODEL = _ccswitch["model"]
        CONFIG_SOURCE = "ccswitch"
        CCSWITCH_RAW_MODEL = _ccswitch.get("raw_model", _ccswitch["model"])
        CCSWITCH_IS_PROXY = _ccswitch.get("is_proxy", False)
        EXTRA_ENV = _ccswitch.get("extra_env", {})
    else:
        ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
        ANTHROPIC_BASE_URL = os.getenv(
            "ANTHROPIC_BASE_URL",
            "https://api.deepseek.com/anthropic",
        )
        ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "deepseek-v4-pro")
        CONFIG_SOURCE = ".env"
        CCSWITCH_RAW_MODEL = ""
        CCSWITCH_IS_PROXY = False
        EXTRA_ENV = {}

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

    # ---- 配置加载时间 ----
    CONFIG_LOADED_AT = _config_loaded_at
