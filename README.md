# EduBrain AI - 智能题库系统

基于 Anthropic 兼容协议的智能题库服务，专为 [OCS (Online Course Script)](https://github.com/ocsjs/ocsjs) 设计，通过 AI 自动回答题目。实现与 OCS AnswererWrapper 兼容的 API 接口，集成 ccswitch 动态配置，无需手动管理 API 密钥。

**版本**: 2026.6.10.1739
**作者**: QXW

---

## 重要提示

> [!IMPORTANT]
> - 本项目仅供个人学习使用，不保证稳定性，且不提供任何技术支持。
> - 使用者必须在遵循 DeepSeek 的[使用条款](https://platform.deepseek.com/policies)以及**法律法规**的情况下使用，不得用于非法用途。
> - 根据[《生成式人工智能服务管理暂行办法》](http://www.cac.gov.cn/2023-07/13/c_1690898327029107.htm)的要求，请勿对中国地区公众提供一切未经备案的生成式人工智能服务。
> - 使用者应当遵守相关法律法规，承担相应的法律责任。
> - 服务不对 AI 生成内容的准确性做出保证。

---

## 功能特点

- **AI 驱动**: 通过 Anthropic 兼容协议调用 DeepSeek API 生成智能回答
- **ccswitch 集成**: 自动读取 `~/.claude/settings.json` 中的 `ANTHROPIC_AUTH_TOKEN`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL` 等字段，无需手动配置密钥
- **模型名自动净化** (v2.1.0): 自动去除 settings.json 中模型名的 `[1M]`/`[200K]` 等后缀，确保 DeepSeek API 兼容
- **运行时配置重载** (v2.1.0): `/api/config/reload` 端点支持不停机切换 API 配置，ccswitch 配置变更即时生效
- **直连 API 支持**: ccswitch 离线时自动回退到 `.env` 配置，支持直连 DeepSeek 等 Anthropic 兼容 API
- **OCS 兼容**: 完全兼容 OCS 的 AnswererWrapper 题库接口
- **高性能缓存**: 线程安全的内存缓存（MD5 哈希键 + TTL 过期 + LRU 淘汰）
- **安全可靠**: 支持 ACCESS_TOKEN 双重验证（Header `X-Access-Token` / URL `?token=`）
- **多种题型**: 支持单选(single)、多选(multiple)、判断(judgement)、填空(completion)
- **错误处理**: API 超时、连接失败、HTTP 错误分级处理与友好提示
- **数据统计**: `/dashboard` 仪表盘实时监控服务状态、ccswitch 配置详情和问答历史
- **Web UI**: Bootstrap 5 响应式界面，支持移动端，XSS 防护
- **日志轮转**: RotatingFileHandler 自动按 10MB 切割，保留 5 个历史文件，Windows 控制台 UTF-8 兼容
- **增强提示词** (v2.2.0): 题目+选项+题型指令强制合并为一条完整提示词，AI 基于实际选项作答
- **防混淆策略** (v2.2.0): 提示词明确告知选项顺序可能被打乱，要求 AI 比对选项内容而非凭记忆
- **空答案自动重试** (v2.2.0): AI 返回空文本时自动降温(T=0.3)重试一次
- **全题型答案清洗** (v2.2.0): 自动去除"答案："等前缀、选项字母前缀(B./A.)、尾标点；判断题中英文标准化
- **Docker 部署**: 提供 Dockerfile + docker-compose.yml，支持容器化运行

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
AI 模型: deepseek-v4-pro, Base URL: http://127.0.0.1:15721
```

> **v2.1.0 新特性**: 如果 settings.json 中模型名为 `deepseek-v4-pro[1M]`，服务会自动净化为 `deepseek-v4-pro`，并记录净化日志。

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
├── app.py                  # 主应用入口 (Flask Web 服务，8 路由)
├── config.py               # 配置模块 (ccswitch 优先 + .env 回退，16 项配置 + 运行时重载)
├── ccswitch.py             # ccswitch 配置读取模块 (5 函数 + 5 级模型回退 + 模型名净化)
├── utils.py                # 工具函数 (线程安全缓存 / 答案格式化 / 答案提取)
├── logger.py               # 日志模块 (RotatingFileHandler 轮转 + Windows UTF-8 修复)
├── test_service.py         # 服务测试脚本 (7 项测试覆盖)
├── requirements.txt        # Python 依赖清单 (6 包)
├── Dockerfile              # Docker 镜像构建文件 (8 层)
├── docker-compose.yml      # Docker Compose 编排文件 (含健康检查)
├── .env.example            # 环境变量配置模板 (15 项)
├── .env                    # 实际环境变量（gitignore 排除）
├── .gitignore              # Git 忽略规则 (42 条)
├── LICENSE                 # GPL v3 许可证
├── api_docs.md             # API 文档 (Markdown)
├── ocs_config_example.json # OCS 配置示例
├── static/
│   └── style.css           # 全局样式 (17 区域，含滚动条美化 / 移动端适配)
└── templates/
    ├── index.html          # 首页 (Bootstrap 5 + Axios + XSS 防护)
    └── dashboard.html      # 仪表盘 (Bootstrap 5 + DataTables + jQuery + ccswitch 详情)
```

---

### 一、核心模块详解

#### 1. `ccswitch.py` — ccswitch 配置读取模块

从 Claude Code 的 `settings.json` 读取 API 配置。**同时支持 ccswitch 本地代理（127.0.0.1:15721）和直连 API（如 api.deepseek.com）两种模式。**

**核心函数**:

| 函数 | 签名 | 说明 |
|------|------|------|
| `_find_settings_path()` | `() -> Optional[Path]` | 查找 `~/.claude/settings.json` 或 `settings.local.json` |
| `get_ccswitch_config()` | `(settings_path=None) -> Optional[Dict]` | 主入口: 读取并解析配置，自动净化模型名 |
| `_resolve_model()` | `(settings, env) -> str` | 5 级模型回退解析 |
| `_sanitize_model_name()` | `(model: str) -> str` | **v2.1.0 新增**: 去除 `[1M]`/`[200K]` 等后缀 |
| `extract_all_env()` | `(settings) -> Dict[str, str]` | **v2.1.0 新增**: 提取 settings.json 中所有 env 变量 |
| `reload_ccswitch_config()` | `() -> Optional[Dict]` | **v2.1.0 新增**: 运行时强制重新读取配置 |

**`get_ccswitch_config()` 完整流程**:

```
1. _find_settings_path()
   └─ 先检查 ~/.claude/settings.json
   └─ 再检查 ~/.claude/settings.local.json
   └─ 均不存在 → return None

2. settings_path.read_text(encoding="utf-8") 读取文件
   └─ JSONDecodeError / OSError → return None

3. 读取 settings['env'] 字典
   └─ 不是 dict 或为空 → return None

4. 读取 env['ANTHROPIC_AUTH_TOKEN'] 和 env['ANTHROPIC_BASE_URL']
   └─ 任一为空 → return None

5. _resolve_model() 模型选择（五级回退）：
   ① env['ANTHROPIC_MODEL']                    ← 通用模型名 (DeepSeek 场景用这个)
   ② env['ANTHROPIC_DEFAULT_{OPUS|SONNET|HAIKU}_MODEL_NAME']
                                                ← 按 settings.model 选专用名称
   ③ env['ANTHROPIC_DEFAULT_{OPUS|SONNET|HAIKU}_MODEL']
                                                ← 模型容器名回退
   ④ ANTHROPIC_REASONING_MODEL / 遍历所有后备键 ← 遍历兜底
   ⑤ 'deepseek-v4-pro'                          ← 硬回退

6. _sanitize_model_name() 净化模型名（v2.1.0 新增）：
   正则 r"\[\d+K?M?\]" 去除方括号后缀
   'deepseek-v4-pro[1M]' → 'deepseek-v4-pro'
   'claude-opus-4-7[200K]' → 'claude-opus-4-7'
   无后缀 → 原样返回

7. 识别代理类型（日志用）：
   is_local = '127.0.0.1' in base_url or 'localhost' in base_url
   tag = 'ccswitch代理' if is_local else '直连'

8. 返回 {
     'api_key': ...,
     'base_url': ...,
     'model': ...,        # ← 净化后的模型名
     'raw_model': ...,    # ← v2.1.0: 原始模型名（未净化）
     'is_proxy': ...,     # ← v2.1.0: 是否代理模式
     'source_file': ...,  # ← v2.1.0: 配置文件路径
   }
```

**`_sanitize_model_name()` 净化规则** (v2.1.0 新增):

| 输入 | 输出 | 说明 |
|------|------|------|
| `deepseek-v4-pro[1M]` | `deepseek-v4-pro` | 去除 1M 上下文后缀 |
| `claude-opus-4-7[200K]` | `claude-opus-4-7` | 去除 200K 上下文后缀 |
| `deepseek-v4-pro` | `deepseek-v4-pro` | 无后缀，原样返回 |
| `claude-sonnet-4-6[128K]` | `claude-sonnet-4-6` | 去除 128K 上下文后缀 |

**`_resolve_model()` 五级回退详解**:

| 级别 | 配置键 | 说明 |
|------|--------|------|
| 1 | `ANTHROPIC_MODEL` | 通用模型名，DeepSeek 直连模式优先使用 |
| 2 | `ANTHROPIC_DEFAULT_{OPUS/SONNET/HAIKU}_MODEL_NAME` | 按当前 `settings.model` 值选择对应显示名 |
| 3 | `ANTHROPIC_DEFAULT_{OPUS/SONNET/HAIKU}_MODEL` | 模型容器名回退 |
| 4 | `ANTHROPIC_REASONING_MODEL` / 遍历所有后备键 | 全量遍历兜底 |
| 5 | `"deepseek-v4-pro"` | 硬编码最终回退值 |

**`extract_all_env()` 提取的 14 个键**:

```
ANTHROPIC_AUTH_TOKEN, ANTHROPIC_BASE_URL, ANTHROPIC_MODEL,
ANTHROPIC_DEFAULT_HAIKU_MODEL, ANTHROPIC_DEFAULT_OPUS_MODEL,
ANTHROPIC_DEFAULT_SONNET_MODEL, ANTHROPIC_REASONING_MODEL,
ANTHROPIC_DEFAULT_OPUS_MODEL_NAME, ANTHROPIC_DEFAULT_SONNET_MODEL_NAME,
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC,
CLAUDE_CODE_DISABLE_NONSTREAMING_FALLBACK,
CLAUDE_CODE_EFFORT_LEVEL, ENABLE_TOOL_SEARCH,
CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
```

这些键值对应仪表盘的 "ccswitch 完整环境变量" 可折叠面板。

**`reload_ccswitch_config()` 运行时重载** (v2.1.0 新增):

```
1. 调用 get_ccswitch_config() 强制重新读取文件
2. 额外解析 settings.json → extract_all_env() 获取完整 env
3. 返回包含 extra_env 字段的完整字典
4. 供 config.reload_config() 和 /api/config/reload 端点使用
```

**用户 ccswitch 配置匹配验证** (基于实际 settings.json):

```
env.ANTHROPIC_AUTH_TOKEN  = "sk-xxx..."                              ✓ 非空
env.ANTHROPIC_BASE_URL    = "https://api.deepseek.com/anthropic"    ✓ 非空 (直连模式)
env.ANTHROPIC_MODEL       = "deepseek-v4-pro"                       ✓ 第1级命中
→ 返回: {api_key, base_url, model="deepseek-v4-pro"}
```

**调用关系**: 
- `config.py` 启动时: `from ccswitch import get_ccswitch_config` → `get_ccswitch_config()`
- `config.py` 重载时: `from ccswitch import reload_ccswitch_config` → `reload_ccswitch_config()`
- `app.py` 健康检查: 通过 `Config.CCSWITCH_*` 属性读取

---

#### 2. `config.py` — 配置模块

配置加载策略：**ccswitch 优先 → .env 回退，支持运行时重载**。

**加载流程**:

```
1. from dotenv import load_dotenv
2. load_dotenv(override=True)  ← 强制覆盖模式，确保 .env 值覆盖系统环境变量
3. _ccswitch = get_ccswitch_config()  ← 调用 ccswitch.py（自动净化模型名）
4. _config_loaded_at = time.time()    ← v2.1.0: 记录加载时间戳
5. class Config:
     if _ccswitch 存在且 api_key 非空:
         ANTHROPIC_API_KEY = _ccswitch['api_key']
         ANTHROPIC_BASE_URL = _ccswitch['base_url']
         ANTHROPIC_MODEL     = _ccswitch['model']       ← 已净化
         CONFIG_SOURCE       = 'ccswitch'
         CCSWITCH_RAW_MODEL  = _ccswitch.get('raw_model')   ← v2.1.0
         CCSWITCH_IS_PROXY   = _ccswitch.get('is_proxy')    ← v2.1.0
         EXTRA_ENV           = _ccswitch.get('extra_env', {})  ← v2.1.0
     else:
         从 os.getenv() 读取
         CONFIG_SOURCE       = '.env'
```

**`reload_config()` 运行时重载** (v2.1.0 新增):

```python
def reload_config() -> bool:
    # 调用 ccswitch.reload_ccswitch_config()
    # 成功 → 更新 Config 类属性（API_KEY, BASE_URL, MODEL, RAW_MODEL, IS_PROXY, EXTRA_ENV）
    # 失败 → 回退到 .env
    # 返回 True 表示从 ccswitch 加载成功，False 表示回退到 .env
```

**`Config` 类属性全表**:

| 属性 | 环境变量 | 类型 | 默认值 | 说明 |
|------|---------|------|--------|------|
| `HOST` | `HOST` | str | `"0.0.0.0"` | Flask 监听地址 |
| `PORT` | `PORT` | int | `5000` | 监听端口 |
| `DEBUG` | `DEBUG` | bool | `True` | Flask 调试模式 |
| `ANTHROPIC_API_KEY` | ccswitch 优先; 回退 `ANTHROPIC_API_KEY` | str | `""` | AI API 密钥 |
| `ANTHROPIC_BASE_URL` | ccswitch 优先; 回退 `ANTHROPIC_BASE_URL` | str | `"https://api.deepseek.com/anthropic"` | API 地址 |
| `ANTHROPIC_MODEL` | ccswitch 优先; 回退 `ANTHROPIC_MODEL` | str | `"deepseek-v4-pro"` | 模型名称（已净化） |
| `CONFIG_SOURCE` | — | str | 动态 | `"ccswitch"` 或 `".env"` |
| `CCSWITCH_RAW_MODEL` | — | str | `""` | **v2.1.0**: ccswitch 原始模型名（净化前） |
| `CCSWITCH_IS_PROXY` | — | bool | `False` | **v2.1.0**: 是否通过 ccswitch 本地代理 |
| `EXTRA_ENV` | — | dict | `{}` | **v2.1.0**: settings.json env 中所有 14 项变量 |
| `API_TIMEOUT` | `API_TIMEOUT` | float | `30.0` | API 请求超时秒数 |
| `API_MAX_RETRIES` | `API_MAX_RETRIES` | int | `2` | API 自动重试次数 |
| `LOG_LEVEL` | `LOG_LEVEL` | str | `"INFO"` | 日志级别 |
| `ACCESS_TOKEN` | `ACCESS_TOKEN` | str\|None | `None` | 访问令牌（None=不验证） |
| `MAX_TOKENS` | `MAX_TOKENS` | int | `500` | AI 响应最大 token 数 |
| `TEMPERATURE` | `TEMPERATURE` | float | `0.7` | AI 生成温度 (0-1) |
| `ENABLE_CACHE` | `ENABLE_CACHE` | bool | `True` | 是否启用缓存 |
| `CACHE_EXPIRATION` | `CACHE_EXPIRATION` | int | `86400` | 缓存过期秒数（默认 24h） |
| `MAX_QUESTION_LENGTH` | `MAX_QUESTION_LENGTH` | int | `2000` | 问题最大字符数 |
| `CONFIG_LOADED_AT` | — | float | 启动时间 | **v2.1.0**: 配置最后加载时间戳 |

---

#### 3. `app.py` — 主应用入口 (Flask Web 服务)

Flask Web 服务主文件，是整个系统的中枢。

**启动流程**:

```
1. logging.basicConfig() 初始化根 logger
   └─ 在导入 config 之前执行，防止 ccswitch/config 等子模块产生 "No handler found" 警告

2. from config import Config, reload_config
   └─ 触发 config.py 模块加载 → ccswitch 配置读取（含模型名净化）→ .env 回退

3. from logger import setup_logger
4. logger = setup_logger('ai_answer_service', level=LOG_LEVEL)
   └─ 用 RotatingFileHandler 重新配置日志（控制台 UTF-8 + 文件轮转）

5. 启动日志: 配置来源 + 模型 + Base URL + 净化信息（如适用）
6. Flask(__name__) + CORS(app)
7. SimpleCache(Config.CACHE_EXPIRATION) 初始化缓存
8. anthropic.Anthropic(api_key, base_url, timeout, max_retries) 初始化 AI 客户端
9. build_ai_client() 函数定义（供运行时重载使用）
```

**全局状态**:

| 变量 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `client` | `anthropic.Anthropic` | — | Anthropic 兼容 API 客户端（含超时/重试，重载时重建） |
| `cache` | `SimpleCache` / `None` | — | 内存缓存实例（缓存关闭时为 None） |
| `qa_records` | `deque(maxlen=100)` | — | 问答历史记录队列，自动淘汰最旧记录 |
| `start_time` | `float` | `time.time()` | 服务启动时间戳 |
| `SYSTEM_PROMPT` | `str` | 见代码 | AI 系统提示词，定义答题格式规范 |
| `MAX_RECORDS` | `int` | `100` | 最大历史记录数 |
| `_SERVER_VERSION` | `str` | `"2.2.0"` | 服务版本号常量 |
| `build_ai_client()` | `() -> Anthropic` | — | **v2.1.0 新增**: 用当前配置重建客户端 |
| `_call_ai()` | `(prompt, max_tokens=300) -> str\|None` | — | **v2.2.0 新增**: 调用 AI API，空文本自动重试+降温

**路由表**:

| 路由 | 方法 | 函数 | 功能 | 令牌验证 |
|------|------|------|------|:---:|
| `/` | GET | `index()` | 返回问答测试首页 `index.html`（传递 version 变量） | — |
| `/dashboard` | GET | `dashboard()` | 返回仪表盘页面（含 ccswitch 详情 + 环境变量面板） | — |
| `/docs` | GET | `docs()` | 读取 `api_docs.md` 并用 `markdown` 库渲染为 HTML | — |
| `/api/search` | GET/POST | `search()` | 核心搜索接口，调用 AI 生成答案 | ✓ |
| `/api/health` | GET | `health_check()` | 健康检查（含 ccswitch 净化信息 + config_keys） | — |
| `/api/config/reload` | POST | `config_reload()` | **v2.1.0 新增**: 运行时重载 ccswitch 配置 | ✓ |
| `/api/cache/clear` | POST | `clear_cache()` | 清除全部缓存，返回清除条目数量 | ✓ |
| `/api/stats` | GET | `get_stats()` | 返回服务统计（含 ccswitch 原始模型名） | ✓ |

**`search()` 请求处理全链路**:

```
客户端请求
  │
  ├─ 1. verify_access_token() 令牌验证 (Header / URL 参数)
  │
  ├─ 2. 参数提取（按请求方法）
  │      GET  → request.args.get()
  │      POST → Content-Type: application/json → request.get_json(silent=True)
  │      POST → 其他 Content-Type → request.form
  │
  ├─ 3. 参数校验
  │      title 为空 → code:0 + 错误消息
  │      title 长度 > MAX_QUESTION_LENGTH → code:0 + 400
  │
  ├─ 4. 缓存查询 → cache.get(question, type, options)
  │      命中 → 直接返回缓存答案（跳过 AI 调用）
  │
  ├─ 5. parse_question_and_options() 构建提示词
  │      (v2.2.0 增强: 题型标签+题干+选项+_build_instructions 合并)
  │
  ├─ 6. _call_ai() 调用 AI API (v2.2.0 新增)
  │      正常调用 → 空文本 → 降温(temperature=0.3)重试 → 仍空 → 返回 None
  │      {model, temperature, max_tokens, system, messages}
  │      自动重试 (max_retries=2)，超时 (timeout=30s)
  │      model 已自动净化（v2.1.0）
  │
  ├─ 7. 提取文本 → response.content[0].text.strip()
  │      空响应 → _call_ai 自动重试 (v2.2.0)
  │
  ├─ 8. extract_answer() 后处理格式 (v2.2.0 增强)
  │      去答案前缀 + 去尾标点 + 单选去选项字母 + 判断标准化 + 多选 # 分隔
  │
  ├─ 9. cache.set() 写入缓存
  │
  ├─ 10. qa_records.append() 记录历史
  │      时间戳使用 timezone.utc
  │
  └─ 11. format_answer_for_ocs() 返回 JSON
         {code:1, question:..., answer:...}
```

**错误处理分级**:

| 异常类型 | HTTP 状态码 | 返回消息 |
|----------|:------:|------|
| `anthropic.APIStatusError` | 503 | AI服务暂时不可用 (HTTP {status}) |
| `anthropic.APITimeoutError` | 504 | AI服务响应超时，请重试 |
| `anthropic.APIConnectionError` | 502 | 无法连接到AI服务 |
| 其他 `Exception` | 500 | 服务内部错误 |

**`health_check()` 响应详解** (v2.1.0 增强):

```json
{
  "status": "ok",
  "message": "AI题库服务运行正常",
  "version": "2.1.0",
  "config_source": "ccswitch",
  "cache_enabled": true,
  "cache_size": 42,
  "model": "deepseek-v4-pro",
  "base_url": "https://api.deepseek.com/anthropic",
  "uptime_seconds": 12345.67,
  "ccswitch": {
    "raw_model": "deepseek-v4-pro[1M]",
    "is_proxy": false,
    "model_sanitized": true
  },
  "config_keys": ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", ...]
}
```

**ccswitch 子对象字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `raw_model` | string | settings.json 中的原始模型名（可能含 `[1M]` 后缀） |
| `is_proxy` | bool | 是否通过 ccswitch 本地代理连接（127.0.0.1:15721） |
| `model_sanitized` | bool | 模型名是否经过净化（raw_model != model） |

**`config_reload()` 配置重载** (v2.1.0 新增):

```
POST /api/config/reload
  ├─ 1. verify_access_token() 令牌验证
  ├─ 2. reload_config() 重新读取 settings.json
  ├─ 3. 成功 → build_ai_client() 重建全局 client
  │          返回 {success:true, model, base_url, raw_model, config_source}
  └─ 4. 失败 → 回退到 .env
              返回 {success:true, message, config_source:".env"}
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

**`dashboard()` 仪表盘** (v2.1.0 增强):

```python
# 构建 ccswitch_info 字典传递给模板
ccswitch_info = {
    'raw_model': Config.CCSWITCH_RAW_MODEL,         # 原始模型名
    'sanitized_model': Config.ANTHROPIC_MODEL,      # 净化后模型名
    'is_proxy': Config.CCSWITCH_IS_PROXY,           # 是否代理模式
    'base_url': Config.ANTHROPIC_BASE_URL,          # API 地址
    'extra_env': Config.EXTRA_ENV,                  # 完整 14 项 env 字典
}
```

仪表盘新增：
- 配置来源 badge（ccswitch=绿色，.env=灰色）
- ccswitch 原始模型名 + 已净化标签
- 连接模式（代理/直连）
- ccswitch 完整环境变量可折叠面板（14 项）
- 「重载配置」按钮

**启动入口**:

```python
if __name__ == '__main__':
    app.run(host=Config.HOST, port=Config.PORT, debug=Config.DEBUG)
```

---

#### 4. `utils.py` — 工具函数模块

`from __future__ import annotations` 确保 Python 3.7+ 兼容。

##### `class SimpleCache` — 线程安全内存缓存

基于 Python 字典的轻量级缓存。MD5 哈希键 + TTL 过期 + LRU 淘汰 + **线程安全锁**。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `expiration_seconds` | `86400` | 24 小时过期 |
| `max_size` | `10000` | 最大缓存条目 |

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__` | `(expiration_seconds, max_size)` | 初始化缓存字典 + `threading.Lock()` |
| `__len__` | `() -> int` | 返回当前条目数（线程安全） |
| `_generate_key` | `(question, type, options) -> str` | MD5(`"q|type|opts"`) 生成固定长度键 |
| `get` | `(question, type="", options="") -> str\|None` | 查询缓存，过期返回 None 并删除；命中时更新时间戳（LRU 提升） |
| `set` | `(question, answer, type="", options="") -> None` | 写入缓存，超容量时 LRU 淘汰最旧条目 |
| `clear` | `() -> int` | 清空全部缓存，返回清除数量（线程安全） |
| `remove_expired` | `() -> int` | 批量删除过期条目，返回删除数量（线程安全） |
| `_evict_one` | `() -> None` | 内部 LRU 淘汰：删除时间戳最小条目 |

**TTL 过期策略 + LRU 提升**:

```python
def get(self, question, question_type, options):
    key = MD5(f"{question}|{question_type}|{options}")
    ts, value = self.cache[key]
    if time.time() - ts < self.expiration:  # 未过期
        self.cache[key] = (time.time(), value)  # LRU: 更新时间戳
        return value
    del self.cache[key]  # 过期自动删除
    return None
```

**LRU 淘汰策略**:

```python
def _evict_one(self):
    oldest = min(self.cache, key=lambda k: self.cache[k][0])  # 最小时间戳
    del self.cache[oldest]
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
        ├─ 模式3: 提取所有 A-H 字母 → 去重按 A-H 顺序排列 → # 分隔
        └─ 均不匹配 → 返回原始文本
```

##### `_normalize_hash_separated(text)` → `str`

标准化已有 `#` 分隔符的答案。对每个分段：
- 单字母 → 直接保留大写
- 多字符 → 取首字母（若首字母是 A-H）
- 空分段 → 跳过

##### `_detect_letters(text)` → `Optional[str]`

从文本中检测选项字母。三种正则模式依次尝试。增加中文逗号 `，` 处理和空字符串早期退出。

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
   └─ v2.1.0: Windows 平台自动修复控制台 UTF-8 编码
6. 统一格式: '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
```

**Windows UTF-8 修复** (v2.1.0 新增):

```python
if sys.platform == 'win32':
    try:
        ch.setStream(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))
    except Exception:
        pass
```

**调用关系**: `app.py` 第 27-28 行 `from logger import setup_logger; logger = setup_logger(...)`

---

#### 6. `test_service.py` — 测试脚本

独立测试脚本，用于验证服务是否正常运行。需先启动 `app.py`。

**主流程** (v2.1.0 增强):

```
main()
  ├─ test_health()       — GET /api/health (验证 ccswitch/raw_model/model_sanitized/config_keys)
  │     └─ 失败 → sys.exit(1)
  │
  ├─ test_config_reload() — POST /api/config/reload (v2.1.0 新增)
  ├─ test_stats()         — GET /api/stats (验证 base_url/ccswitch_raw_model)
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
  └─ OCS 配置示例 #ocs-config <pre> 代码块 (自动替换为当前服务地址)

页脚: "EduBrain AI - 智能题库系统 v{{ version }}" (Jinja2 模板变量)
```

**前端 JS 交互流**:

```
#search-btn click
  ├─ 校验 question 非空 → 否则 alert
  ├─ 显示 #loading / 隐藏 #result
  ├─ axios.get('/api/search', {params: {title, type, options}})
  │   └─ 空 type/options 传 undefined (不添加到 URL)
  │
  ├─ 成功:
  │    code===1 → 显示 问题 + 答案 (escapeHtml XSS 防护)
  │    code!==1 → 显示红色边框 + error 样式 + 错误消息
  │
  └─ 异常 → 显示红色边框 + error.message (含 response.data.msg 回退)

页面加载时:
  └─ IIFE: 替换 OCS 配置中 localhost:5000 为当前服务地址
```

**XSS 防护**:
```javascript
function escapeHtml(text) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(text));
    return div.innerHTML;
}
```

**OCS 配置 URL 自动更新**:
- 使用 IIFE 自动执行，不再依赖可能不存在的 window.load 事件
- 通过 `#ocs-config` ID 精确定位 pre 元素内的 `<code>` 标签
- 动态替换 `http://localhost:5000` 为当前浏览器实际地址

