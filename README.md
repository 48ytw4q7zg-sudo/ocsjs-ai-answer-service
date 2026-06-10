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

- **AI 驱动**: 通过 ccswitch 代理或直接 API 调用生成智能回答
- **ccswitch 集成**: 自动读取 `~/.claude/settings.json`，无需手动配置密钥
- **OCS 兼容**: 完全兼容 OCS 的 AnswererWrapper 题库接口
- **高性能**: 内存缓存（MD5 哈希键 + TTL 过期 + LRU 淘汰），快速响应
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

如果已安装并运行 ccswitch，服务会自动读取 `~/.claude/settings.json` 中的代理配置，无需手动配置 `.env` 文件。直接启动即可：

```bash
python app.py
```

启动日志会显示 `配置来源: ccswitch`。

**方式二：手动配置 .env**

将 `.env.example` 复制为 `.env` 并填写配置：

```bash
cp .env.example .env
```

编辑 `.env` 文件，填写 API 密钥：

```
ANTHROPIC_API_KEY=your_api_key_here
ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic
ANTHROPIC_MODEL=deepseek-v4-pro
```

### 4. 启动服务

```bash
python app.py
```

服务将默认运行在 `http://localhost:5000`

### 5. 在 OCS 中配置使用

在 OCS 的自定义题库配置中添加如下配置：

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
├── .env                    # 实际环境变量 (gitignore, 不入库)
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

1. `logging.basicConfig()` 初始化全局日志格式（在导入 config 之前，确保 ccswitch 模块日志也能被捕获）
2. `from config import Config` 触发配置加载（详见 config.py 章节）
3. `logging.getLogger().setLevel(Config.LOG_LEVEL)` 根据配置调整日志级别
4. 记录配置来源和模型信息
5. `Flask(__name__)` 创建应用实例
6. `CORS(app)` 启用跨域支持
7. `SimpleCache(Config.CACHE_EXPIRATION)` 初始化缓存
8. 检查 `ANTHROPIC_API_KEY` 是否存在，不存在则抛出 ValueError
9. `anthropic.Anthropic(api_key=..., base_url=...)` 初始化 AI 客户端

**全局状态**:

| 变量 | 类型 | 说明 |
|------|------|------|
| `client` | `anthropic.Anthropic` | Anthropic 兼容 API 客户端 |
| `cache` | `SimpleCache` / `None` | 内存缓存实例（缓存关闭时为 None） |
| `qa_records` | `deque(maxlen=100)` | 问答历史记录队列，自动淘汰最旧记录 |
| `start_time` | `float` | 服务启动时间戳，用于计算 uptime |
| `SYSTEM_PROMPT` | `str` | AI 系统提示词，约定答题格式规范 |
| `MAX_RECORDS` | `int` | 最大记录数 = 100 |

**路由表**:

| 路由 | 方法 | 函数 | 功能 | 访问令牌验证 |
|------|------|------|------|:---:|
| `/` | GET | `index()` | 返回问答测试首页 `index.html` | — |
| `/dashboard` | GET | `dashboard()` | 返回仪表盘页面 `dashboard.html`，计算 uptime 字符串 | — |
| `/docs` | GET | `docs()` | 读取 `api_docs.md` 并用 `markdown` 库渲染为 HTML（未安装则纯文本） | — |
| `/api/search` | GET/POST | `search()` | 核心搜索接口，调用 AI 生成答案 | ✓ |
| `/api/health` | GET | `health_check()` | 健康检查，返回状态/版本/配置来源/缓存状态/模型 | — |
| `/api/cache/clear` | POST | `clear_cache()` | 清除全部缓存 | ✓ |
| `/api/stats` | GET | `get_stats()` | 返回服务统计（版本/uptime/模型/缓存/记录数） | ✓ |

**`search()` 请求处理流程（核心链路）**:

