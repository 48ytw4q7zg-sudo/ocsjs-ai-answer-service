# -*- coding: utf-8 -*-
"""
工具函数模块 v2026.6.10.1739
缓存管理、增强提示词构建、全题型答案后处理
"""
from __future__ import annotations

import time
import threading
import hashlib
import re
from typing import Dict, Any, Optional


class SimpleCache:
    """线程安全的内存缓存，支持 TTL 过期和 LRU 淘汰"""

    def __init__(self, expiration_seconds: int = 86400, max_size: int = 10000):
        self.cache: Dict[str, tuple[float, str]] = {}
        self.expiration = expiration_seconds
        self.max_size = max_size
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self.cache)

    @staticmethod
    def _generate_key(question: str, question_type: str, options: str) -> str:
        content = f"{question}|{question_type}|{options}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def get(self, question: str, question_type: str = "",
            options: str = "") -> Optional[str]:
        key = self._generate_key(question, question_type, options)
        with self._lock:
            entry = self.cache.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.time() - ts < self.expiration:
                self.cache[key] = (time.time(), value)
                return value
            del self.cache[key]
            return None

    def set(self, question: str, answer: str, question_type: str = "",
            options: str = "") -> None:
        key = self._generate_key(question, question_type, options)
        with self._lock:
            if len(self.cache) >= self.max_size:
                self._evict_one()
            self.cache[key] = (time.time(), answer)

    def clear(self) -> int:
        with self._lock:
            count = len(self.cache)
            self.cache.clear()
            return count

    def remove_expired(self) -> int:
        now = time.time()
        with self._lock:
            expired = [k for k, (ts, _) in self.cache.items()
                        if now - ts >= self.expiration]
            for k in expired:
                del self.cache[k]
            return len(expired)

    def _evict_one(self) -> None:
        oldest = min(self.cache, key=lambda k: self.cache[k][0])
        del self.cache[oldest]


def format_answer_for_ocs(question: str, answer: str) -> Dict[str, Any]:
    return {'code': 1, 'question': question, 'answer': answer}


def parse_question_and_options(question: str, options: str,
                               question_type: str) -> str:
    """构建完整 AI 提示词：题型标签 + 题干 + 选项 + 严格指令。

    v2026.6.10.1739 增强：
    - 指令前加「联网搜索」暗示，让 AI 更认真对待
    - 强调选项顺序可能不同，必须逐项比对
    - 填空题缺少选项时不再追加空选项段
    """
    parts = []

    # 题型标签
    type_label = {
        "single": "【单选题】", "multiple": "【多选题】",
        "judgement": "【判断题】", "completion": "【填空题】",
    }.get(question_type, "【题目】")

    parts.append(f"{type_label}{question}")

    # 选项核心上下文
    if options:
        if question_type == "single":
            parts.append(f"选项:\n{options}")
        elif question_type == "multiple":
            parts.append(f"选项（可多选）:\n{options}")
        elif question_type == "judgement":
            parts.append(f"选项:\n{options}")
        else:
            parts.append(f"选项:\n{options}")

    # 严格指令
    instructions = _build_instructions(question_type, bool(options))
    parts.append(instructions)

    return "\n\n".join(parts)


def _build_instructions(question_type: str, has_options: bool) -> str:
    """根据题型和是否有选项，生成精确的输出指令。"""
    if question_type == "single" and has_options:
        return (
            "请逐一分析每个选项的内容，判断哪个是正确的。\n"
            "警示：即使这道题你在网上见过，当前试卷的选项顺序可能不同、\n"
            '选项内容可能有微调（如"选择正确的"vs"选择错误的"）。\n'
            "必须以当前提供的选项为准，仔细比对后选择。\n"
            "只输出正确选项的完整文本内容（不是选项字母），如「北京」。"
        )
    elif question_type == "single" and not has_options:
        return "请直接回答正确答案。只输出答案本身。"
    elif question_type == "multiple" and has_options:
        return (
            "请逐一分析每个选项，选出所有正确的。\n"
            "警示：选项顺序可能被打乱，必须以当前选项内容为准。\n"
            "用 # 号分隔每个正确选项的完整文本（不是字母），如「北京#上海#广州」。"
        )
    elif question_type == "multiple" and not has_options:
        return "请用 # 号分隔每个答案。只输出答案。"
    elif question_type == "judgement":
        return (
            "请根据题目描述判断正误。\n"
            "只输出两个字：「正确」或「错误」。"
        )
    elif question_type == "completion":
        return "只输出填空处的答案文本，不要输出题目。"
    else:
        return "只输出最终答案。"