---

#### 8. `templates/dashboard.html` — 统计仪表盘

**CDN 依赖**: Bootstrap 5.3 CSS/JS + jQuery 3.7.1 + DataTables 1.13.8 (BS5 + Responsive)

**Jinja2 注入变量**:

| 变量 | 类型 | 说明 |
|------|------|------|
| `{{ version }}` | str | 版本号 ("2.1.0") |
| `{{ config_source }}` | str | 配置来源 ("ccswitch" / ".env")，渲染为 badge |
| `{{ cache_enabled }}` | bool | 缓存是否启用 |
| `{{ cache_size }}` | int | 当前缓存条目数 |
| `{{ model }}` | str | AI 模型名（已净化），渲染为 `<code>` |
| `{{ uptime }}` | str | 运行时长 ("X天X小时X分钟") |
| `{{ records }}` | deque | 问答历史记录 |
| `{{ ccswitch_info }}` | dict/None | **v2.1.0 新增**: ccswitch 详情 |

**ccswitch_info 子字段** (v2.1.0):

| 字段 | 说明 |
|------|------|
| `raw_model` | 原始模型名（可能含 `[1M]` 后缀） |
| `sanitized_model` | 净化后模型名 |
| `is_proxy` | 是否代理模式 |
| `base_url` | API 地址 |
| `extra_env` | 完整 env 字典（14 项） |