```
客户端请求
  │
  ├─ 1. verify_access_token() — 验证 X-Access-Token 头或 ?token 参数
  │
  ├─ 2. 根据请求方法提取参数:
  │      GET  → request.args.get('title', ''), request.args.get('type', ''), request.args.get('options', '')
  │      POST → Content-Type: application/json → request.get_json()
  │      POST → 其他 Content-Type → request.form (表单数据)
  │
  ├─ 3. 参数校验 — title 为空返回 code:0 + "未提供问题内容"
  │
  ├─ 4. 缓存查询 — cache.get(question, question_type, options)
  │      命中 → 直接返回缓存答案（跳过 AI 调用）
  │
  ├─ 5. parse_question_and_options() — 构建 AI 提示词
  │      (utils.py: 拼接题型提示 + 选项内容)
  │
  ├─ 6. client.messages.create() — 调用 AI API
  │      参数: model, temperature, max_tokens, system=SYSTEM_PROMPT, messages=[{"role":"user","content":prompt}]
  │
  ├─ 7. 提取响应文本 — response.content[0].text.strip()
  │
  ├─ 8. extract_answer() — 后处理答案格式
  │      (utils.py: 多选答案自动转换为 # 分隔格式)
  │
  ├─ 9. cache.set() — 写入缓存
  │
  ├─ 10. qa_records.append() — 记录问答历史
  │
  └─ 11. format_answer_for_ocs() → 返回 JSON {code:1, question:..., answer:...}
```

**`docs()` 渲染逻辑**:

```
读取 api_docs.md
  │
  ├─ try: import markdown → markdown.markdown(content, extensions=['tables'])
  │      返回内嵌 CSS 的完整 HTML 页面
  │
  └─ except ImportError:
         返回 <pre>{content}</pre> 纯文本页面
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
2. load_dotenv(override=True)  — 强制覆盖方式加载 .env 到 os.environ
3. _ccswitch = get_ccswitch_config()  — 调用 ccswitch.py 读取 settings.json
4. class Config:
     if _ccswitch 有效:
         使用 ccswitch 的 api_key / base_url / model
         CONFIG_SOURCE = 'ccswitch'
     else:
         从 os.getenv() 读取 ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL / ANTHROPIC_MODEL
         CONFIG_SOURCE = '.env'
```

**Config 类属性**:

| 属性 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `HOST` | `HOST` | `"0.0.0.0"` | Flask 监听地址 |
| `PORT` | `PORT` | `5000` | 监听端口 |
| `DEBUG` | `DEBUG` | `True` | Flask 调试模式 |
| `ANTHROPIC_API_KEY` | 优先 ccswitch, 回退 `ANTHROPIC_API_KEY` | — | AI API 密钥（启动时必填） |
| `ANTHROPIC_BASE_URL` | 优先 ccswitch, 回退 `ANTHROPIC_BASE_URL` | `"https://api.deepseek.com/anthropic"` | AI API 地址 |
| `ANTHROPIC_MODEL` | 优先 ccswitch, 回退 `ANTHROPIC_MODEL` | `"deepseek-v4-pro"` | 请求的模型名称 |
| `CONFIG_SOURCE` | — | 动态 | 配置来源标识（`"ccswitch"` 或 `".env"`） |
| `LOG_LEVEL` | `LOG_LEVEL` | `"INFO"` | 日志级别 |
| `ACCESS_TOKEN` | `ACCESS_TOKEN` | `None` | 访问令牌（None=不验证） |
| `MAX_TOKENS` | `MAX_TOKENS` | `500` | AI 响应最大 token 数 |
| `TEMPERATURE` | `TEMPERATURE` | `0.7` | AI 生成温度参数 |
| `ENABLE_CACHE` | `ENABLE_CACHE` | `True` | 是否启用缓存 |
| `CACHE_EXPIRATION` | `CACHE_EXPIRATION` | `86400` | 缓存过期时间（秒，默认 24h） |

---

#### 3. `ccswitch.py` — ccswitch 配置读取模块

从 Claude Code 的 `settings.json` 中读取 ccswitch 代理配置，实现 API 密钥动态获取。

**核心常量**:

```python
CCSWITCH_DEFAULT_HOST = "127.0.0.1"
CCSWITCH_DEFAULT_PORT = 15721
```

**函数调用链**:

```
get_ccswitch_config()                      # 主入口
  │
  ├─ _find_settings_path()                 # 查找配置文件
  │     检查 ~/.claude/settings.json
  │     检查 ~/.claude/settings.local.json
  │     返回第一个存在的路径，不存在返回 None
  │
  └─ _is_ccswitch_proxy(base_url)          # 判断是否为 ccswitch 代理
        检查 "127.0.0.1:15721" 或 "localhost:15721" 是否在 base_url 中
```

**`get_ccswitch_config()` 详细流程**:

