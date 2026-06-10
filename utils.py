# -*- coding: utf-8 -*-
"""
工具函数模块
包含缓存管理、答案处理和 AI API 调用等辅助功能
"""
import time
import hashlib
from typing import Dict, Any, Optional, Tuple

class SimpleCache:
    """简单的内存缓存实现，支持过期时间和最大容量限制"""

    def __init__(self, expiration_seconds: int = 86400, max_size: int = 10000):
        self.cache = {}
        self.expiration = expiration_seconds
        self.max_size = max_size

    def __len__(self) -> int:
        return len(self.cache)

    def _generate_key(self, question: str, question_type: str, options: str) -> str:
        content = f"{question}|{question_type}|{options}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    def get(self, question: str, question_type: str = "", options: str = "") -> Optional[str]:
        key = self._generate_key(question, question_type, options)
        if key in self.cache:
            timestamp, value = self.cache[key]
            if time.time() - timestamp < self.expiration:
                return value
            del self.cache[key]
        return None

    def set(self, question: str, answer: str, question_type: str = "", options: str = "") -> None:
        key = self._generate_key(question, question_type, options)
        # 超过最大容量时删除最旧的条目
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.cache, key=lambda k: self.cache[k][0])
            del self.cache[oldest_key]
        self.cache[key] = (time.time(), answer)

    def clear(self) -> None:
        self.cache.clear()

    def remove_expired(self) -> int:
        now = time.time()
        expired_keys = [
            key for key, (timestamp, _) in self.cache.items()
            if now - timestamp >= self.expiration
        ]
        for key in expired_keys:
            del self.cache[key]
        return len(expired_keys)


def format_answer_for_ocs(question: str, answer: str) -> Dict[str, Any]:
    """
    格式化答案为OCS期望的格式
    
    Args:
        question: 问题内容
        answer: 答案内容
        
    Returns:
        Dict[str, Any]: 格式化后的响应
    """
    return {
        'code': 1,
        'question': question,
        'answer': answer
    }


def parse_question_and_options(question: str, options: str, question_type: str) -> str:
    """
    解析问题和选项，为 AI API 构建更好的提示

    Args:
        question: 问题内容
        options: 选项内容
        question_type: 问题类型（单选、多选、判断、填空）

    Returns:
        str: 格式化后的提示
    """
    prompt = f"问题: {question}\n"
    
    # 添加题目类型提示
    type_prompts = {
        "single": "这是一道单选题。",
        "multiple": "这是一道多选题，答案请用#符号分隔。",
        "judgement": "这是一道判断题，需要回答：正确/对/true/√ 或者 错误/错/false/×。",
        "completion": "这是一道填空题。"
    }
    
    if question_type in type_prompts:
        prompt += f"{type_prompts[question_type]}\n"
    
    if options:
        prompt += f"选项:\n{options}\n"
    
    prompt += "请直接给出答案，不要解释。"
    return prompt


def extract_answer(ai_response: str, question_type: str) -> str:
    """
    从AI响应中提取答案

    Args:
        ai_response: AI生成的完整响应
        question_type: 问题类型

    Returns:
        str: 提取的答案部分
    """
    if question_type != "multiple":
        return ai_response

    # 多选答案格式化：尝试多种模式匹配
    text = ai_response.strip()

    # 模式1：已包含 # 分隔符，直接返回
    if '#' in text:
        return text

    # 模式2：选项字母连续出现，如 "ABC" 或 "A B C" -> "A#B#C"
    option_letters = ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']
    found = [opt for opt in option_letters if opt in text.upper()]
    if len(found) >= 2:
        return '#'.join(found)

    # 模式3：按行查找，如单独一行 "AB" 或 "A,B,C"
    for line in ai_response.split('\n'):
        stripped = line.strip().rstrip(',.;，。；')
        if len(stripped) <= 8 and all(c.upper() in option_letters for c in stripped.replace(',', '').replace(' ', '')):
            letters = [c for c in stripped.upper() if c in option_letters]
            if len(letters) >= 2:
                return '#'.join(letters)

    return ai_response