**DOM 结构**:

```
导航栏 (同 index)

系统信息卡片 (.card-header.bg-primary)
  左栏:
    ├─ 版本 / 配置来源 (badge 样式)
    ├─ 缓存状态 / 缓存数量
  右栏:
    ├─ 使用模型 (code 样式)
    ├─ 运行时长
    ├─ CCSwitch 原始模型 (code + 已净化 badge)
    └─ 连接模式 (代理/直连)
  v2.1.0: ccswitch 完整环境变量可折叠面板 (14 项 key-value 表)

问答记录卡片
  ├─ 标题 + "重载配置" 按钮 (v2.1.0) + "清除缓存" 按钮
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

**前端 JS** (v2.1.0 增强):

- `reloadConfig()`: **v2.1.0 新增** — `fetch POST /api/config/reload` → 显示结果 → `location.reload()`
- `clearCache()`: `fetch POST /api/cache/clear` → `location.reload()`
- `showDetail(q, o, a)`: 填充模态框 → `new bootstrap.Modal().show()`
- DataTable: responsive + 时间倒序 + 中文 + 10/25/50/100 分页

---

### 三、静态资源详解

#### 9. `static/style.css` — 全局样式

| 选择器区域 | 样式说明 |
|-----------|------|
| `body` | Arial 字体，1.6 行高，#333 文字色，#f8f9fa 背景色 |
| `.navbar` / `.navbar-brand` | 导航栏阴影 `0 2px 4px` + 粗体品牌名 |
| `.card` / `.card-header` | 卡片阴影 `0 1px 3px` + 无边框 |
| `.table` / `.table-hover` | 表头灰底 fw-600 + 悬停蓝色高亮 |
| `.form-group` / `textarea` | 表单间距 1rem + 文本框最小高度 100px |
| `.btn` | 圆角 4px |
| `.text-truncate` | 文本截断 (300px/移动端 150px) |
| `.modal-content` | 无边框 + 0.5rem 1rem 深阴影 |
| `.modal pre` | pre 自动折行 + 灰底 1rem 内边距 |
| `.footer` | 灰底 + 上边框 `border-top` + 1.5rem 内边距 |
| `.spinner` | 自定义 36px 旋转圆环 (蓝色左边) |
| `@keyframes spin` | 0→360deg 持续旋转动画 |
| `.dataTables_*` | 搜索框/分页/信息栏微调 |
| `@media (max-width:768px)` | 移动端适配：缩小 padding/字体/按钮 |
| `::-webkit-scrollbar` | 滚动条美化 (8px + 灰色滑块 + 悬停深灰) |

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

# AI 客户端参数
API_TIMEOUT=30.0           # API 请求超时(秒)
API_MAX_RETRIES=2          # 自动重试次数

# 响应参数
MAX_TOKENS=500             # AI 最大输出 token
TEMPERATURE=0.7            # 生成温度 (0-1)

# 缓存设置
ENABLE_CACHE=True          # 启用缓存
CACHE_EXPIRATION=86400     # 过期时间(秒)

# 输入限制
MAX_QUESTION_LENGTH=2000   # 问题最大字符数

# Access Token 配置 (可选，设置后 API 需要令牌验证)
# ACCESS_TOKEN=your_access_token_here

# 日志级别 (DEBUG/INFO/WARNING/ERROR/CRITICAL)
LOG_LEVEL=INFO
```

