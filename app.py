# -*- coding: utf-8 -*-
"""
EduBrain AI - 智能题库系统 v2.2.0
基于 Anthropic 兼容协议的智能题库服务，支持 ccswitch 动态配置
优先通过 ccswitch 代理调用 API，自动读取 Claude Code 的实时配置
新增：增强提示词（题目+选项强制合并）、空答案自动重试、DeepSeek 深度适配
作者：QXW
版本：2.2.0
"""
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os
import time
import logging
import anthropic
from collections import deque
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from config import Config, reload_config
from utils import SimpleCache, format_answer_for_ocs, parse_question_and_options, extract_answer
from logger import setup_logger

level = getattr(logging, Config.LOG_LEVEL, logging.INFO)
logger = setup_logger('ai_answer_service', level=level)

logger.info(f"配置来源: {Config.CONFIG_SOURCE}")
logger.info(f"AI 模型: {Config.ANTHROPIC_MODEL}, Base URL: {Config.ANTHROPIC_BASE_URL}")
if Config.CCSWITCH_RAW_MODEL and Config.CCSWITCH_RAW_MODEL != Config.ANTHROPIC_MODEL:
    logger.info(f"模型名已净化: '{Config.CCSWITCH_RAW_MODEL}' → '{Config.ANTHROPIC_MODEL}'")

app = Flask(__name__)
CORS(app)

cache = SimpleCache(Config.CACHE_EXPIRATION) if Config.ENABLE_CACHE else None

if not Config.ANTHROPIC_API_KEY:
    logger.critical("未设置 Anthropic API 密钥，请在 .env 文件中配置 ANTHROPIC_API_KEY")
    raise ValueError("请设置环境变量 ANTHROPIC_API_KEY")

client = anthropic.Anthropic(
    api_key=Config.ANTHROPIC_API_KEY,
    base_url=Config.ANTHROPIC_BASE_URL,
    timeout=Config.API_TIMEOUT,
    max_retries=Config.API_MAX_RETRIES,
)

MAX_RECORDS = 100
qa_records = deque(maxlen=MAX_RECORDS)
start_time = time.time()

SYSTEM_PROMPT = (
    "你是一个考试答题助手，为在线答题系统提供精准答案。\n"
    "\n"
    "## 核心规则\n"
    "1. 必须基于用户提供的具体选项来回答，不要凭记忆作答\n"
    "2. 如果题目与网络常见题相同但选项顺序不同，必须按实际选项回答\n"
    "3. 输出答案内容 / 选项字母，不要任何解释\n"
    "4. 不要输出「答案：」「答案是」等前缀\n"
    "\n"
    "## 输出格式\n"
    "- 单选题：输出选项字母（如 A）或正确选项的完整文本（如 北京）\n"
    "- 多选题：用#分隔选项字母（如 A#C#D）\n"
    "- 判断题：输出「正确」或「错误」\n"
    "- 填空题：输出填空处的答案文本"
)

_SERVER_VERSION = "2.2.0"


def verify_access_token(req):
    if Config.ACCESS_TOKEN:
        token = req.headers.get('X-Access-Token') or req.args.get('token')
        if not token or token != Config.ACCESS_TOKEN:
            return False
    return True


def build_ai_client():
    return anthropic.Anthropic(
        api_key=Config.ANTHROPIC_API_KEY,
        base_url=Config.ANTHROPIC_BASE_URL,
        timeout=Config.API_TIMEOUT,
        max_retries=Config.API_MAX_RETRIES,
    )


