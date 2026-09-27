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
import logging
import math
import os
import re
import sqlite3
from collections import Counter, OrderedDict, deque
from collections.abc import Mapping
from typing import Dict, Any, Optional

_logger = logging.getLogger(__name__)


class SimpleCache:
    """线程安全的答案缓存：空闲 TTL 过期 + O(1) LRU 淘汰 + 命中率统计。

    namespace（协议|模型|提示词版本）写进缓存键：换模型或升级提示词后，旧答案不会被命中。
    store 是可选的磁盘持久层（PersistentAnswerStore）；不设置时只在内存中。
    """

    def __init__(self, expiration_seconds: int = 86400, max_size: int = 10000,
                 namespace: str = "", store: "Optional[PersistentAnswerStore]" = None):
        # key -> (最近访问时间, 答案, 写入时间)；OrderedDict 顺序即 LRU 顺序。
        self.cache: "OrderedDict[str, tuple[float, str, float]]" = OrderedDict()
        self.expiration = max(0.0, float(expiration_seconds))
        self.max_size = max(1, int(max_size))
        self.namespace = str(namespace or "")
        self.store = store
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    def __len__(self) -> int:
        with self._lock:
            self.remove_expired()
            return len(self.cache)

    def _generate_key(self, question: str, question_type: str, options: str) -> str:
        parts = [question, question_type, options]
        if self.namespace:
            parts.insert(0, self.namespace)
        content = json.dumps(parts, ensure_ascii=False, separators=(',', ':'))
        return hashlib.sha256(content.encode('utf-8')).hexdigest()

    def get_with_age(self, question: str, question_type: str = "",
                     options: str = "") -> Optional[tuple[str, float]]:
        """返回 (答案, 距首次写入的秒数)；未命中返回 None。内存未命中时再查磁盘层。"""
        key = self._generate_key(question, question_type, options)
        with self._lock:
            entry = self.cache.get(key)
            now = time.time()
            if entry is not None and (self.expiration <= 0 or now - entry[0] >= self.expiration):
                del self.cache[key]
                entry = None
            if entry is None and self.store is not None and self.expiration > 0:
                stored = self.store.get(key, now, self.expiration)
                if stored is not None:
                    while len(self.cache) >= self.max_size:
                        self._evict_one()
                    entry = (now, stored[0], stored[1])
            if entry is None:
                self.misses += 1
                return None
            _, value, created = entry
            self.cache[key] = (now, value, created)
            self.cache.move_to_end(key)
            self.hits += 1
            return value, max(0.0, now - created)

    def get(self, question: str, question_type: str = "",
            options: str = "") -> Optional[str]:
        result = self.get_with_age(question, question_type, options)
        return result[0] if result is not None else None

    def set(self, question: str, answer: str, question_type: str = "",
            options: str = "") -> None:
        key = self._generate_key(question, question_type, options)
        with self._lock:
            self.remove_expired()
            if self.expiration <= 0:
                return
            now = time.time()
            if key in self.cache:
                created = self.cache[key][2]
                self.cache.move_to_end(key)
            else:
                while len(self.cache) >= self.max_size:
                    self._evict_one()
                created = now
            self.cache[key] = (now, answer, created)
            if self.store is not None:
                self.store.put(key, answer, created, now, self.expiration, self.max_size)

    def clear(self) -> int:
        with self._lock:
            count = len(self.cache)
            self.cache.clear()
            if self.store is not None:
                count = max(count, self.store.clear())
            return count

    def remove_expired(self) -> int:
        now = time.time()
        with self._lock:
            if self.expiration <= 0:
                count = len(self.cache)
                self.cache.clear()
                return count
            expired = [k for k, (ts, _value, _created) in self.cache.items()
                       if now - ts >= self.expiration]
            for k in expired:
                del self.cache[k]
            return len(expired)

    def _evict_one(self) -> None:
        self.cache.popitem(last=False)
        self.evictions += 1

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            lookups = self.hits + self.misses
            return {
                'size': len(self.cache), 'max_size': self.max_size,
                'hits': self.hits, 'misses': self.misses, 'evictions': self.evictions,
                'hit_rate': round(self.hits / lookups, 4) if lookups else None,
                'persisted': self.store.count() if self.store is not None else None,
            }