```
1. 调用 _find_settings_path() 找配置文件
   └─ 未找到 → return None (回退到 .env)

2. 读取 JSON 文件
   └─ JSON 解析/IO 异常 → return None

3. 读取 settings['env'] 字典
   └─ 不是 dict → return None

4. 读取 env['ANTHROPIC_BASE_URL']
   └─ 为空 或 不是 ccswitch 代理地址 → return None

5. 根据 settings['model'] 选择模型:
   'opus'   → 'ANTHROPIC_DEFAULT_OPUS_MODEL_NAME'
   'sonnet' → 'ANTHROPIC_DEFAULT_SONNET_MODEL_NAME'
   'haiku'  → 'ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME'
   其他     → 'ANTHROPIC_DEFAULT_OPUS_MODEL_NAME'

6. 读取对应的模型名称 env[model_key]
   └─ 空值 → 回退 'deepseek-v4-pro'

7. 读取 env['ANTHROPIC_AUTH_TOKEN']
   └─ 空值 → return None

8. 返回 {'api_key': ..., 'base_url': ..., 'model': ...}
```

---

#### 4. `utils.py` — 工具函数模块

包含 3 个纯函数 + 1 个类。

##### `class SimpleCache` — 内存缓存

基于 Python 字典的轻量级缓存，核心特点：

- **MD5 哈希键**: `_generate_key()` 对 `question|type|options` 拼接串做 MD5 哈希，确保键长度恒定
- **TTL 过期**: `get()` 检查 `time.time() - timestamp < expiration`，过期自动删除
- **LRU 淘汰**: `set()` 在超过 `max_size` 时删除时间戳最旧的条目
- **容量限制**: 默认 `max_size=10000`

| 方法 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `__init__` | `expiration_seconds=86400, max_size=10000` | — | 24h 过期，最多 10000 条 |
| `__len__` | — | `int` | 当前缓存条目数 |
| `_generate_key` | `question, question_type, options` | `str` (MD5 hex) | 生成缓存键 |
| `get` | `question, question_type="", options=""` | `str` / `None` | 查询缓存，过期自动删除返回 None |
| `set` | `question, answer, question_type="", options=""` | `None` | 写入缓存，超出容量时淘汰最旧条目 |
| `clear` | — | `None` | 清空全部缓存 |
| `remove_expired` | — | `int` | 批量删除过期条目，返回删除数量 |

##### `format_answer_for_ocs(question, answer)` → `Dict[str, Any]`

将答案包装为 OCS 标准响应格式：`{'code': 1, 'question': question, 'answer': answer}`

##### `parse_question_and_options(question, options, question_type)` → `str`

构建发送给 AI 的完整提示词。拼接逻辑：

```
"问题: {question}\n"
+ 题型提示（从 type_prompts 字典按 question_type 映射）
+ "选项:\n{options}\n"  (仅当 options 非空)
+ "请直接给出答案，不要解释。"
```

`type_prompts` 映射：

| type | 提示文本 |
|------|---------|
| `single` | `"这是一道单选题。"` |
| `multiple` | `"这是一道多选题，答案请用#符号分隔。"` |
| `judgement` | `"这是一道判断题，需要回答：正确/对/true/√ 或者 错误/错/false/×。"` |
| `completion` | `"这是一道填空题。"` |

##### `extract_answer(ai_response, question_type)` → `str`

从 AI 原始响应中提取和格式化答案。仅对多选题做特殊处理：

```
1. 非多选 → 直接返回原始文本

2. 多选处理（3 种模式）:
   模式1: 文本中已包含 '#' → 直接返回
   模式2: 连续选项字母 "ABC" 或 "A B C" → 转换为 "A#B#C"
   模式3: 按行扫描 ≤8 字符的行 → 识别纯字母组合 → 转换为 # 分隔
   无法匹配任何模式 → 返回原始文本
```

---

#### 5. `logger.py` — 日志模块

提供 `Logger` 类和自动初始化的 `app_logger` 实例。

**`class Logger`**:

| 参数 | 说明 |
|------|------|
| `name` | 日志记录器名称 |
| `log_dir` | 日志目录，默认 `"logs"` |

**初始化流程**:

```
1. os.makedirs(log_dir, exist_ok=True)  — 创建日志目录
2. 日志文件名: logs/{name}_{YYYY-MM-DD}.log
3. logging.getLogger(name)  — 获取/创建 logger
4. 检查 handler 是否已存在（幂等性保护）
5. RotatingFileHandler:
     - maxBytes=10MB
     - backupCount=5
     - encoding='utf-8'
6. StreamHandler(sys.stdout)  — 控制台输出
7. 统一格式: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
```

