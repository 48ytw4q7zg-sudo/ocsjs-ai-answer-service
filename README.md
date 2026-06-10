# EduBrain AI - 智能题库系统

基于 Anthropic 兼容协议的智能题库服务，专为 [OCS (Online Course Script)](https://github.com/ocsjs/ocsjs) 设计，通过 AI 自动回答题目。实现与 OCS AnswererWrapper 兼容的 API 接口，集成 ccswitch 动态配置，无需手动管理 API 密钥。

**版本**: 1.3.0
**作者**: Lynn

---

## ⚠️ 重要提示

> [!IMPORTANT]
> - 本项目仅供个人学习使用，不保证稳定性，且不提供任何技术支持。
> - 使用者必须在遵循 DeepSeek 的[使用条款](https://platform.deepseek.com/policies)以及**法律法规**的情况下使用，不得用于非法用途。
> - 根据[《生成式人工智能服务管理暂行办法》](http://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm)的要求，请勿对中国地区公众提供一切未经备案的生成式人工智能服务。
> - 使用者应当遵守相关法律法规，承担相应的法律责任。
> - 服务不对 AI 生成内容的准确性做出保证。

---

## 功能特点

- **AI 驱动**: 通过 ccswitch 代理或直连 API 调用生成智能回答
- **ccswitch 集成**: 自动读取 `~/.claude/settings.json` 中的 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL` 等字段，无需手动配置密钥
- **直连 API 支持**: ccswitch 离线时自动回退到 `.env` 配置，支持直连 DeepSeek 等 Anthropic 兼容 API
- **OCS 兼容**: 完全兼容 OCS 的 AnswererWrapper 题库接口
- **高性能缓存**: 内存缓存（MD5 哈希键 + TTL 过期 + LRU 淘汰），快速响应
- **安全可靠**: 支持 ACCESS_TOKEN 双重验证（Header `X-Access-Token` / URL `?token=`）
- **多种题型**: 支持单选(single)、多选(multiple)、判断(judgement)、填空(completion)
- **数据统计**: `/dashboard` 仪表盘实时监控服务状态和问答历史
- **Web UI**: Bootstrap 5 响应式界面，支持移动端
- **日志轮转**: RotatingFileHandler 自动按 10MB 切割，保留 5 个历史文件

---

## 系统要求

- Python 3.7+
- [ccswitch](https://github.com/ccswitch/ccswitch)（推荐，自动管理 API 密钥和模型配置）
- 或手动配置：DeepSeek / Anthropic 兼容 API 密钥

---

## 快速开始

### 1. 克隆代码库

```bash
git clone https://gitee.com/qinxinwei123/ocsjs-ai-answer-service.git
cd ocsjs-ai-answer-service
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置

**方式一（推荐）：使用 ccswitch**

如果已安装并运行 ccswitch，服务会自动读取 `~/.claude/settings.json` 中的配置，无需手动配置 `.env` 文件。直接启动即可：

```bash
python app.py
```

启动日志：
```
配置来源: ccswitch
AI 模型: deepseek-v4-pro, Base URL: https://api.deepseek.com/anthropic
```

**方式二：手动配置 .env**

将 `.env.example` 复制为 `.env` 并填写配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件：

```
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-pro
```

### 4. 启动服务

```bash
python app.py
```

服务默认运行在 `http://localhost:5000`

### 5. 在 OCS 中配置使用

```json
[
  {
    "name": "AI智能题库",
    "url": "http://localhost:5000/api/search",
    "method": "get",
    "type": "GM_xmlhttpRequest",
    "contentType": "json",
    "data": {
      "title": "${title}",
      "type": "${type}",
      "options": "${options}"
    },
    "handler": "return (res)=> res.code === 1 ? [res.question, res.answer] : [res.msg, undefined]"
  }
]
```

---

## 项目结构详解

```
ocsjs-ai-answer-service/
├── app.py                  # 主应用入口 (Flask Web 服务)
├── config.py               # 配置模块 (ccswitch 优先 + .env 回退)
├── ccswitch.py             # ccswitch 配置读取模块
├── utils.py                # 工具函数 (缓存/答案格式化/答案提取)
├── logger.py               # 日志模块 (RotatingFileHandler 轮转)
├── test_service.py         # 服务测试脚本 (4种题型覆盖)
├── requirements.txt        # Python 依赖清单
├── Dockerfile              # Docker 镜像构建文件
├── docker-compose.yml      # Docker Compose 编排文件
├── .env.example            # 环境变量配置模板
├── .gitignore              # Git 忽略规则
├── LICENSE                 # 许可证文件
├── api_docs.md             # API 文档 (Markdown)
├── ocs_config_example.json # OCS 配置示例
├── static/
│   └── style.css           # 全局样式 (导航/卡片/表格/表单/模态框/响应式)
└── templates/
    ├── index.html          # 首页 (问答测试页面)
    └── dashboard.html      # 仪表盘 (系统状态 + 问答历史)
```

---

### 一、核心模块详解

#### 1. `app.py` — 主应用入口

Flask Web 服务主文件，是整个系统的中枢。

**启动流程**:

```
1. logging.basicConfig() 初始化根 logger
   └─ 在导入 config 之前执行，防止 ccswitch/config 等子模块产生 "No handler found" 警告

2. from config import Config
   └─ 触发 config.py 模块加载 → ccswitch 配置读取 → .env 回退

3. from logger import setup_logger
4. logger = setup_logger('ai_answer_service', level=LOG_LEVEL)
   └─ 用 RotatingFileHandler 重新配置日志（控制台 + 文件轮转）

5. Flask(__name__) + CORS(app)
6. SimpleCache(Config.CACHE_EXPIRATION) 初始化缓存
7. anthropic.Anthropic(api_key, base_url) 初始化 AI 客户端
```

**全局状态**:

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `client` | `anthropic.Anthropic` | — | Anthropic 兼容 API 客户端 |
| `cache` | `SimpleCache` / `None` | — | 内存缓存实例（缓存关闭时为 None） |
| `qa_records` | `deque(maxlen=100)` | — | 问答历史记录队列，自动淘汰最旧记录 |
| `start_time` | `float` | `time.time()` | 服务启动时间戳 |
| `SYSTEM_PROMPT` | `str` | 见代码 | AI 系统提示词，定义答题格式规范 |
| `MAX_RECORDS` | `int` | `100` | 最大历史记录数 |

**路由表**:

| 路由 | 方法 | 函数 | 功能 | 令牌验证 |
|------|------|------|------|:---:|
| `/` | GET | `index()` | 返回问答测试首页 `index.html` | — |
| `/dashboard` | GET | `dashboard()` | 返回仪表盘页面（含系统信息 + DataTable 问答历史） | — |
| `/docs` | GET | `docs()` | 读取 `api_docs.md` 并用 `markdown` 库渲染为 HTML | — |
| `/api/search` | GET/POST | `search()` | 核心搜索接口，调用 AI 生成答案 | ✓ |
| `/api/health` | GET | `health_check()` | 健康检查（状态/版本/配置来源/缓存/模型） | — |
| `/api/cache/clear` | POST | `clear_cache()` | 清除全部缓存 | ✓ |
| `/api/stats` | GET | `get_stats()` | 返回服务统计（版本/uptime/模型/缓存/记录数） | ✓ |

**`search()` 请求处理全链路**:

```
客户端请求
  │
  ├─ 1. verify_access_token() 令牌验证
  │
  ├─ 2. 参数提取（按请求方法）
  │      GET  → request.args.get()
  │      POST → Content-Type: application/json → request.get_json()
  │      POST → 其他 Content-Type → request.form
  │
  ├─ 3. 参数校验 → title 为空返回 code:0 + 403
  │
  ├─ 4. 缓存查询 → cache.get(question, type, options)
  │      命中 → 直接返回缓存答案（跳过 AI 调用）
  │
  ├─ 5. parse_question_and_options() 构建提示词
  │      (utils.py: 问题 + 题型提示 + 选项 + 格式指令)
  │
  ├─ 6. client.messages.create() 调用 AI API
  │      {model, temperature, max_tokens, system, messages}
  │
  ├─ 7. 提取文本 → response.content[0].text.strip()
  │
  ├─ 8. extract_answer() 后处理格式
  │      (utils.py: 多选 4 模式检测 + # 标准化)
  │
  ├─ 9. cache.set() 写入缓存
  │
  ├─ 10. qa_records.append() 记录历史
  │
  └─ 11. format_answer_for_ocs() 返回 JSON
         {code:1, question:..., answer:...}
```

**`verify_access_token()` 令牌验证逻辑**:

```python
def verify_access_token(req):
    if Config.ACCESS_TOKEN:                              # 配置了令牌才验证
        token = req.headers.get('X-Access-Token') \      # 优先 HTTP Header
             or req.args.get('token')                    # 回退 URL 参数
        if not token or token != Config.ACCESS_TOKEN:
            return False
    return True
```

**`docs()` Markdown 渲染**:

```
读取 api_docs.md
  │
  ├─ markdown 库可用 → markdown.markdown(content, extensions=['tables'])
  │                    返回内嵌 CSS 的完整 HTML 页面
  │
  └─ markdown 库不可用 → <pre>{content}</pre> 纯文本
```

**`dashboard()` uptime 计算**:

```python
uptime_seconds = time.time() - start_time
days = int(uptime_seconds // 86400)
hours = int((uptime_seconds % 86400) // 3600)
minutes = int((uptime_seconds % 3600) // 60)
uptime_str = f"{days}天{hours}小时{minutes}分钟"
```

**启动入口**:

```python
if __name__ == '__main__':
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
```

---

#### 2. `config.py` — 配置模块

配置加载策略：**ccswitch 优先 → .env 回退**

**加载流程**:

```
1. from dotenv import load_dotenv
2. load_dotenv(override=True)  ← 强制覆盖模式，确保 .env 值覆盖系统环境变量
3. _ccswitch = get_ccswitch_config()  ← 调用 ccswitch.py
4. class Config:
     if _ccswitch 存在且 api_key 非空:
         ANTHROPIC_API_KEY = _ccswitch['api_key']
         ANTHROPIC_BASE_URL = _ccswitch['base_url']
         ANTHROPIC_MODEL     = _ccswitch['model']
         CONFIG_SOURCE       = 'ccswitch'
     else:
         从 os.getenv() 读取 ANTHROPIC_API_KEY/BASE_URL/MODEL
         CONFIG_SOURCE       = '.env'
```

**`Config` 类属性全表**:

| 属性 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `HOST` | `HOST` | `"0.0.0.0"` | Flask 监听地址 |
| `PORT` | `PORT` | `5000` | 监听端口（int） |
| `DEBUG` | `DEBUG` | `True` | Flask 调试模式（bool） |
| `ANTHROPIC_API_KEY` | 优先 ccswitch; 回退 `ANTHROPIC_API_KEY` | `""` | AI API 密钥 |
| `ANTHROPIC_BASE_URL` | 优先 ccswitch; 回退 `ANTHROPIC_BASE_URL` | `"https://api.deepseek.com/anthropic"` | API 地址 |
| `ANTHROPIC_MODEL` | 优先 ccswitch; 回退 `ANTHROPIC_MODEL` | `"deepseek-v4-pro"` | 模型名称 |
| `CONFIG_SOURCE` | — | 动态 | `"ccswitch"` 或 `".env"` |
| `LOG_LEVEL` | `LOG_LEVEL` | `"INFO"` | 日志级别 |
| `ACCESS_TOKEN` | `ACCESS_TOKEN` | `None` | 访问令牌（None=不验证） |
| `MAX_TOKENS` | `MAX_TOKENS` | `500` | AI 响应最大 token 数（int） |
| `TEMPERATURE` | `TEMPERATURE` | `0.7` | AI 生成温度（float） |
| `ENABLE_CACHE` | `ENABLE_CACHE` | `True` | 是否启用缓存（bool） |
| `CACHE_EXPIRATION` | `CACHE_EXPIRATION` | `86400` | 缓存过期秒数（int，默认 24h） |

---

#### 3. `ccswitch.py` — ccswitch 配置读取模块

从 Claude Code 的 `settings.json` 读取 API 配置。**同时支持 ccswitch 本地代理（127.0.0.1:15721）和直连 API（如 api.deepseek.com）两种模式。**

**核心函数**:

```python
_find_settings_path()           # 辅助: 查找 ~/.claude/settings.json 或 settings.local.json
get_ccswitch_config()           # 主入口: 读取并解析配置
_get_model_by_selection()       # 辅助: 按当前选定模型取名称
```

**`get_ccswitch_config()` 完整流程**:

```
1. _find_settings_path()
   └─ 先检查 ~/.claude/settings.json
   └─ 再检查 ~/.claude/settings.local.json
   └─ 均不存在 → return None

2. json.load(f) 读取文件
   └─ JSONDecodeError / IOError → return None

3. 读取 settings['env'] 字典
   └─ 不是 dict 或为空 → return None

4. 读取 env['ANTHROPIC_AUTH_TOKEN'] 和 env['ANTHROPIC_BASE_URL']
   └─ 任一为空 → return None

5. 模型选择（三级优先级）：
   ① env['ANTHROPIC_MODEL']               ← 通用模型名（DeepSeek 场景用这个）
   ② _get_model_by_selection()             ← 按 settings['model'] 选专用名称
      'opus'   → env['ANTHROPIC_DEFAULT_OPUS_MODEL_NAME']
      'sonnet' → env['ANTHROPIC_DEFAULT_SONNET_MODEL_NAME']
      'haiku'  → env['ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME']
   ③ 'deepseek-v4-pro'                     ← 硬回退

6. 识别代理类型（日志用）：
   is_local = '127.0.0.1' in base_url or 'localhost' in base_url
   tag = 'ccswitch代理' if is_local else '直连'

7. 返回 {'api_key': ..., 'base_url': ..., 'model': ...}
```

**用户 ccswitch 配置匹配验证**（基于你提供的 settings.json）：

```
env.ANTHROPIC_AUTH_TOKEN  = "sk-xxx...xxx"                         ✓ 非空
env.ANTHROPIC_BASE_URL    = "https://api.deepseek.com/anthropic"   ✓ 非空（直连模式）
env.ANTHROPIC_MODEL       = "deepseek-v4-pro"                     ✓ 优先命中
→ 返回: {api_key, base_url, model="deepseek-v4-pro"}
```

---

#### 4. `utils.py` — 工具函数模块

`from __future__ import annotations` 确保 Python 3.7+ 兼容。

##### `class SimpleCache` — 内存缓存

基于 Python 字典的轻量级缓存。MD5 哈希键 + TTL 过期 + LRU 淘汰。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `expiration_seconds` | `86400` | 24 小时过期 |
| `max_size` | `10000` | 最大缓存条目 |

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(expiration_seconds, max_size)` | 初始化缓存字典 |
| `__len__` | `() -> int` | 返回当前条目数 |
| `_generate_key` | `(question, type, options) -> str` | MD5(`"q|type|opts"`) 生成固定长度键 |
| `get` | `(question, type="", options="") -> str\|None` | 查询缓存，过期返回 None 并删除 |
| `set` | `(question, answer, type="", options="") -> None` | 写入缓存，超容量时删除最旧条目 |
| `clear` | `() -> None` | 清空全部缓存 |
| `remove_expired` | `() -> int` | 批量删除过期条目，返回删除数量 |

**TTL 过期策略**:

```python
def get(self, question, question_type, options):
    key = MD5(f"{question}|{question_type}|{options}")
    ts, value = self.cache[key]
    if time.time() - ts < self.expiration:  # 未过期
        return value
    del self.cache[key]  # 过期自动删除
    return None
```

**LRU 淘汰策略**:

```python
def set(self, question, answer, question_type, options):
    if len(self.cache) >= self.max_size:
        oldest = min(self.cache, key=lambda k: self.cache[k][0])  # 最小时间戳
        del self.cache[oldest]
    self.cache[key] = (time.time(), answer)
```

##### `format_answer_for_ocs(question, answer)` → `Dict[str, Any]`

包装为 OCS 标准格式：`{'code': 1, 'question': question, 'answer': answer}`。

##### `parse_question_and_options(question, options, question_type)` → `str`

构建 AI 提示词。拼接三段式结构：

```
问题: {question}
{题型提示行 — 从 _TYPE_HINTS 字典映射}
选项:\n{options}        (仅当 options 非空)
请直接给出答案，不要解释。
```

**`_TYPE_HINTS` 映射**:

| type | 提示文本 |
|------|---------|
| `single` | `这是一道单选题。` |
| `multiple` | `这是一道多选题，答案请用#号分隔选项。` |
| `judgement` | `这是一道判断题，需要回答：正确/对/true/√ 或者 错误/错/false/×。` |
| `completion` | `这是一道填空题。` |

##### `extract_answer(ai_response, question_type)` → `str`

AI 答案后处理。**仅多选题做格式转换**。

```
非多选 → 直接返回原始文本

多选处理:
  ├─ text.strip() 为空 → 返回空
  ├─ 包含 '#' → _normalize_hash_separated() 标准化
  └─ 不含 '#' → _detect_letters() 检测选项字母
        ├─ 模式1: 连续字母 "ABC" → "A#B#C"
        ├─ 模式2: 按行扫描 ≤8 字符的行 → 纯字母行 → # 分隔
        ├─ 模式3: 提取所有 A-H 字母 → 去重排序 → # 分隔
        └─ 均不匹配 → 返回原始文本
```

##### `_normalize_hash_separated(text)` → `str`

标准化已有 `#` 分隔符的答案。对每个分段：
- 单字母 → 直接保留大写
- 多字符 → 取首字母（若首字母是 A-H）

##### `_detect_letters(text)` → `Optional[str]`

从文本中检测选项字母。三种正则模式依次尝试。

---

#### 5. `logger.py` — 日志模块

通过 `setup_logger()` 函数创建带轮转的日志记录器。

```python
setup_logger(name: str, log_dir: str = "logs",
             level: int = logging.INFO) -> logging.Logger
```

**内部机制**:

```
1. os.makedirs(log_dir, exist_ok=True)
2. 日志文件: logs/{name}_{YYYY-MM-DD}.log
3. 幂等保护: logger.handlers 已存在 → 直接返回（避免重复添加）
4. RotatingFileHandler: maxBytes=10MB, backupCount=5, encoding='utf-8'
5. StreamHandler(sys.stdout): 控制台同步输出
6. 统一格式: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
```

**调用关系**: `app.py` 第 27-28 行 `from logger import setup_logger; logger = setup_logger(...)`

---

#### 6. `test_service.py` — 测试脚本

独立测试脚本，用于验证服务是否正常运行。需先启动 `app.py`。

**主流程**:

```
main()
  ├─ test_health()  — GET /api/health
  │     └─ 失败 → sys.exit(1)
  │
  ├─ test_search("中国的首都是哪个城市？", "single", "A. 上海\nB. 北京\nC. 广州\nD. 深圳")
  ├─ test_search("以下哪些是中国的一线城市？", "multiple", "A. 北京\n...\nF. 杭州")
  ├─ test_search("地球是太阳系中第三颗行星。", "judgement")
  └─ test_search("《红楼梦》的作者是_______。", "completion")
```

可通过 `SERVICE_URL` 环境变量自定义服务地址（默认 `http://localhost:5000`）。

---

### 二、前端模板详解

#### 7. `templates/index.html` — 问答测试首页

**CDN 依赖**: Bootstrap 5.3 CSS + Axios

**DOM 结构**:

```
导航栏 (.navbar-dark.bg-primary)
  └─ 品牌: "EduBrain AI" + 链接: /dashboard, /docs

主内容区
  ├─ 标题: "EduBrain AI — 新一代智能题库服务，兼容 OCS 题库接口"
  ├─ 表单卡片 (.card.shadow-sm)
  │    ├─ textarea #question   — 问题内容 (3行)
  │    ├─ select #question-type — 未指定/单选/多选/判断/填空
  │    └─ textarea #options    — 选项内容 (每行一个，4行)
  ├─ 按钮 #search-btn (.btn-primary.btn-lg) "获取答案"
  ├─ 加载动画 #loading (display:none) — .spinner-border + "AI正在思考"
  ├─ 结果卡片 #result (display:none)  — #answer-content 显示答案
  └─ OCS 配置示例 <pre> 代码块

页脚: "EduBrain AI - 智能题库系统 v1.3.0"
```

**前端 JS 交互流**:

```
#search-btn click
  ├─ 校验 question 非空 → 否则 alert
  ├─ 显示 #loading / 隐藏 #result
  ├─ axios.get('/api/search', {params: {title, type, options}})
  │
  ├─ 成功:
  │    code===1 → 显示 问题 + 答案
  │    code!==1 → 显示 error 样式 + 错误消息
  │
  └─ 异常 → 显示 error 样式 + error.message
```

---

#### 8. `templates/dashboard.html` — 统计仪表盘

**CDN 依赖**: Bootstrap 5.3 CSS/JS + jQuery 3.7.1 + DataTables 1.13.8 (BS5 + Responsive)

**Jinja2 注入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| `{{ version }}` | str | 版本号 ("1.3.0") |
| `{{ config_source }}` | str | 配置来源 ("ccswitch" / ".env") |
| `{{ cache_enabled }}` | bool | 缓存是否启用 |
| `{{ cache_size }}` | int | 当前缓存条目数 |
| `{{ model }}` | str | AI 模型名 |
| `{{ uptime }}` | str | 运行时长 ("X天X小时X分钟") |
| `{{ records }}` | deque | 问答历史记录 |

**DOM 结构**:

```
导航栏 (同 index)

系统信息卡片 (.card-header.bg-primary)
  ├─ 版本 / 配置来源 / 缓存状态
  ├─ 缓存数量 / 使用模型 / 运行时长

问答记录卡片
  ├─ 标题 + "清除缓存" 按钮 (调用 /api/cache/clear POST)
  └─ DataTable 表格 (#qa-records)
        ├─ 时间 (data-order 排序)
        ├─ 问题类型
        ├─ 问题内容 (.text-truncate + title 悬停提示)
        ├─ 选项 (.text-truncate)
        ├─ AI答案 (.text-truncate)
        └─ 操作 → "详情" 按钮

详情模态框 (.modal#detailModal)
  ├─ 问题 <pre>
  ├─ 选项 <pre>
  └─ 答案 <pre>
```

**前端 JS**:

- `clearCache()`: `fetch POST /api/cache/clear` → `location.reload()`
- `showDetail(q, o, a)`: 填充模态框 → `new bootstrap.Modal().show()`
- DataTable: responsive + 时间倒序 + 中文 + 10/25/50/100 分页

---

### 三、静态资源详解

#### 9. `static/style.css` — 全局样式

| 选择器区域 | 说明 |
|-----------|------|
| `.navbar` / `.navbar-brand` | 导航栏阴影 + 粗体品牌名 |
| `.card` / `.card-header` | 卡片阴影 + 无边框 |
| `.table` / `.table-hover` | 表头灰底 + 悬停高亮 |
| `.form-group` / `textarea` | 表单间距 + 文本框最小高度 100px |
| `.btn` | 圆角 4px |
| `.text-truncate` | 文本截断 (300px/移动端 150px) |
| `.modal-content` | 无边框 + 深阴影 |
| `.modal pre` | pre 自动折行 + 灰底 |
| `.footer` | 灰底 + 上边框 `border-top` |
| `.spinner` | 自定义旋转动画 |
| `@keyframes spin` | 0→360deg |
| `.dataTables_*` | 搜索框/分页/信息栏微调 |
| `@media (max-width:768px)` | 移动端适配 |
| `::-webkit-scrollbar` | 滚动条美化 (8px + 灰色滑块) |

---

### 四、配置与部署文件详解

#### 10. `.env.example` — 环境变量模板

```ini
HOST=0.0.0.0              # Flask 监听地址
PORT=5000                  # 监听端口
DEBUG=True                 # 调试模式

# 回退 API 配置（ccswitch 可用时忽略）
ANTHROPIC_API_KEY=your-api-key-here
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-pro

# 响应参数
MAX_TOKENS=500             # AI 最大输出 token
TEMPERATURE=0.7            # 生成温度 (0-1)

# 缓存设置
ENABLE_CACHE=True          # 启用缓存
CACHE_EXPIRATION=86400     # 过期时间(秒)

# ACCESS_TOKEN=...         # 可选，API 访问令牌
```

#### 11. `requirements.txt` — Python 依赖

| 包 | 最低版本 | 用途 |
|----|---------|------|
| `flask` | ≥2.0.1 | Web 框架 |
| `flask-cors` | ≥3.0.10 | 跨域支持 |
| `python-dotenv` | ≥0.19.1 | .env 加载 |
| `anthropic` | ≥0.39.0 | Anthropic 兼容 API 客户端 |
| `gunicorn` | ≥20.1.0 | 生产 WSGI 服务器 |
| `markdown` | ≥3.3.0 | Markdown→HTML (可选) |

#### 12. `Dockerfile` — Docker 镜像

基于 `python:3.9-slim`，7 步构建：

```
1. FROM python:3.9-slim
2. WORKDIR /app
3. COPY requirements.txt .
4. RUN apt-get 安装 curl + pip install 依赖
5. COPY . .
6. RUN mkdir -p logs
7. EXPOSE 5000
8. CMD: gunicorn --bind 0.0.0.0:5000 --limit-request-line 16380 app:app
```

`--limit-request-line 16380` 允许长题干 URL 参数通过。

#### 13. `docker-compose.yml` — Docker Compose

```yaml
services:
  ai-answer-service:
    build: .
    ports: "5000:5000"
    volumes: ./logs:/app/logs         # 日志持久化
    env_file: .env                    # 环境变量注入
    extra_hosts:
      - "host.docker.internal:host-gateway"  # 容器→宿主机 (访问 ccswitch)
    restart: unless-stopped
    healthcheck:
      test: curl -f http://localhost:5000/api/health
      interval: 30s / timeout: 10s / retries: 3
```

> 如果 ccswitch 监听在 `127.0.0.1:15721`，settings.json 中 `ANTHROPIC_BASE_URL` 需配置为 `http://host.docker.internal:15721/...`。

#### 14. `.gitignore`

```
__pycache__/
```

#### 15. `api_docs.md` — API 文档

Markdown 格式 API 文档，被 `app.py` 的 `/docs` 路由读取并渲染。包含搜索/健康/缓存/统计四个接口的参数表和示例、OCS 配置示例、安全设置说明。

#### 16. `ocs_config_example.json` — OCS 配置示例

```json
[{
  "name": "AI智能题库",
  "homepage": "https://github.com/LynnGuo666/ocsjs-ai-answer-service",
  "url": "http://localhost:5000/api/search",
  "method": "get",
  "contentType": "json",
  "data": {"title": "${title}", "type": "${type}", "options": "${options}"},
  "handler": "return (res)=> res.code === 1 ? [res.question, res.answer] : [res.msg, undefined]"
}]
```

---

## API 接口参考

### 搜索接口

| 属性 | 值 |
|------|-----|
| **URL** | `/api/search` |
| **方法** | `GET` / `POST` |
| **认证** | ACCESS_TOKEN（可选） |

**参数**:

| 参数 | 类型 | 必填 | 说明 |
|------|------|:----:|------|
| title | string | 是 | 题目内容 |
| type | string | 否 | single / multiple / judgement / completion |
| options | string | 否 | 选项文本 |

**成功** `{"code": 1, "question": "...", "answer": "..."}`

**失败** `{"code": 0, "msg": "..."}`

### 健康检查

**GET** `/api/health` · 无需认证

```json
{"status": "ok", "message": "AI题库服务运行正常", "version": "1.3.0",
 "config_source": "ccswitch", "cache_enabled": true, "model": "deepseek-v4-pro"}
```

### 缓存清理

**POST** `/api/cache/clear` · 需 ACCESS_TOKEN

```json
{"success": true, "message": "缓存已清除"}
```

### 统计信息

**GET** `/api/stats` · 需 ACCESS_TOKEN

```json
{"version": "1.3.0", "config_source": "ccswitch", "uptime": 12345.67,
 "model": "deepseek-v4-pro", "cache_enabled": true, "cache_size": 42,
 "qa_records_count": 42}
```

---

## 页面路由

| 路由 | 功能 | 说明 |
|------|------|------|
| `/` | 问答测试 | Bootstrap 5 表单 + Axios 调用 /api/search |
| `/dashboard` | 统计面板 | Jinja2 渲染 + DataTables + 清除缓存按钮 |
| `/docs` | API 文档 | api_docs.md 渲染为 HTML |

---

## 安全设置

在 `.env` 中设置 `ACCESS_TOKEN=your_token` 后：

| 受保护接口 | 令牌传递方式 |
|-----------|-------------|
| `/api/search` | `X-Access-Token: <token>` 头 或 `?token=<token>` 参数 |
| `/api/cache/clear` | 同上 |
| `/api/stats` | 同上 |

> `/`、`/dashboard`、`/docs`、`/api/health` 不受令牌保护。

---

## 生产部署

```bash
# Gunicorn
gunicorn -w 4 -b 0.0.0.0:5000 app:app

# Docker
docker build -t ai-answer-service .
docker run -p 5000:5000 --env-file .env ai-answer-service

# Docker Compose
docker-compose up -d
```

---

## 常见问题

### AI 答案准确性

AI 生成答案可能有偏差，以人工判断为准。

### 多选答案格式

OCS 期望 `#` 分隔格式。`utils.py:extract_answer()` 通过 4 种模式自动转换。

### Docker 容器访问宿主机 ccswitch

`docker-compose.yml` 配置了 `extra_hosts: host.docker.internal:host-gateway`。

### Gitee 推送 SSL 错误

如果遇到 `schannel: failed to receive handshake`，可以临时禁用 schannel：

```bash
git -c http.sslBackend=openssl push origin main
```

---

## 技术栈

- **后端**: Flask + Gunicorn
- **AI**: Anthropic 兼容协议 (DeepSeek / ccswitch 代理)
- **前端**: Bootstrap 5 + DataTables + Axios
- **缓存**: 内存缓存 (MD5 + TTL + LRU)
- **部署**: Docker + Docker Compose

---

## 许可证

本项目仅供个人学习使用。详见 [LICENSE](./LICENSE) 文件。