class PersistentAnswerStore:
    """可选的答案磁盘缓存（SQLite）：只存题目哈希键、答案和时间戳，不存题目原文。

    任何磁盘/数据库错误都只记一次日志并降级为纯内存缓存，不影响答题。
    """

    def __init__(self, path) -> None:
        self.path = str(path)
        self.available = True
        self._lock = threading.Lock()
        self._writes = 0
        self._connection = None
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            self._connection = sqlite3.connect(self.path, timeout=5, check_same_thread=False, isolation_level=None)
            self._connection.execute(
                "CREATE TABLE IF NOT EXISTS answers (key TEXT PRIMARY KEY, answer TEXT NOT NULL, "
                "created REAL NOT NULL, accessed REAL NOT NULL)")
        except (sqlite3.Error, OSError, ValueError) as exc:
            self._disable(exc)

    def _disable(self, exc) -> None:
        self.available = False
        _logger.warning("答案磁盘缓存不可用，已改为仅内存缓存: %s", type(exc).__name__)
        if self._connection is not None:
            try:
                self._connection.close()
            except sqlite3.Error:
                pass
            self._connection = None

    def _run(self, operation, default=None):
        with self._lock:
            if not self.available:
                return default
            try:
                return operation(self._connection)
            except sqlite3.Error as exc:
                self._disable(exc)
                return default

    def get(self, key: str, now: float, expiration: float) -> Optional[tuple[str, float]]:
        def operation(db):
            row = db.execute("SELECT answer, created, accessed FROM answers WHERE key = ?", (key,)).fetchone()
            if row is None:
                return None
            if now - row[2] >= expiration:
                db.execute("DELETE FROM answers WHERE key = ?", (key,))
                return None
            db.execute("UPDATE answers SET accessed = ? WHERE key = ?", (now, key))
            return row[0], row[1]
        return self._run(operation)

    def put(self, key: str, answer: str, created: float, now: float, expiration: float, max_rows: int) -> None:
        def operation(db):
            db.execute("INSERT OR REPLACE INTO answers (key, answer, created, accessed) VALUES (?, ?, ?, ?)",
                       (key, answer, created, now))
            self._writes += 1
            if self._writes % 100 == 1:
                # 顺带清理过期记录，并把总量控制在上限内（按最近访问保留）。
                db.execute("DELETE FROM answers WHERE accessed <= ?", (now - expiration,))
                db.execute("DELETE FROM answers WHERE key IN "
                           "(SELECT key FROM answers ORDER BY accessed DESC LIMIT -1 OFFSET ?)", (int(max_rows),))
        self._run(operation)

    def clear(self) -> int:
        return self._run(lambda db: db.execute("DELETE FROM answers").rowcount, 0)

    def count(self) -> int:
        return self._run(lambda db: db.execute("SELECT COUNT(*) FROM answers").fetchone()[0], 0)

    def close(self) -> None:
        with self._lock:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
            self.available = False


class PromptText(str):
    """携带题型与简化版提示词的 str；_call_ai 的调用签名保持为单个参数。"""

    question_type: str = ""
    simple: Optional[str] = None

    def __new__(cls, text: str, *, question_type: str = "", simple: Optional[str] = None):
        value = super().__new__(cls, text)
        value.question_type = question_type
        value.simple = simple
        return value


class RateLimiter:
    """按客户端的滑动窗口限流（每分钟 N 次 AI 调用），防止脚本刷爆上游费用。"""

    def __init__(self, max_keys: int = 4096):
        self._lock = threading.Lock()
        self._events: "OrderedDict[str, deque]" = OrderedDict()
        self._max_keys = max(1, int(max_keys))

    def acquire(self, key: str, limit_per_minute: int, now: Optional[float] = None) -> tuple[bool, int]:
        if not limit_per_minute or limit_per_minute <= 0:
            return True, 0
        now = time.monotonic() if now is None else now
        with self._lock:
            events = self._events.get(key)
            if events is None:
                events = deque()
                self._events[key] = events
                while len(self._events) > self._max_keys:
                    self._events.popitem(last=False)
            self._events.move_to_end(key)
            while events and now - events[0] >= 60:
                events.popleft()
            if len(events) >= limit_per_minute:
                return False, max(1, math.ceil(60 - (now - events[0])))
            events.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