**模块级实例**: `app_logger = Logger("ai_answer_service").get_logger()`

---

#### 6. `test_service.py` — 测试脚本

独立测试脚本，用于验证服务是否正常运行。**提示**: 需要先启动 `app.py` 服务（默认端口 5000），再运行本脚本。

**主流程**:

```
main()
  │
  ├─ test_health()  — GET /api/health
  │     └─ 失败 → sys.exit(1)
  │
  ├─ test_search("中国的首都是哪个城市？", "single", "A. 上海\nB. 北京\nC. 广州\nD. 深圳")
  ├─ test_search("以下哪些是中国的一线城市？", "multiple", "A. 北京\nB. 上海\nC. 广州\nD. 深圳\nE. 成都\nF. 杭州")
  ├─ test_search("地球是太阳系中第三颗行星。", "judgement")
  └─ test_search("《红楼梦》的作者是_______。", "completion")
```

每个 `test_search()` 使用 `requests.get()` 发送 GET 请求到 `/api/search`，验证 `response.json()['code'] == 1`。

可通过 `SERVICE_URL` 环境变量自定义服务地址。

---

### 二、前端模板详解

#### 7. `templates/index.html` — 问答测试首页

**CDN 依赖**: Bootstrap 5.3 CSS + Axios

**页面结构**:

```
导航栏 (.navbar-dark.bg-primary)
  ├─ 品牌: "EduBrain AI"
  ├─ 链接: /dashboard (统计面板)
  └─ 链接: /docs (API文档)

主内容区
  ├─ 标题区: "EduBrain AI — 新一代智能题库服务"
  ├─ 表单卡片 (.card)
  │    ├─ textarea #question — 问题内容
  │    ├─ select #question-type — 单选题/多选题/判断题/填空题
  │    └─ textarea #options — 选项内容（每行一个）
  ├─ 按钮: #search-btn "获取答案"
  ├─ 加载动画: #loading (.spinner-border)
  ├─ 结果卡片: #result — 显示 AI 回答
  └─ OCS 配置示例: <pre> 代码块

页脚: "EduBrain AI - 智能题库系统 v1.3.0"
```

**前端 JS 交互流**:

```
#search-btn click
  │
  ├─ 1. 校验 question 非空 → 否则 alert('请输入问题内容')
  ├─ 2. 显示 #loading / 隐藏 #result
  ├─ 3. axios.get('/api/search', {params: {title, type, options}})
  │
  ├─ 成功:
  │    code===1 → 显示问题+答案
  │    code!==1 → 显示错误信息 msg
  │
  └─ 异常:
       显示 "请求失败: " + error.message
```

---

#### 8. `templates/dashboard.html` — 统计仪表盘

**CDN 依赖**: Bootstrap 5.3 CSS/JS + jQuery 3.7.1 + DataTables 1.13.8 (BS5 + Responsive)

**后端注入变量（Jinja2）**:

| 变量 | 说明 |
|------|------|
| `{{ version }}` | 版本号 "1.3.0" |
| `{{ config_source }}` | 配置来源 "ccswitch" / ".env" |
| `{{ cache_enabled }}` | 缓存启用状态 (bool) |
| `{{ cache_size }}` | 当前缓存条目数 |
| `{{ model }}` | 使用的 AI 模型名 |
| `{{ uptime }}` | 运行时长 "X天X小时X分钟" |
| `{{ records }}` | 问答记录列表 (deque) |

**页面结构**:

```
导航栏 (同 index)

系统信息卡片 (.card)
  ├─ 版本
  ├─ 配置来源
  ├─ 缓存状态
  ├─ 缓存数量
  ├─ 使用模型
  └─ 运行时长

问答记录卡片 (.card)
  ├─ 标题 + "清除缓存" 按钮
  └─ DataTable 表格
        ├─ 时间 (data-order 排序)
        ├─ 问题类型
        ├─ 问题内容 (.text-truncate 截断 + title 悬停)
        ├─ 选项 (.text-truncate)
        ├─ AI答案 (.text-truncate)
        └─ 操作: "详情" 按钮

详情模态框 (.modal#detailModal)
  ├─ 问题 <pre>
  ├─ 选项 <pre>
  └─ 答案 <pre>
```

**前端 JS 交互**:

- `clearCache()`: `fetch('/api/cache/clear', {method:'POST'})` → 成功后 `location.reload()`
- `showDetail(question, options, answer)`: 填充模态框并 `new bootstrap.Modal(...).show()`
- DataTable 配置: 响应式 + 按时间倒序 + 中文语言包 + 每页 10/25/50/100 可选

---

### 三、静态资源详解

#### 9. `static/style.css` — 全局样式

按功能区域组织的自定义样式表：

| 选择器区域 | 说明 |
|-----------|------|
| `.navbar` / `.navbar-brand` | 导航栏阴影 + 粗体品牌名 |
| `.card` / `.card-header` | 卡片阴影 + 无边框 |
| `.table` / `.table-hover` | 表头背景色 + 悬停高亮 |
| `.form-group` / `textarea` | 表单间距 + 文本框最小高度 100px |
| `.btn` | 按钮圆角 4px |
| `.text-truncate` | 文本截断（默认最大 300px, 移动端 150px） |
| `.modal-content` | 无边框 + 深阴影 |
| `.modal pre` | 模态框中 pre 样式：折行 + 浅灰背景 |
| `.footer` | 页脚：浅灰背景 + 上边框 |
| `.spinner` | 自定义旋转加载动画（`animation: spin 1s linear infinite`） |
| `@keyframes spin` | 0→360deg 旋转 |
| `.dataTables_*` | DataTables 搜索框/分页/信息栏微调 |
| `@media (max-width: 768px)` | 移动端适配：缩小内边距/字号/截断宽度 |
| `::-webkit-scrollbar` | 滚动条美化：8px 宽 + 灰色滑块 |

---

### 四、配置与部署文件详解

#### 10. `.env.example` — 环境变量模板

提供 8 个配置项的默认值和注释，复制为 `.env` 后使用：

```
HOST=0.0.0.0          # Flask 监听地址
PORT=5000              # 监听端口
DEBUG=True             # 调试模式
ANTHROPIC_API_KEY=...  # 回退 API 密钥（ccswitch 可用时忽略）
ANTHROPIC_BASE_URL=... # 回退 API 地址
ANTHROPIC_MODEL=...    # 回退模型名
MAX_TOKENS=500         # AI 响应最大 token
TEMPERATURE=0.7        # 生成温度
ENABLE_CACHE=True      # 启用缓存
CACHE_EXPIRATION=86400 # 缓存过期秒数
# ACCESS_TOKEN=...     # 可选的访问令牌
```

#### 11. `requirements.txt` — Python 依赖

| 包 | 最低版本 | 用途 |
|----|---------|------|
| `flask` | ≥2.0.1 | Web 框架（路由/模板/请求处理） |
| `flask-cors` | ≥3.0.10 | 跨域支持 |
| `python-dotenv` | ≥0.19.1 | .env 文件加载 |
| `anthropic` | ≥0.39.0 | Anthropic 兼容 API 客户端（调用 DeepSeek） |
| `gunicorn` | ≥20.1.0 | 生产级 WSGI 服务器 |
| `markdown` | ≥3.3.0 | Markdown → HTML 转换（/docs 页面） |

#### 12. `Dockerfile` — Docker 镜像

基于 `python:3.9-slim`，构建流程：

```
1. WORKDIR /app
2. COPY requirements.txt .
3. apt-get 安装 curl（用于 healthcheck）
4. pip install requirements.txt
5. COPY . .  （全量复制）
6. mkdir -p logs
7. EXPOSE 5000
8. CMD: gunicorn --bind 0.0.0.0:5000 --limit-request-line 16380 app:app
```

`--limit-request-line 16380` 允许较大的 HTTP 请求行，应对长题干 URL 参数。

#### 13. `docker-compose.yml` — Docker Compose

```yaml
services:
  ai-answer-service:
    build: .                     # 从当前目录 Dockerfile 构建
    ports: "5000:5000"
    volumes: ./logs:/app/logs    # 日志持久化
    env_file: .env               # 注入环境变量
    extra_hosts:
      - "host.docker.internal:host-gateway"  # 容器访问宿主机 ccswitch
    restart: unless-stopped
    healthcheck:
      test: curl -f http://localhost:5000/api/health
      interval: 30s / timeout: 10s / retries: 3
```

**关键设计**: `extra_hosts` 配置让容器内可通过 `host.docker.internal` 访问宿主机的 ccswitch 代理（`127.0.0.1:15721`）。

#### 14. `.gitignore` — Git 忽略

```
__pycache__/
```

