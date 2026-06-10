# -*- coding: utf-8 -*-
"""
EduBrain AI - 智能题库系统
基于 Anthropic 兼容协议的智能题库服务，支持 ccswitch 动态配置
优先通过 ccswitch 代理调用 API，自动读取 Claude Code 的实时配置
作者：Lynn
版本：2.0.0
"""
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os
import time
import logging
import anthropic
from collections import deque
from datetime import datetime, timezone

# 导入 config 前配置根 logger（防止子模块 "No handler found" 警告），
# 真正的日志配置由 setup_logger 完成
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

from config import Config
from utils import SimpleCache, format_answer_for_ocs, parse_question_and_options, extract_answer
from logger import setup_logger

# 用 RotatingFileHandler 重新配置日志
level = getattr(logging, Config.LOG_LEVEL, logging.INFO)
logger = setup_logger('ai_answer_service', level=level)

# 记录配置来源
logger.info(f"配置来源: {Config.CONFIG_SOURCE}")
logger.info(f"AI 模型: {Config.ANTHROPIC_MODEL}, Base URL: {Config.ANTHROPIC_BASE_URL}")

# 初始化应用
app = Flask(__name__)
CORS(app)

# 初始化缓存
cache = SimpleCache(Config.CACHE_EXPIRATION) if Config.ENABLE_CACHE else None

# 验证 Anthropic API 密钥
if not Config.ANTHROPIC_API_KEY:
    logger.critical("未设置 Anthropic API 密钥，请在 .env 文件中配置 ANTHROPIC_API_KEY")
    raise ValueError("请设置环境变量 ANTHROPIC_API_KEY")

# 初始化 Anthropic 客户端（连接 DeepSeek API）
client = anthropic.Anthropic(
    api_key=Config.ANTHROPIC_API_KEY,
    base_url=Config.ANTHROPIC_BASE_URL,
    timeout=Config.API_TIMEOUT,
    max_retries=Config.API_MAX_RETRIES,
)

# 问答记录存储
MAX_RECORDS = 100
qa_records = deque(maxlen=MAX_RECORDS)
start_time = time.time()

# AI 系统提示词
SYSTEM_PROMPT = (
    "你是一个专业的考试答题助手。请直接回答答案，不要解释。"
    "选择题只回答选项的内容(如：地球)；"
    "多选题用#号分隔答案,只回答选项的内容(如中国#世界#地球)；"
    "判断题只回答: 正确/对/true/√ 或 错误/错/false/×；"
    "填空题直接给出答案。"
)

_SERVER_VERSION = "2.0.0"


def verify_access_token(req):
    """验证访问令牌（如果配置了的话）"""
    if Config.ACCESS_TOKEN:
        token = req.headers.get('X-Access-Token') or req.args.get('token')
        if not token or token != Config.ACCESS_TOKEN:
            return False
    return True


@app.route('/api/search', methods=['GET', 'POST'])
def search():
    """
    处理OCS发送的搜索请求，使用 DeepSeek API 生成答案
    GET请求: 从URL参数获取问题
    POST请求: 从请求体获取问题

    参数:
        title: 问题内容
        type: 问题类型 (single-单选, multiple-多选, judgement-判断, completion-填空)
        options: 选项内容

    返回:
        成功: {'code': 1, 'question': '问题', 'answer': 'AI生成的答案'}
        失败: {'code': 0, 'msg': '错误信息'}
    """
    t_start = time.time()

    if not verify_access_token(request):
        return jsonify({'code': 0, 'msg': '无效的访问令牌'}), 403

    try:
        # 根据请求方法获取问题内容
        if request.method == 'GET':
            question = request.args.get('title', '')
            question_type = request.args.get('type', '')
            options = request.args.get('options', '')
        else:  # POST
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

        logger.info(f"接收到问题: '{question[:80]}...' (类型: {question_type})")

        # 检查缓存中是否有此问题的答案
        if cache is not None:
            cached_answer = cache.get(question, question_type, options)
            if cached_answer:
                elapsed = time.time() - t_start
                logger.info(f"从缓存获取答案 (耗时: {elapsed:.2f}秒)")
                return jsonify(format_answer_for_ocs(question, cached_answer))

        # 构建发送给 AI 的提示
        prompt = parse_question_and_options(question, options, question_type)

        # 调用 AI API
        response = client.messages.create(
            model=Config.ANTHROPIC_MODEL,
            temperature=Config.TEMPERATURE,
            max_tokens=Config.MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": prompt}
            ],
        )

        # 安全获取 AI 响应内容
        if response.content and len(response.content) > 0:
            first_block = response.content[0]
            if hasattr(first_block, 'text') and first_block.text:
                ai_answer = first_block.text.strip()
            else:
                logger.warning("AI 返回空文本块")
                return jsonify({'code': 0, 'msg': 'AI 未返回有效答案'})
        else:
            logger.warning("AI 返回空响应")
            return jsonify({'code': 0, 'msg': 'AI 未返回有效答案'})

        # 处理答案格式
        processed_answer = extract_answer(ai_answer, question_type)

        # 保存到缓存
        if cache is not None:
            cache.set(question, processed_answer, question_type, options)

        # 保存问答记录
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
        logger.info(f"问题处理完成 (耗时: {elapsed:.2f}秒)")

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
    """健康检查接口"""
    return jsonify({
        'status': 'ok',
        'message': 'AI题库服务运行正常',
        'version': _SERVER_VERSION,
        'config_source': Config.CONFIG_SOURCE,
        'cache_enabled': Config.ENABLE_CACHE,
        'model': Config.ANTHROPIC_MODEL,
    })


