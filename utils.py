# -*- coding: utf-8 -*-
"""
工具函数模块
包含缓存管理、答案处理和提示词构建等辅助功能
"""
from __future__ import annotations

import time
import hashlib
import re
from typing import Dict, Any, Optional


class SimpleCache:
    """简单的内存缓存，支持 TTL 过期和 LRU 淘汰"""

    def __init__(self, expiration_seconds: int = 86400, max_size: int = 10000):
        self.cache: Dict[str, tuple[float, str]] = {}
        self.expiration = expiration_seconds
        self.max_size = max_size

    def __len__(self) -> int:
        return len(self.cache)

    @staticmethod
    def _generate_key(question: str, question_type: str, options: str) -> str:
        content = f"{question}|{question_type}|{options}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def get(self, question: str, question_type: str = "",
            options: str = "") -> Optional[str]:
        key = self._generate_key(question, question_type, options)
        entry = self.cache.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts < self.expiration:
            return value
        del self.cache[key]
        return None

    def set(self, question: str, answer: str, question_type: str = "",
            options: str = "") -> None:
        key = self._generate_key(question, question_type, options)
        if len(self.cache) >= self.max_size:
            # 找到时间戳最小的 key（最旧）并删除
            oldest = min(self.cache, key=lambda k: self.cache[k][0])
            del self.cache[oldest]
        self.cache[key] = (time.time(), answer)

    def clear(self) -> None:
        self.cache.clear()

    def remove_expired(self) -> int:
        now = time.time()
        expired = [k for k, (ts, _) in self.cache.items()
                    if now - ts >= self.expiration]
        for k in expired:
            del self.cache[k]
        return len(expired)


def format_answer_for_ocs(question: str, answer: str) -> Dict[str, Any]:
    """格式化答案为 OCS 协议格式"""
    return {'code': 1, 'question': question, 'answer': answer}


_TYPE_HINTS = {
    "single":     "这是一道单选题。",
    "multiple":   "这是一道多选题，答案请用#号分隔选项。",
    "judgement":  "这是一道判断题，需要回答：正确/对/true/√ 或者 错误/错/false/×。",
    "completion": "这是一道填空题。",
}


def parse_question_and_options(question: str, options: str,
                               question_type: str) -> str:
    """解析问题和选项，构建发送给 AI 的提示词"""
    parts = [f"问题: {question}"]
    hint = _TYPE_HINTS.get(question_type)
    if hint:
        parts.append(hint)
    if options:
        parts.append(f"选项:\n{options}")
    parts.append("请直接给出答案，不要解释。")
    return "\n".join(parts)


_OPTION_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']


def extract_answer(ai_response: str, question_type: str) -> str:
    """从 AI 响应中提取并格式化答案（多选题做 # 分隔转换）"""
    if question_type != "multiple":
        return ai_response

    text = ai_response.strip()
    if not text:
        return text

    # 已包含 # 分隔符
    if '#' in text:
        return _normalize_hash_separated(text)

    # 尝试从文本中提取选项字母
    return _detect_letters(text) or text


def _normalize_hash_separated(text: str) -> str:
    """标准化 # 分隔的答案，确保只保留选项字母"""
    parts = [p.strip() for p in text.split('#') if p.strip()]
    letters = []
    for p in parts:
        upper = p.upper()
        if len(upper) == 1 and upper in _OPTION_LETTERS:
            letters.append(upper)
        else:
            # 尝试从长文本中提取首字母
            first = upper[0] if upper else ''
            if first in _OPTION_LETTERS:
                letters.append(first)
    return '#'.join(letters) if letters else text


def _detect_letters(text: str) -> Optional[str]:
    """从文本中检测选项字母并返回 # 分隔格式"""
    upper = text.upper()

    # 模式 1: 连续字母如 "ABC"
    m = re.match(r'^([A-H]+)$', upper.replace(' ', '').replace(',', ''))
    if m:
        return '#'.join(m.group(1))

    # 模式 2: 逐行扫描，找纯字母行
    for line in text.split('\n'):
        clean = line.strip().rstrip(',.;，。；')
        if not clean or len(clean) > 8:
            continue
        letters_only = clean.replace(',', '').replace(' ', '').upper()
        if all(c in _OPTION_LETTERS for c in letters_only):
            return '#'.join(letters_only)

    # 模式 3: 提取所有出现的选项字母
    found = sorted(set(c for c in upper if c in _OPTION_LETTERS),
                   key=lambda c: _OPTION_LETTERS.index(c))
    if len(found) >= 2:
        return '#'.join(found)

    return None