`.env` 文件已在仓库中但通过 git 管理策略控制（包含在 tracked files 但 `.env.example` 作为模板）。

#### 15. `api_docs.md` — API 文档

Markdown 格式的 API 文档，包含：
- 搜索接口参数表（title/type/options）
- 成功/失败响应示例
- 健康检查/缓存清理/统计信息接口
- OCS 配置示例
- 安全设置说明
- Multi-connect 域名注意事项

被 `app.py` 的 `/docs` 路由读取并渲染为 HTML。

#### 16. `ocs_config_example.json` — OCS 配置示例

JSON 数组，包含一个 OCS AnswererWrapper 配置对象：

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

## API 接口完整参考

### 搜索接口

**URL**: `/api/search`

**方法**: `GET` / `POST`

**认证**: ACCESS_TOKEN（可选，通过 `X-Access-Token` 头或 `?token=` 参数）

**参数**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|:----:|------|
| title | string | 是 | 题目内容 |
| type | string | 否 | single(单选) / multiple(多选) / judgement(判断) / completion(填空) |
| options | string | 否 | 选项文本 |

**成功响应**:

```json
{"code": 1, "question": "问题原文", "answer": "AI生成的答案"}
```

**失败响应**:

```json
{"code": 0, "msg": "错误描述"}
```

### 健康检查

**URL**: `/api/health` | **方法**: `GET` | **认证**: 无

```json
{"status": "ok", "message": "AI题库服务运行正常", "version": "1.3.0", "config_source": "ccswitch", "cache_enabled": true, "model": "deepseek-v4-pro"}
```

### 缓存清理

**URL**: `/api/cache/clear` | **方法**: `POST` | **认证**: ACCESS_TOKEN

```json
{"success": true, "message": "缓存已清除"}
```

### 统计信息

**URL**: `/api/stats` | **方法**: `GET` | **认证**: ACCESS_TOKEN

```json
{"version": "1.3.0", "config_source": "ccswitch", "uptime": 12345.67, "model": "deepseek-v4-pro", "cache_enabled": true, "cache_size": 42, "qa_records_count": 42}
```

---

## 页面路由

| 路由 | 页面 | 功能 |
|------|------|------|
| `/` | 问答测试页 | 输入题目 → 调用 AI → 显示答案 |
| `/dashboard` | 统计仪表盘 | 系统信息 + 问答历史 DataTable + 清除缓存 |
| `/docs` | API 文档 | api_docs.md 渲染为 HTML（需 markdown 库，否则显示纯文本） |

---

## 安全设置

在 `.env` 中设置 `ACCESS_TOKEN`：

```
ACCESS_TOKEN=your_secret_token_here
```

设置后，以下接口需要令牌验证（`/api/health` 和页面路由**不受**令牌保护）：

- `GET/POST /api/search`
- `POST /api/cache/clear`
- `GET /api/stats`

传递方式（二选一）：

1. HTTP 头部: `X-Access-Token: your_secret_token_here`
2. URL 参数: `?token=your_secret_token_here`

验证逻辑位于 `app.py:verify_access_token()` 函数：

```python
def verify_access_token(req):
    if Config.ACCESS_TOKEN:
        token = req.headers.get('X-Access-Token') or req.args.get('token')
        if not token or token != Config.ACCESS_TOKEN:
            return False
    return True
```

---

## Gunicorn 生产部署

```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

Docker 部署（推荐）：

```bash
docker build -t ai-answer-service .
docker run -p 5000:5000 --env-file .env ai-answer-service
```

Docker Compose（最简单）：

```bash
docker-compose up -d
```

---

## 常见问题

### 1. AI 答案准确性

AI 生成的答案可能存在偏差，建议以人工判断为准。

### 2. 多选题答案格式

OCS 期望 `#` 分隔格式（如 `A#B#C`）。服务通过 `utils.py:extract_answer()` 自动转换 3 种常见格式。

### 3. API 请求限制

DeepSeek API 有使用限制和费用，确保账户额度充足。

### 4. Docker 容器访问宿主机 ccswitch

`docker-compose.yml` 已配置 `extra_hosts: host.docker.internal:host-gateway`。如果 ccswitch 监听在 `127.0.0.1:15721`，需确保 `~/.claude/settings.json` 中 `ANTHROPIC_BASE_URL` 为 `http://host.docker.internal:15721/...`。

---

## 许可证

本项目仅供个人学习使用。详见 [LICENSE](./LICENSE) 文件。