#### 11. `requirements.txt` — Python 依赖

| 包 | 最低版本 | 用途 |
|----|---------|------|
| `flask` | ≥2.0.1 | Web 框架 |
| `flask-cors` | ≥3.0.10 | 跨域支持 |
| `python-dotenv` | ≥0.19.1 | .env 加载 |
| `anthropic` | ≥0.39.0 | Anthropic 兼容 API 客户端 (含超时/重试机制) |
| `gunicorn` | ≥20.1.0 | 生产 WSGI 服务器 |
| `markdown` | ≥3.3.0 | Markdown→HTML (可选，/docs 路由美化) |

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

#### 14. `.gitignore` — Git 忽略规则

```
# Python
__pycache__/        *.py[cod]       *$py.class
*.so                *.egg-info/     dist/       build/
.eggs/              *.egg

# Virtual environments
.venv/              venv/           env/        ENV/

# IDE
.idea/              .vscode/        *.swp       *.swo       *~

# OS
.DS_Store           Thumbs.db

# Logs
logs/               *.log

# Environment & secrets
.env                !.env.example

# Docker
.docker/

# Test
.pytest_cache/      .coverage       htmlcov/
```

#### 15. `api_docs.md` — API 文档

Markdown 格式 API 文档，被 `app.py` 的 `/docs` 路由读取并渲染（支持 tables 扩展）。v2.1.0 新增：配置重载接口、ccswitch 模型名净化说明、ccswitch 完整字段说明。

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
| title | string | 是 | 题目内容（最大 2000 字符） |
| type | string | 否 | single / multiple / judgement / completion |
| options | string | 否 | 选项文本 |

