# -*- coding: utf-8 -*-
"""
日志工具模块
提供 RotatingFileHandler 轮转日志记录
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime


def setup_logger(name: str, log_dir: str = "logs",
                 level: int = logging.INFO) -> logging.Logger:
    """
    创建并配置日志记录器。

    - 控制台输出 (StreamHandler)
    - 文件轮转输出 (RotatingFileHandler, 10MB, 保留5个)
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False

    # 幂等保护：避免重复添加 handler
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 文件处理器（轮转）
    try:
        os.makedirs(log_dir, exist_ok=True)
        log_file = os.path.join(log_dir, f"{name}_{datetime.now().strftime('%Y-%m-%d')}.log")
        fh = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8')
        fh.setLevel(level)
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass

    # 控制台处理器（Windows 控制台 UTF-8 编码兼容）
    stream = sys.stdout
    if stream is not None:
        if sys.platform == 'win32' and hasattr(stream, 'reconfigure'):
            try:
                stream.reconfigure(encoding='utf-8', errors='replace')
            except (OSError, ValueError):
                pass
        ch = logging.StreamHandler(stream)
        ch.setLevel(level)
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    return logger