_OPTION_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
_OPTION_SET = frozenset(_OPTION_LETTERS)

_ANSWER_PREFIX_RE = re.compile(
    r'^(答案[是为：:]\s*|答[：:]\s*|正确答[案案][：:]\s*|正确[选项是]*[：:]\s*'
    r'|Answer[：:]\s*|The\s+answer\s+is\s*)+',
    re.IGNORECASE
)
_ANSWER_SUFFIX_RE = re.compile(r'[。！!；;，,]$')
_OPTION_LETTER_PREFIX_RE = re.compile(r'^[A-Ha-h][.、．)]?\s*')


def _strip_option_letter_prefix(text: str) -> str:
    """去除选项字母前缀，如 'B. 北京' -> '北京'"""
    return _OPTION_LETTER_PREFIX_RE.sub('', text).strip()


def extract_answer(ai_response: str, question_type: str) -> str:
    """从 AI 响应中提取并清洗答案。

    流程：去前缀 -> 去尾标点 -> 按题型处理
    - 多选： # 分隔标准化 + 字母检测
    - 判断：中英文统一为「正确」「错误」
    - 单选：去除选项字母前缀
    """
    text = ai_response.strip()
    if not text:
        return text

    cleaned = _ANSWER_PREFIX_RE.sub('', text).strip()
    if not cleaned:
        cleaned = text

    cleaned = _ANSWER_SUFFIX_RE.sub('', cleaned)

    if question_type == "multiple":
        return _process_multiple_answer(cleaned)
    elif question_type == "judgement":
        return _process_judgement_answer(cleaned)
    elif question_type == "single":
        return _strip_option_letter_prefix(cleaned)

    return cleaned


def _process_multiple_answer(text: str) -> str:
    """多选答案处理"""
    if '#' in text:
        return _normalize_hash_separated(text)
    result = _detect_letters(text)
    if result:
        return result
    parts = re.split(r'[,，\s、]+', text)
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) >= 2:
        return '#'.join(parts)
    return text


def _process_judgement_answer(text: str) -> str:
    """判断答案标准化"""
    positive = {'正确', '对', 'true', '√', 'yes', '是', 'right', 't', 'v'}
    negative = {'错误', '错', 'false', '×', 'no', '否', 'wrong', 'f', 'x'}
    lower = text.lower().strip()
    if lower in positive:
        return '正确'
    if lower in negative:
        return '错误'
    return text


def _normalize_hash_separated(text: str) -> str:
    parts = [p.strip() for p in text.split('#') if p.strip()]
    letters = []
    for p in parts:
        upper = p.strip().upper()
        if not upper:
            continue
        if len(upper) == 1 and upper in _OPTION_SET:
            letters.append(upper)
        else:
            first = upper[0]
            if first in _OPTION_SET:
                letters.append(first)
            else:
                letters.append(p)
    return '#'.join(letters) if letters else text


def _detect_letters(text: str) -> Optional[str]:
    upper = text.upper().strip()
    if not upper:
        return None
    clean = upper.replace(' ', '').replace(',', '').replace('，', '')
    m = re.match(r'^([A-H]+)$', clean)
    if m:
        return '#'.join(m.group(1))
    for line in text.split('\n'):
        line_clean = line.strip().rstrip(',.;，。；')
        if not line_clean or len(line_clean) > 8:
            continue
        letters_only = line_clean.replace(',', '').replace(' ', '').replace('，', '').upper()
        if letters_only and all(c in _OPTION_SET for c in letters_only):
            return '#'.join(letters_only)
    found = sorted(set(c for c in upper if c in _OPTION_SET),
                   key=lambda c: _OPTION_LETTERS.index(c))
    if len(found) >= 2:
        return '#'.join(found)
    return None