**成功** `{"code": 1, "question": "...", "answer": "..."}`

**失败** `{"code": 0, "msg": "..."}`

**错误码**:

| HTTP 状态 | 说明 |
|-----------|------|
| 400 | 请求参数错误（空问题、过长问题、无效 JSON） |
| 403 | 令牌验证失败 |
| 500 | 服务内部错误 |
| 502 | 无法连接到 AI 服务 |
| 503 | AI 服务返回错误 |
| 504 | AI 服务响应超时 |

### 健康检查

**GET** `/api/health` · 无需认证

```json
{"status": "ok", "message": "AI题库服务运行正常", "version": "2.1.0",
 "config_source": "ccswitch", "model": "deepseek-v4-pro",
 "base_url": "https://api.deepseek.com/anthropic",
 "ccswitch": {"raw_model": "deepseek-v4-pro[1M]", "is_proxy": false, "model_sanitized": true}}
```

### 配置重载 (v2.1.0 新增)

**POST** `/api/config/reload` · 需 ACCESS_TOKEN

```json
{"success": true, "message": "配置已从 ccswitch 重新加载",
 "config_source": "ccswitch", "model": "deepseek-v4-pro",
 "base_url": "https://api.deepseek.com/anthropic", "raw_model": "deepseek-v4-pro[1M]"}
```

### 缓存清理

**POST** `/api/cache/clear` · 需 ACCESS_TOKEN

```json
{"success": true, "message": "缓存已清除 (42条)", "count": 42}
```

### 统计信息

**GET** `/api/stats` · 需 ACCESS_TOKEN

```json
{"version": "2.1.0", "config_source": "ccswitch", "uptime": 12345.67,
 "model": "deepseek-v4-pro", "base_url": "https://api.deepseek.com/anthropic",
 "cache_enabled": true, "cache_size": 42, "qa_records_count": 42,
 "ccswitch_raw_model": "deepseek-v4-pro[1M]", "ccswitch_is_proxy": false}
```

---

## 页面路由

| 路由 | 功能 | 说明 |
|------|------|------|
| `/` | 问答测试 | Bootstrap 5 表单 + Axios 调用 `/api/search` + XSS 防护 |
| `/dashboard` | 统计面板 | Jinja2 渲染 + DataTables + ccswitch 详情面板 + 重载/清除按钮 |
| `/docs` | API 文档 | `api_docs.md` 渲染为 HTML |

---

## 安全设置

在 `.env` 中设置 `ACCESS_TOKEN=your_token` 后：

| 受保护接口 | 令牌传递方式 |
|-----------|-------------|
| `/api/search` | `X-Access-Token: <token>` 头 或 `?token=<token>` 参数 |
| `/api/cache/clear` | 同上 |
| `/api/stats` | 同上 |
| `/api/config/reload` (v2.1.0) | 同上 |

