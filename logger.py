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
    os.makedirs(log_dir, exist_ok=True)

    log_file = os.path.join(
        log_dir, f"{name}_{datetime.now().strftime('%Y-%m-%d')}.log"
    )

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # 幂等保护：避免重复添加 handler
    if logger.handlers:
        return logger

    fmt = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # 文件处理器（轮转）
    fh = RotatingFileHandler(
        log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'
    )
    fh.setLevel(level)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # 控制台处理器（Windows 控制台 UTF-8 编码兼容）
    if sys.platform == 'win32':
        import io
        utf8_stream = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8',
                                        errors='replace', line_buffering=True)
        ch = logging.StreamHandler(utf8_stream)
    else:
        ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger
