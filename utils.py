# -*- coding: utf-8 -*-
"""
工具函数模块 v2026.6.10.1739
缓存管理、增强提示词构建、全题型答案后处理
"""
from __future__ import annotations

import time
import threading
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Dict, Any, Optional


class SimpleCache:
    """线程安全的内存缓存，支持 TTL 过期和 LRU 淘汰"""

    def __init__(self, expiration_seconds: int = 86400, max_size: int = 10000):
        self.cache: Dict[str, tuple[float, str]] = {}
        self.expiration = max(0.0, float(expiration_seconds))
        self.max_size = max(1, int(max_size))
        self._lock = threading.RLock()

    def __len__(self) -> int:
        with self._lock:
            self.remove_expired()
            return len(self.cache)

    @staticmethod
    def _generate_key(question: str, question_type: str, options: str) -> str:
        content = json.dumps([question, question_type, options], ensure_ascii=False, separators=(',', ':'))
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def get(self, question: str, question_type: str = "",
            options: str = "") -> Optional[str]:
        key = self._generate_key(question, question_type, options)
        with self._lock:
            entry = self.cache.get(key)
            if entry is None:
                return None
            ts, value = entry
            if self.expiration <= 0:
                del self.cache[key]
                return None
            if time.time() - ts < self.expiration:
                self.cache[key] = (time.time(), value)
                return value
            del self.cache[key]
            return None

    def set(self, question: str, answer: str, question_type: str = "",
            options: str = "") -> None:
        key = self._generate_key(question, question_type, options)
        with self._lock:
            self.remove_expired()
            if self.expiration <= 0:
                return
            if key not in self.cache and len(self.cache) >= self.max_size:
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
            if self.expiration <= 0:
                count = len(self.cache)
                self.cache.clear()
                return count
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


def normalize_options(options: Any) -> str:
    if options is None:
        return ""
    if isinstance(options, str):
        return _normalize_option_lines(options)
    if isinstance(options, (list, tuple)):
        return _normalize_option_lines("\n".join(_format_option_item(item) for item in options if item is not None))
    if isinstance(options, Mapping):
        if _looks_like_option_item(options):
            return _normalize_option_lines(_format_option_item(options))
        return _normalize_option_lines(
            "\n".join(_format_mapping_option(key, value) for key, value in options.items())
        )
    return _normalize_option_lines(str(options))