> `/`、`/dashboard`、`/docs`、`/api/health` 不受令牌保护。

---

## ccswitch 模型名净化 (v2.1.0 新增)

### 问题背景

ccswitch settings.json 中的模型名可能包含上下文长度后缀，例如：
- `deepseek-v4-pro[1M]` — 1M token 上下文窗口
- `claude-opus-4-7[200K]` — 200K token 上下文窗口

DeepSeek API 不识别带方括号后缀的模型名，直接使用会导致 API 400 错误。

### 自动净化机制

`ccswitch.py` 的 `_sanitize_model_name()` 函数在配置加载时自动执行：

```python
import re
def _sanitize_model_name(model: str) -> str:
    return re.sub(r"\[\d+K?M?\]", "", model).strip()
```

**净化示例**:

| 输入 | 输出 | 触发条件 |
|------|------|---------|
| `deepseek-v4-pro[1M]` | `deepseek-v4-pro` | 含 `[1M]` 后缀 |
| `claude-opus-4-7[200K]` | `claude-opus-4-7` | 含 `[200K]` 后缀 |
| `claude-sonnet-4-6[128K]` | `claude-sonnet-4-6` | 含 `[128K]` 后缀 |
| `deepseek-v4-pro` | `deepseek-v4-pro` | 无后缀，原样返回 |

### 净化验证

健康检查接口返回净化状态：
```json
{
  "ccswitch": {
    "raw_model": "deepseek-v4-pro[1M]",
    "model_sanitized": true
  }
}
```

启动日志记录净化过程：
```
模型名已净化: 'deepseek-v4-pro[1M]' → 'deepseek-v4-pro'
```

---

## 配置重载工作流 (v2.1.0 新增)

```
1. 用户在 ccswitch 中切换 API / 模型
       ↓
2. ccswitch 自动更新 settings.json
       ↓
3. 浏览器访问 /dashboard → 点击「重载配置」
    或 POST /api/config/reload
       ↓
4. reload_config() 重新读取 settings.json
     ├─ _sanitize_model_name() 自动净化
     └─ 更新 Config 类所有属性
       ↓
5. build_ai_client() 用新配置重建 Anthropic 客户端
       ↓
6. 后续 /api/search 请求使用新配置
```

无需重启服务，零停机切换。

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

## 版本变更

### v2.2.0 (2026-06-10) — 提示词深度增强 + 全题型答案清洗
- **新增**: 增强提示词构建 (`parse_question_and_options` + `_build_instructions`)
  - 题目+选项+题型指令强制合并，AI 始终看到完整上下文
  - 明确告知 AI 选项顺序可能被打乱，必须基于实际选项内容判断
  - 分别针对有选项/无选项、不同题型生成精确指令