def _call_ai(prompt: str, max_tokens: int = 300) -> str | None:
    """调用 AI API，重试 2 次（含备选提示词策略）"""
    # 第 1 次：正常调用
    for attempt in range(2):
        try:
            response = client.messages.create(
                model=Config.ANTHROPIC_MODEL,
                temperature=0.3 if attempt > 0 else Config.TEMPERATURE,
                max_tokens=max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            if response.content and len(response.content) > 0:
                block = response.content[0]
                if hasattr(block, 'text') and block.text and block.text.strip():
                    return block.text.strip()
        except (anthropic.APIStatusError, anthropic.APITimeoutError, anthropic.APIConnectionError):
            if attempt == 1:
                raise
        if attempt == 0:
            logger.warning(f"AI 返回空文本，尝试第 {attempt + 2} 次（降温 + 更短提示）...")

    return None


@app.route('/api/search', methods=['GET', 'POST'])
def search():
    t_start = time.time()

    if not verify_access_token(request):
        return jsonify({'code': 0, 'msg': '无效的访问令牌'}), 403

    try:
        if request.method == 'GET':
            question = request.args.get('title', '')
            question_type = request.args.get('type', '')
            options = request.args.get('options', '')
        else:
            content_type = request.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                data = request.get_json(silent=True)
                if data is None:
                    return jsonify({'code': 0, 'msg': '无效的JSON格式'}), 400
                question = data.get('title', '')
                question_type = data.get('type', '')
                options = data.get('options', '')
            else:
                question = request.form.get('title', '')
                question_type = request.form.get('type', '')
                options = request.form.get('options', '')

        if not question:
            logger.warning("未提供问题内容")
            return jsonify({'code': 0, 'msg': '未提供问题内容'})

        question = question.strip()
        if len(question) > Config.MAX_QUESTION_LENGTH:
            return jsonify({'code': 0, 'msg': f'问题内容过长，最大{Config.MAX_QUESTION_LENGTH}字符'}), 400

        logger.info(f"接收到问题: '{question[:80]}...' (类型: {question_type}, 选项: {bool(options)})")

        if cache is not None:
            cached_answer = cache.get(question, question_type, options)
            if cached_answer:
                elapsed = time.time() - t_start
                logger.info(f"从缓存获取答案 (耗时: {elapsed:.2f}秒)")
                return jsonify(format_answer_for_ocs(question, cached_answer))

        # 构建完整提示词（题目+选项+题型+指令）
        full_prompt = parse_question_and_options(question, options, question_type)
        logger.debug(f"AI 提示词: {full_prompt[:200]}...")

        ai_answer = _call_ai(full_prompt)
        if ai_answer is None:
            return jsonify({'code': 0, 'msg': 'AI 未返回有效答案'})

        processed_answer = extract_answer(ai_answer, question_type)

        if cache is not None:
            cache.set(question, processed_answer, question_type, options)

        current_time = datetime.now(timezone.utc)
        qa_records.append({
            'time': current_time.strftime('%Y-%m-%d %H:%M:%S'),
            'timestamp': current_time.isoformat(),
            'question': question,
            'type': question_type or '未指定',
            'options': options,
            'answer': processed_answer,
        })

        elapsed = time.time() - t_start
        logger.info(f"问题处理完成 (耗时: {elapsed:.2f}秒, 答案: {processed_answer})")

        return jsonify(format_answer_for_ocs(question, processed_answer))

    except anthropic.APIStatusError as e:
        logger.error(f"API 错误 (status={e.status_code}): {e.message}")
        return jsonify({'code': 0, 'msg': f'AI服务暂时不可用 (HTTP {e.status_code})'}), 503

    except anthropic.APITimeoutError:
        logger.error("API 请求超时")
        return jsonify({'code': 0, 'msg': 'AI服务响应超时，请重试'}), 504

    except anthropic.APIConnectionError:
        logger.error("API 连接失败")
        return jsonify({'code': 0, 'msg': '无法连接到AI服务'}), 502

    except Exception as e:
        logger.error(f"处理问题时发生错误: {str(e)}", exc_info=True)
        return jsonify({'code': 0, 'msg': '服务内部错误'}), 500


@app.route('/api/health', methods=['GET'])
def health_check():
    uptime_seconds = time.time() - start_time
    result = {
        'status': 'ok',
        'message': 'AI题库服务运行正常',
        'version': _SERVER_VERSION,
        'config_source': Config.CONFIG_SOURCE,
        'cache_enabled': Config.ENABLE_CACHE,
        'cache_size': len(cache) if cache is not None else 0,
        'model': Config.ANTHROPIC_MODEL,
        'base_url': Config.ANTHROPIC_BASE_URL,
        'uptime_seconds': round(uptime_seconds, 2),
    }
    if Config.CONFIG_SOURCE == 'ccswitch':
        result['ccswitch'] = {
            'raw_model': Config.CCSWITCH_RAW_MODEL,
            'is_proxy': Config.CCSWITCH_IS_PROXY,
            'model_sanitized': Config.CCSWITCH_RAW_MODEL != Config.ANTHROPIC_MODEL,
        }
        result['config_keys'] = list(Config.EXTRA_ENV.keys()) if Config.EXTRA_ENV else []
    return jsonify(result)


@app.route('/api/config/reload', methods=['POST'])
def config_reload():
    if not verify_access_token(request):
        return jsonify({'success': False, 'message': '无效的访问令牌'}), 403
    success = reload_config()
    if success:
        global client
        client = build_ai_client()
        logger.info(f"配置已重新加载: model={Config.ANTHROPIC_MODEL}, base_url={Config.ANTHROPIC_BASE_URL}")
        return jsonify({
            'success': True, 'message': '配置已从 ccswitch 重新加载',
            'config_source': Config.CONFIG_SOURCE, 'model': Config.ANTHROPIC_MODEL,
            'base_url': Config.ANTHROPIC_BASE_URL, 'raw_model': Config.CCSWITCH_RAW_MODEL,
        })
    else:
        return jsonify({
            'success': True, 'message': 'ccswitch 不可用，已回退到 .env 配置',
            'config_source': Config.CONFIG_SOURCE, 'model': Config.ANTHROPIC_MODEL,
        })


@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    if not verify_access_token(request):
        return jsonify({'success': False, 'message': '无效的访问令牌'}), 403
    if cache is None:
        return jsonify({'success': False, 'message': '缓存未启用'})
    count = cache.clear()
    return jsonify({'success': True, 'message': f'缓存已清除 ({count}条)', 'count': count})


@app.route('/api/stats', methods=['GET'])
def get_stats():
    if not verify_access_token(request):
        return jsonify({'success': False, 'message': '无效的访问令牌'}), 403
    stats = {
        'version': _SERVER_VERSION, 'config_source': Config.CONFIG_SOURCE,
        'uptime': time.time() - start_time, 'model': Config.ANTHROPIC_MODEL,
        'base_url': Config.ANTHROPIC_BASE_URL, 'cache_enabled': Config.ENABLE_CACHE,
        'cache_size': len(cache) if cache is not None else 0,
        'qa_records_count': len(qa_records),
    }
    if Config.CONFIG_SOURCE == 'ccswitch':
        stats['ccswitch_raw_model'] = Config.CCSWITCH_RAW_MODEL
        stats['ccswitch_is_proxy'] = Config.CCSWITCH_IS_PROXY
    return jsonify(stats)


@app.route('/dashboard', methods=['GET'])
def dashboard():
    uptime_seconds = time.time() - start_time
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    uptime_str = f"{days}天{hours}小时{minutes}分钟"
    ccswitch_info = None
    if Config.CONFIG_SOURCE == 'ccswitch':
        ccswitch_info = {
            'raw_model': Config.CCSWITCH_RAW_MODEL,
            'sanitized_model': Config.ANTHROPIC_MODEL,
            'is_proxy': Config.CCSWITCH_IS_PROXY,
            'base_url': Config.ANTHROPIC_BASE_URL,
            'extra_env': Config.EXTRA_ENV,
        }
    return render_template(
        'dashboard.html', version=_SERVER_VERSION, config_source=Config.CONFIG_SOURCE,
        cache_enabled=Config.ENABLE_CACHE,
        cache_size=len(cache.cache) if cache is not None else 0,
        model=Config.ANTHROPIC_MODEL, uptime=uptime_str, records=qa_records,
        ccswitch_info=ccswitch_info,
    )


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html', version=_SERVER_VERSION)


@app.route('/docs', methods=['GET'])
def docs():
    doc_path = os.path.join(os.path.dirname(__file__), 'api_docs.md')
    with open(doc_path, 'r', encoding='utf-8') as f:
        content = f.read()
    try:
        import markdown
        html_content = markdown.markdown(content, extensions=['tables'])
        return f"""<html><head><title>AI题库服务 - API文档 v{_SERVER_VERSION}</title>
<style>body{{font-family:Arial,sans-serif;margin:40px;line-height:1.6}}h1,h2,h3{{color:#2c3e50}}.container{{max-width:800px;margin:0 auto}}code{{background:#e0e0e0;padding:2px 4px;border-radius:3px}}pre{{background:#f4f4f4;padding:10px;border-radius:4px;overflow-x:auto}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px}}th{{background-color:#f4f4f4}}</style></head>
<body><div class="container">{html_content}</div></body></html>"""
    except ImportError:
        return f"""<html><head><title>AI题库服务 - API文档 v{_SERVER_VERSION}</title>
<style>body{{font-family:Arial,sans-serif;margin:40px;line-height:1.6}}h1{{color:#333}}.container{{max-width:800px;margin:0 auto}}pre{{background:#f4f4f4;padding:10px;border-radius:4px;overflow-x:auto}}</style></head>
<body><div class="container"><h1>AI题库服务 - API文档 v{_SERVER_VERSION}</h1><pre>{content}</pre></div></body></html>"""


if __name__ == '__main__':
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