def _normalize_option_lines(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


_OPTION_LABEL_KEYS = ("label", "key", "id", "option", "letter", "no", "index")
_OPTION_TEXT_KEYS = ("text", "content", "value", "title", "name")


def _format_option_item(item: Any) -> str:
    if isinstance(item, Mapping):
        label = _first_mapping_value(item, _OPTION_LABEL_KEYS)
        text = _first_mapping_value(item, _OPTION_TEXT_KEYS)
        if label and text:
            return f"{_clean_option_label(label)}. {text}"
        return text or label or ""
    return str(item)


def _format_mapping_option(key: Any, value: Any) -> str:
    label = _clean_option_label(key)
    if isinstance(value, Mapping):
        formatted = _format_option_item(value)
        return formatted if _has_option_prefix(formatted) else f"{label}. {formatted}"
    text = str(value).strip()
    return f"{label}. {text}" if text else label


def _first_mapping_value(item: Mapping, keys: tuple[str, ...]) -> str:
    for key in keys:
        if key not in item:
            continue
        value = item[key]
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _looks_like_option_item(item: Mapping) -> bool:
    return any(key in item for key in _OPTION_TEXT_KEYS)


def _clean_option_label(value: Any) -> str:
    return str(value).strip().rstrip(".、．):：）")


def _has_option_prefix(text: str) -> bool:
    return bool(_OPTION_LINE_RE.match(text))


def normalize_question_type(question_type: Any) -> str:
    if question_type is None:
        return ""
    normalized = str(question_type).strip().lower()
    aliases = {
        "1": "single",
        "single": "single",
        "radio": "single",
        "单选": "single",
        "单选题": "single",
        "2": "multiple",
        "multiple": "multiple",
        "checkbox": "multiple",
        "multi": "multiple",
        "多选": "multiple",
        "多选题": "multiple",
        "3": "judgement",
        "judgement": "judgement",
        "judgment": "judgement",
        "judge": "judgement",
        "truefalse": "judgement",
        "true_false": "judgement",
        "判断": "judgement",
        "判断题": "judgement",
        "4": "completion",
        "completion": "completion",
        "fill": "completion",
        "blank": "completion",
        "填空": "completion",
        "填空题": "completion",
        "5": "short-answer",
        "short-answer": "short-answer",
        "short_answer": "short-answer",
        "shortanswer": "short-answer",
        "short": "short-answer",
        "简答": "short-answer",
        "简答题": "short-answer",
        "问答": "short-answer",
        "问答题": "short-answer",
    }
    return aliases.get(normalized, normalized)


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
        "short-answer": "【简答题】",
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
    elif question_type == "short-answer":
        return "请用简洁的完整句回答简答题。只输出答案正文，不要复述题目，也不要附加分析过程。"
    else:
        return "只输出最终答案。"


_OPTION_LETTERS = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
_OPTION_SET = frozenset(_OPTION_LETTERS)

_ANSWER_PREFIX_RE = re.compile(
    r'^(答案[是为：:]\s*|答[：:]\s*|正确答案[：:]\s*|正确[选项是]*[：:]\s*'
    r'|Answer[：:]\s*|The\s+answer\s+is\s*)+',
    re.IGNORECASE
)
_ANSWER_SUFFIX_RE = re.compile(r'[。！!；;，,]$')
_OPTION_LETTER_PREFIX_RE = re.compile(r'^[A-Ha-h](?:[.、．):：）]|\s+)\s*')
_EXPLICIT_OPTION_TEXT_RE = re.compile(r'^[A-Ha-h](?:[.、．):：）]|\s+)\s*(.+)$')
_OPTION_LINE_RE = re.compile(r'^\s*([A-Ha-h])(?:[.、．):：）]|\s+)\s*(.+?)\s*$')
_SINGLE_OPTION_LETTER_RE = re.compile(r'^\s*([A-Ha-h])(?:[.、．):：），,]|\s+|$)')
_ONLY_OPTION_LETTERS_RE = re.compile(r'^[A-Ha-h\s,，、#;；/和及与]+$')
_PREFIXED_OPTION_START_RE = re.compile(
    r'(?:^|[\r\n,，、;；]\s*)([A-Ha-h])(?:[.、．):：）]|\s+)'
)
_EXPLANATION_BOUNDARY_CHARS = frozenset(' \t\r\n,，.。;；:：!！?？)、）')


def _strip_option_letter_prefix(text: str) -> str:
    """去除选项字母前缀，如 'B. 北京' -> '北京'"""
    return _OPTION_LETTER_PREFIX_RE.sub('', text).strip()


def extract_answer(ai_response: str, question_type: str, options: str = "") -> str:
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
        exact_options = _match_complete_option_answers(cleaned, options)
        if exact_options is not None:
            return exact_options
        return _map_answer_letters_to_options(
            _process_multiple_answer(cleaned),
            options,
        )
    elif question_type == "judgement":
        return _process_judgement_answer(cleaned)
    elif question_type == "single":
        return _map_single_answer_to_option(cleaned, options)

    return cleaned


def _parse_option_texts(options: str) -> Dict[str, str]:
    result: Dict[str, str] = {}
    for line in (options or "").splitlines():
        match = _OPTION_LINE_RE.match(line)
        if not match:
            continue
        letter = match.group(1).upper()
        text = match.group(2).strip()
        if text:
            result[letter] = text
    return result


def _match_complete_option_answers(answer: str, options: str) -> Optional[str]:
    choices = sorted(set(_parse_option_texts(options).values()), key=len, reverse=True)
    if not choices:
        return None
    answer = answer.strip()
    separators = re.compile(r'[#\s,，、;；]+')
    pending = [0]
    parents = {0: None}
    for position in pending:
        for choice in choices:
            if not answer.startswith(choice, position):
                continue
            end = position + len(choice)
            if end < len(answer):
                separator = separators.match(answer, end)
                if separator is None:
                    continue
                end = separator.end()
            if end in parents:
                continue
            parents[end] = (position, choice)
            if end == len(answer):
                selected = []
                while end:
                    end, matched = parents[end]
                    selected.append(matched)
                return '#'.join(dict.fromkeys(reversed(selected)))
            pending.append(end)
    return None


def _map_answer_letters_to_options(answer: str, options: str) -> str:
    option_texts = _parse_option_texts(options)
    if not option_texts or not answer:
        return answer
    parts = [part.strip() for part in answer.split('#')]
    if not parts:
        return answer
    mapped = []
    changed = False
    for part in parts:
        key = part.upper()
        if len(key) == 1 and key in option_texts:
            mapped.append(option_texts[key])
            changed = True
        else:
            mapped.append(part)
    return '#'.join(mapped) if changed else answer


def _map_single_answer_to_option(answer: str, options: str) -> str:
    option_texts = _parse_option_texts(options)
    if not option_texts or not answer:
        return _strip_option_letter_prefix(answer)

    for option_text in option_texts.values():
        if answer == option_text:
            return option_text

    for option_text in sorted(option_texts.values(), key=len, reverse=True):
        if _starts_with_option_text(answer, option_text):
            return option_text

    letter_match = re.match(r'^\s*([A-Ha-h])(?:[.、．):：），,]|\s*$)', answer)
    if letter_match:
        letter = letter_match.group(1).upper()
        if letter in option_texts:
            return option_texts[letter]

    stripped = _strip_option_letter_prefix(answer)
    for option_text in sorted(option_texts.values(), key=len, reverse=True):
        if _starts_with_option_text(stripped, option_text):
            return option_text
    return stripped


def _starts_with_option_text(answer: str, option_text: str) -> bool:
    if answer == option_text:
        return True
    if not answer.startswith(option_text):
        return False
    next_char = answer[len(option_text):len(option_text) + 1]
    if not next_char or next_char in _EXPLANATION_BOUNDARY_CHARS:
        return True
    if option_text[-1:].isascii() and option_text[-1:].isalnum():
        return not (next_char.isascii() and next_char.isalnum())
    return False


def _process_multiple_answer(text: str) -> str:
    """多选答案处理"""
    if '#' in text:
        return _normalize_hash_separated(text)
    result = _detect_letters(text)
    if result:
        return result
    result = _normalize_prefixed_option_segments(text)
    if result:
        return result
    parts = re.split(r'[,，、;；\r\n]+', text)
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


def _normalize_prefixed_option_segments(text: str) -> Optional[str]:
    matches = list(_PREFIXED_OPTION_START_RE.finditer(text))
    if len(matches) < 2:
        return None
    parts = []
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        part = text[match.end():end].strip().strip(',，、;；')
        if part:
            parts.append(part)
    return '#'.join(parts) if len(parts) >= 2 else None


def _normalize_hash_separated(text: str) -> str:
    parts = [p.strip() for p in text.split('#') if p.strip()]
    normalized = []
    for p in parts:
        upper = p.strip().upper()
        if not upper:
            continue
        if len(upper) == 1 and upper in _OPTION_SET:
            normalized.append(upper)
        else:
            match = _EXPLICIT_OPTION_TEXT_RE.match(p)
            normalized.append(match.group(1).strip() if match else p)
    return '#'.join(normalized) if normalized else text


def _detect_letters(text: str) -> Optional[str]:
    upper = text.upper().strip()
    if not upper:
        return None
    clean = re.sub(r'[\s,，、#;；/和及与]+', '', upper)
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
    if _ONLY_OPTION_LETTERS_RE.fullmatch(text.strip()):
        letters = []
        for char in upper:
            if char in _OPTION_SET and char not in letters:
                letters.append(char)
        if len(letters) >= 2:
            return '#'.join(letters)
    return None