- **新增**: 空答案自动重试 (`_call_ai`)
  - 第 1 次失败后降温(temperature=0.3)再试一次
  - 统一异常捕获（APIStatusError/APITimeoutError/APIConnectionError）
- **新增**: 全题型答案清洗 (`extract_answer`)
  - 自动去除「答案：」「答案是」「Answer:」等前缀
  - 自动去除尾部标点（。！；，）
  - 单选：去除「B. 北京」→「北京」的选项字母前缀
  - 判断：正确/对/true/√/yes→「正确」，错误/错/false/×/no→「错误」
  - 多选：逗号/空格分隔的答案自动转 # 格式
- **新增**: 详细日志（API 提示词、答案内容、是否有选项）
- **修复**: `str | None` 类型注解改为 Python 3.7+ 兼容写法
- **修复**: SYSTEM_PROMPT 与 _build_instructions 指令一致性对齐
- **Q-CR 三轮审查**: R-07 类型注解/R-10 单选字母前缀/R-13 指令矛盾 全部修复

### v2.1.0 (2026-06-10) — ccswitch 深度集成优化
- **新增**: 模型名自动净化 (`_sanitize_model_name()`) — 去除 `[1M]`/`[200K]` 等后缀
- **新增**: 运行时配置重载 (`/api/config/reload` 端点 + `reload_config()`)
- **新增**: 完整 ccswitch env 提取 (`extract_all_env()` — 14 个键)
- **新增**: 仪表盘 ccswitch 详情面板（原始模型/连接模式/完整 env 表）
- **新增**: `build_ai_client()` 函数 — 配置重载时重建客户端
- **新增**: 健康检查返回 `ccswitch` 子对象（raw_model/is_proxy/model_sanitized/config_keys）
- **新增**: 统计接口返回 `base_url`/`ccswitch_raw_model`/`ccswitch_is_proxy`
- **新增**: `test_service.py` 增加配置重载测试
- **改进**: `ccswitch.py` 返回更多元数据（raw_model/is_proxy/source_file）
- **改进**: `config.py` 新增 6 个属性（CCSWITCH_RAW_MODEL/IS_PROXY/EXTRA_ENV/CONFIG_LOADED_AT）
- **改进**: `logger.py` Windows 控制台 UTF-8 编码自动修复
- **改进**: `dashboard.html` 更好的 UI 布局 + 配置来源 badge 样式
- **修复**: 模型名包含 `[1M]` 等上下文后缀导致 DeepSeek API 400 错误
- **文档**: README 全面重写，覆盖每个文件的每个函数/类/路由/属性

### v2.0.0 (2026-06-10)
- **新增**: API 超时/重试配置 (`API_TIMEOUT`, `API_MAX_RETRIES`)
- **新增**: 输入验证（问题最大长度限制 `MAX_QUESTION_LENGTH`）
- **新增**: 错误处理分级（502/503/504 + 友好提示）
- **新增**: 线程安全缓存 (`threading.Lock`)
- **新增**: SimpleCache LRU 提升策略（访问命中更新时间戳）
- **新增**: 前端 XSS 防护 (`escapeHtml`)
- **新增**: `ccswitch.py` 5 级模型名回退
- **修复**: `index.html` 中 `updateOcsConfig` 引用不存在元素的问题
- **修复**: `LICENSE` 文件重复内容问题
- **改进**: `.gitignore` 从 2 条扩展到 42 条
- **改进**: `pathlib.Path` 替代 `os.path`，utf-8 显式编码
- **改进**: 缓存清除返回清除条数
- **改进**: 时区使用 UTC (`datetime.now(timezone.utc)`)
- **改进**: `utils.py` 答案提取增加中文逗号处理和 empty string guard

---

## 常见问题

### AI 答案准确性

AI 生成答案可能有偏差，以人工判断为准。

### 多选答案格式

OCS 期望 `#` 分隔格式。`utils.py:extract_answer()` 通过 4 种模式自动转换：
1. 直接 `#` 分隔检测
2. 连续字母 "ABC" 模式
3. 逐行扫描纯字母行
4. 全文本 A-H 字母提取

### Docker 容器访问宿主机 ccswitch

`docker-compose.yml` 配置了 `extra_hosts: host.docker.internal:host-gateway`。

### API 超时

默认超时 30 秒，可通过 `.env` 中 `API_TIMEOUT` 调整。连接失败自动重试 2 次（`API_MAX_RETRIES`）。

### ccswitch 模型名含后缀 (v2.1.0)

v2.1.0 自动净化，无需手动处理。健康检查接口可验证净化状态。

### 如何确认当前使用的是 ccswitch 还是 .env 配置？

访问 `/api/health`，查看 `config_source` 字段：
- `"ccswitch"` — 正在使用 `~/.claude/settings.json` 中的配置
- `".env"` — ccswitch 不可用，回退到 `.env` 文件

### 切换 API 后需要重启服务吗？ (v2.1.0)

不需要。POST `/api/config/reload` 或点击仪表盘「重载配置」即可即时生效。

### Gitee 推送 SSL 错误

如果遇到 `schannel: failed to receive handshake`，可以临时禁用 schannel：

```bash
git -c http.sslBackend=openssl push origin main
```

---

## 技术栈

- **后端**: Flask + Gunicorn
- **AI**: Anthropic 兼容协议 (DeepSeek / ccswitch 代理)
- **前端**: Bootstrap 5 + DataTables + Axios + jQuery
- **缓存**: 线程安全内存缓存 (MD5 + TTL + LRU)
- **配置**: ccswitch 实时读取 + 模型名净化 + 运行时重载
- **部署**: Docker + Docker Compose

---

## 许可证

本项目仅供个人学习使用。详见 [LICENSE](./LICENSE) 文件。