@app.route('/api/cache/clear', methods=['POST'])
def clear_cache():
    """清除缓存接口"""
    if not verify_access_token(request):
        return jsonify({'success': False, 'message': '无效的访问令牌'}), 403

    if cache is None:
        return jsonify({'success': False, 'message': '缓存未启用'})

    count = cache.clear()
    return jsonify({'success': True, 'message': f'缓存已清除 ({count}条)', 'count': count})


@app.route('/api/stats', methods=['GET'])
def get_stats():
    """获取服务统计信息"""
    if not verify_access_token(request):
        return jsonify({'success': False, 'message': '无效的访问令牌'}), 403

    stats = {
        'version': _SERVER_VERSION,
        'config_source': Config.CONFIG_SOURCE,
        'uptime': time.time() - start_time,
        'model': Config.ANTHROPIC_MODEL,
        'cache_enabled': Config.ENABLE_CACHE,
        'cache_size': len(cache) if cache is not None else 0,
        'qa_records_count': len(qa_records),
    }

    return jsonify(stats)


@app.route('/dashboard', methods=['GET'])
def dashboard():
    """仪表盘 - 显示问答记录和系统状态"""
    uptime_seconds = time.time() - start_time
    days = int(uptime_seconds // 86400)
    hours = int((uptime_seconds % 86400) // 3600)
    minutes = int((uptime_seconds % 3600) // 60)
    uptime_str = f"{days}天{hours}小时{minutes}分钟"

    return render_template(
        'dashboard.html',
        version=_SERVER_VERSION,
        config_source=Config.CONFIG_SOURCE,
        cache_enabled=Config.ENABLE_CACHE,
        cache_size=len(cache.cache) if cache is not None else 0,
        model=Config.ANTHROPIC_MODEL,
        uptime=uptime_str,
        records=qa_records,
    )


@app.route('/', methods=['GET'])
def index():
    """首页 - 显示Web界面"""
    return render_template('index.html', version=_SERVER_VERSION)


@app.route('/docs', methods=['GET'])
def docs():
    """API文档页面"""
    doc_path = os.path.join(os.path.dirname(__file__), 'api_docs.md')
    with open(doc_path, 'r', encoding='utf-8') as f:
        content = f.read()

    try:
        import markdown
        html_content = markdown.markdown(content, extensions=['tables'])

        return f"""
        <html>
            <head>
                <title>AI题库服务 - API文档</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                    h1, h2, h3 {{ color: #2c3e50; }}
                    .container {{ max-width: 800px; margin: 0 auto; }}
                    code {{ background: #e0e0e0; padding: 2px 4px; border-radius: 3px; }}
                    pre {{ background: #f4f4f4; padding: 10px; border-radius: 4px; overflow-x: auto; }}
                    table {{ border-collapse: collapse; width: 100%; }}
                    th, td {{ border: 1px solid #ddd; padding: 8px; }}
                    th {{ background-color: #f4f4f4; }}
                </style>
            </head>
            <body>
                <div class="container">
                    {html_content}
                </div>
            </body>
        </html>
        """
    except ImportError:
        return f"""
        <html>
            <head>
                <title>AI题库服务 - API文档</title>
                <style>
                    body {{ font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; }}
                    h1 {{ color: #333; }}
                    .container {{ max-width: 800px; margin: 0 auto; }}
                    pre {{ background: #f4f4f4; padding: 10px; border-radius: 4px; overflow-x: auto; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <h1>AI题库服务 - API文档</h1>
                    <pre>{content}</pre>
                </div>
            </body>
        </html>
        """


if __name__ == '__main__':
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