class ServiceMetrics:
    """进程内运行指标：请求量、失败分类、缓存命中、AI 重试、延迟分位与最近 1 分钟 QPS。"""

    def __init__(self, window: int = 500):
        self._lock = threading.Lock()
        self.counters: Counter = Counter()
        self.failures: Counter = Counter()
        self.ai_failures: Counter = Counter()
        self.extraction_paths: Counter = Counter()
        self.latencies: deque = deque(maxlen=max(1, int(window)))
        self.recent: deque = deque()

    def incr(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self.counters[name] += amount

    def record_ai_failure(self, category: str) -> None:
        with self._lock:
            self.ai_failures[category] += 1

    def record_search(self, seconds: float, error_code: Optional[str] = None, *, cached: bool = False) -> None:
        now = time.monotonic()
        with self._lock:
            self.counters['search_requests'] += 1
            if error_code:
                self.failures[error_code] += 1
            else:
                self.counters['search_success'] += 1
                if cached:
                    self.counters['search_cached'] += 1
            self.latencies.append(max(0.0, seconds))
            self.recent.append(now)
            while self.recent and now - self.recent[0] > 60:
                self.recent.popleft()

    def record_extraction_path(self, path: str) -> None:
        with self._lock:
            self.extraction_paths[path] += 1

    @staticmethod
    def _percentile(values: list, fraction: float) -> Optional[float]:
        if not values:
            return None
        ordered = sorted(values)
        index = min(len(ordered) - 1, max(0, math.ceil(fraction * len(ordered)) - 1))
        return round(ordered[index] * 1000, 1)

    def snapshot(self) -> Dict[str, Any]:
        now = time.monotonic()
        with self._lock:
            while self.recent and now - self.recent[0] > 60:
                self.recent.popleft()
            latencies = list(self.latencies)
            ai_calls = self.counters['ai_calls']
            total = self.counters['search_requests']
            return {
                'search_requests': total,
                'search_success': self.counters['search_success'],
                'search_cached': self.counters['search_cached'],
                'failures': dict(self.failures),
                'failure_rate': round(sum(self.failures.values()) / total, 4) if total else None,
                'ai_calls': ai_calls,
                'ai_retries': self.counters['ai_retries'],
                'retry_rate': round(self.counters['ai_retries'] / ai_calls, 4) if ai_calls else None,
                'ai_failures': dict(self.ai_failures),
                'extraction_paths': dict(self.extraction_paths),
                'qps_1m': round(len(self.recent) / 60, 3),
                'latency_ms': {
                    'p50': self._percentile(latencies, 0.5),
                    'p95': self._percentile(latencies, 0.95),
                    'max': round(max(latencies) * 1000, 1) if latencies else None,
                    'samples': len(latencies),
                },
            }


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
    # 只统一换行、去掉空行与首尾空白；不删 HTML 标记和实体，“<p>”这类字面选项要原样保留。
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def count_options(options: str) -> int:
    """带字母标号的选项按标号行计数（长选项可能折成多行），没有标号时按非空行计数。"""
    lines = [line for line in (options or "").splitlines() if line.strip()]
    labeled = sum(1 for line in lines if _OPTION_LINE_RE.match(line))
    return labeled or len(lines)


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


KNOWN_QUESTION_TYPES = frozenset({"single", "multiple", "judgement", "completion", "short-answer"})
_TYPE_LABELS = {
    "single": "【单选题】", "multiple": "【多选题】",
    "judgement": "【判断题】", "completion": "【填空题】",
    "short-answer": "【简答题】",
}


# 定界标记的各种变体（空格、全角尖括号/斜杠）；题干里伪造的 <选项> 块也要去掉。
_DELIMITER_TAG_RE = re.compile(r"[<＜]\s*[/／]?\s*(?:题干|选项)\s*[>＞]")


def _quote_block(tag: str, text: str) -> str:
    # 题目数据放进定界块，并去掉内容中伪造的定界标记，防止“越狱”到指令区。
    safe = _DELIMITER_TAG_RE.sub("", text)
    return f"<{tag}>\n{safe}\n</{tag}>"


def parse_question_and_options(question: str, options: str,
                               question_type: str) -> str:
    """构建完整 AI 提示词：题型标签 + 定界的题干/选项 + 严格指令。

    - 题干和选项放在 <题干>/<选项> 定界块中；系统提示要求照常完成题目本身的作答要求，
      但不执行其中改变身份、忽略规则或改变输出格式的语句
    - 强调选项顺序可能不同，必须逐项比对
    - 填空题缺少选项时不再追加空选项段
    """
    parts = []

    type_label = _TYPE_LABELS.get(question_type, "【题目】")
    parts.append(f"{type_label}\n{_quote_block('题干', question)}")

    if options:
        heading = "选项（可多选）:" if question_type == "multiple" else "选项:"
        parts.append(f"{heading}\n{_quote_block('选项', options)}")

    parts.append(_build_instructions(question_type, bool(options)))

    return "\n\n".join(parts)


def build_simple_prompt(question: str, options: str, question_type: str) -> str:
    """重试用的极简提示：保留完整题干与全部选项，只去掉冗长指令。"""
    parts = [f"{_TYPE_LABELS.get(question_type, '【题目】')}\n{_quote_block('题干', question)}"]
    if options:
        parts.append(f"选项:\n{_quote_block('选项', options)}")
    parts.append("只输出最终答案。")
    return "\n\n".join(parts)


# 系统提示要求无法确定时只输出“无法确定”，这类完整回答在任何题型都视为拒答；
# 其余说法只在选择/判断题（含未标题型但带选项的题）中视为拒答（填空、简答的答案本身可能就是“不知道”“unknown”）。
_REFUSAL_EXACT = frozenset({"无法确定", "cannot determine"})
_CHOICE_REFUSAL_EXACT = frozenset({
    "无法判断", "无法回答", "无法得出答案", "不确定", "不知道", "我不知道", "i don't know", "i do not know", "not sure",
})
_REFUSAL_PREFIXES = ("无法确定", "抱歉", "对不起", "作为一个ai", "作为ai", "作为 ai", "i'm sorry", "sorry,")
_CHOICE_QUESTION_TYPES = frozenset({"single", "multiple", "judgement"})
_REFUSAL_STRIP_RE = re.compile(r"[\s。．.!！?？,，;；:：「」“”\"'（）()]+")
_REFUSAL_NORMALIZED = frozenset(_REFUSAL_STRIP_RE.sub("", item) for item in _REFUSAL_EXACT)
_CHOICE_REFUSAL_NORMALIZED = frozenset(_REFUSAL_STRIP_RE.sub("", item) for item in _CHOICE_REFUSAL_EXACT)


def _option_answer_forms(options: str) -> set:
    """选项文本的比较形式；没有字母标号时整行就是选项。"""
    labeled = _parse_option_texts(options)
    values = labeled.values() if labeled else (line.strip() for line in (options or "").splitlines())
    return {_REFUSAL_STRIP_RE.sub("", value.lower()) for value in values if value}


def looks_like_refusal(answer: str, question_type: str = "", options: str = "") -> bool:
    text = (answer or "").strip().lower()
    if not text:
        return True
    # 答案本身就是某个选项（如语文题选项“抱歉，我来晚了”）时不算拒答。
    option_forms = _option_answer_forms(options)
    parts = [_REFUSAL_STRIP_RE.sub("", part) for part in text.split('#') if part.strip()]
    if option_forms and parts and all(part in option_forms for part in parts):
        return False
    normalized = _REFUSAL_STRIP_RE.sub("", text)
    if normalized in _REFUSAL_NORMALIZED:
        return True
    # 未标题型但带选项的题目按选择题处理。
    if question_type not in _CHOICE_QUESTION_TYPES and (question_type or not options):
        return False
    return normalized in _CHOICE_REFUSAL_NORMALIZED or text.startswith(_REFUSAL_PREFIXES)


# 只作告警统计，不拦截；“扮演”“你现在是”在情景题里很常见，不再计入。
_INJECTION_RE = re.compile(
    r"忽略(?:以上|之前|前面|上述)|无视(?:以上|之前)|系统提示|system\s*prompt|"
    r"ignore\s+(?:all\s+)?(?:previous|above)|disregard\s+(?:all\s+)?(?:previous|above)|"
    r"[<＜]\s*[/／]?\s*(?:题干|选项)\s*[>＞]",
    re.I,
)


def looks_like_prompt_injection(*texts: str) -> bool:
    return any(_INJECTION_RE.search(text or "") for text in texts)


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


def extract_answer(ai_response: str, question_type: str, options: str = "",
                   trace: Optional[list] = None) -> str:
    """从 AI 响应中提取并清洗答案。

    流程：去前缀 -> 去尾标点 -> 按题型处理
    - 多选： # 分隔标准化 + 字母检测
    - 判断：中英文统一为「正确」「错误」
    - 单选：去除选项字母前缀

    trace 非空时追加命中的处理路径，用于统计启发式规则的实际效果。
    """
    def mark(path: str) -> None:
        if trace is not None:
            trace.append(path)

    text = ai_response.strip()
    if not text:
        mark("empty")
        return text

    cleaned = _ANSWER_PREFIX_RE.sub('', text).strip()
    if not cleaned:
        cleaned = text

    cleaned = _ANSWER_SUFFIX_RE.sub('', cleaned)

    if question_type == "multiple":
        exact_options = _match_complete_option_answers(cleaned, options)
        if exact_options is not None:
            mark("multiple_option_text")
            return exact_options
        mark("multiple_letters_or_split")
        return _map_answer_letters_to_options(
            _process_multiple_answer(cleaned),
            options,
        )
    elif question_type == "judgement":
        mark("judgement")
        return _process_judgement_answer(cleaned)
    elif question_type == "single":
        mapped = _map_single_answer_to_option(cleaned, options)
        mark("single_option" if mapped in _parse_option_texts(options).values() else "single_free_text")
        return mapped

    mark("free_text")
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
