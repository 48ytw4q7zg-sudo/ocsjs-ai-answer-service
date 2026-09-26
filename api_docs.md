# AI题库服务API文档 v2026.9

## 概述

AI题库服务是一个基于 Anthropic 兼容协议（也支持 OpenAI Chat / Responses 协议）的智能题库服务，专为 [OCS (Online Course Script)](https://github.com/ocsjs/ocsjs) 设计，实现与 OCS AnswererWrapper 兼容的 API 接口，并集成 ccswitch 动态配置。

**使用范围**：仅用于用户自有学习辅助，不鼓励、不支持任何考试作弊或违反课程平台规则的用法；答案由第三方模型生成，可能出错，请自行核对；模型调用费用由使用者承担。

**核心特性**:
- 自动读取 `~/.claude/settings.json` 中的 ccswitch 配置（`CCSWITCH_ENABLED=false` 可关闭；便携版从不读取）
- 模型名自动净化（去除 `[1M]`、`[200K]` 等上下文长度后缀）
- 运行时配置重载（无需重启服务；`settings.json` 正在写入时保留当前配置）
- 5 级模型名回退策略
- 机器可读契约：`GET /openapi.json`（OpenAPI 3.0）

## 认证与访问控制

| 场景 | 行为 |
|------|------|
| 设置了 `ACCESS_TOKEN` | 受保护接口必须携带有效令牌，或持有同源浏览器会话 cookie |
| 未设置 `ACCESS_TOKEN`（默认） | **只允许本机直连调用**：来源为 127.0.0.1 / ::1、Host 为 localhost / 127.0.0.1 / [::1]，且没有 `X-Forwarded-For`、`Forwarded` 等代理头；其它网站用图片/iframe/表单跳转触发的请求（`Sec-Fetch-Site` 跨站且 `Sec-Fetch-Dest` 不是 `empty`）返回 403 |
| 未设置令牌且 `ALLOW_REMOTE_WITHOUT_TOKEN=true` | 任何可达客户端都能调用（高风险，仅限可信网络） |

经反向代理或内网穿透隧道（nginx、frp、ngrok、cloudflared 等）对外提供服务时必须设置 `ACCESS_TOKEN`。未设置令牌时，其它网页仍可能用 `fetch` 让浏览器发起答题请求（读不到结果，但会消耗额度），长期运行建议始终设置令牌。

令牌传递方式（按优先级）：

1. **`X-Access-Token: <token>` 请求头（推荐）**
2. `Authorization: Bearer <token>`
3. 兼容旧版：`?token=` / `?access_token=` 查询参数、表单字段或 JSON 字段 `token`（会进入代理日志/浏览器历史，不推荐）

浏览器：问答页通过 `POST /api/session` 用令牌换取 HttpOnly、`SameSite=Strict` 的会话 cookie（1 小时）；带 cookie 的写操作必须同时带 `Origin` 或 `Sec-Fetch-Site` 同源证据。
`/dashboard?token=<token>` 首次访问会建立会话并 **303 跳转到不带令牌的 `/dashboard`**，令牌不再停留在地址栏；浏览器历史/自动补全仍可能记下首次输入的网址，推荐从首页输入令牌后进入仪表盘。会话过期后仪表盘返回 403 并提示重新输入令牌。

所有响应都带：`X-Request-ID`（可由客户端传入 8–64 位字母、数字或 `._-` 作为追踪号，不合规时由服务生成）、`Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`；`/api/*` 与 `/dashboard` 另带 `Cache-Control: no-store`。

## 接口详情

### 1. 搜索接口

**URL**: `/api/search`　**方法**: `GET` 或 `POST`（JSON、`application/*+json` 或表单）　**认证**: 见上文

**参数**（同义字段按列出顺序取第一个非空值；响应头 `X-Question-Field` 回显实际采用的题目字段名）:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| title / question / q / content / text | string | 是 | 题目内容（默认最大 2000 字符，`MAX_QUESTION_LENGTH`） |
| type / questionType / question_type / qtype / category / kind | string/number | 否 | `single`/`multiple`/`judgement`/`completion`/`short-answer`，或 `1`–`5`；无法识别的题型按通用题目处理，响应 `type` 为 `null` |
| options / choices / answers / answerOptions / option / opts | string/array/object | 否 | 字符串、字符串数组、对象数组（如 `{label,text}`）或键值对象（如 `{A:"上海"}`）；服务只统一换行、去除空行与首尾空格，不改动 HTML 标记和实体（`<p>`、`&lt;` 这类字面选项原样保留）。默认最多 64 个选项（按 `A.`/`B.` 标号计数，长选项折行不重复计；无标号时按行计）、8000 字符（`MAX_OPTIONS` / `MAX_OPTIONS_LENGTH`） |

请求体默认上限 256 KB（`MAX_REQUEST_BYTES`），超出返回 413。

**成功响应** (HTTP 200):

```json
{
  "code": 1,
  "question": "问题内容",
  "answer": "AI生成的答案",
  "type": "single",
  "cached": false,
  "model": "deepseek-v4-pro",
  "prompt_version": "2026.09.26",
  "request_id": "3f9c0a1b2c4d5e6f"
}
```

命中缓存时 `cached: true`，并附 `cache_age_seconds`（距首次写入的秒数）。OCS 只读取 `code/question/answer/msg`，额外字段不影响兼容。

**失败响应**:

```json
{
  "code": 0,
  "msg": "错误信息",
  "error_code": "rate_limited",
  "request_id": "3f9c0a1b2c4d5e6f"
}
```

**状态码与 error_code**:

| HTTP | code | error_code | 说明 |
|------|------|-----------|------|
| 200 | 1 | — | 成功 |
| 200 | 0 | `uncertain_answer` | 模型表示无法确定答案（不写缓存，OCS 会换用其它题库） |
| 400 | 0 | `invalid_json` / `invalid_question` / `missing_question` / `question_too_long` / `options_too_large` | 请求参数错误 |
| 403 | 0 | `invalid_token` | 令牌无效；未设置令牌时来自非本机地址、Host 不是本机名、经代理转发或被其它网站嵌入触发 |
| 413 | 0 | `payload_too_large` | 请求体过大 |
| 429 | 0 | `rate_limited` | 超过每分钟 AI 调用上限（默认 60，缓存命中不计）；`Retry-After` 头与 `retry_after` 字段给出等待秒数 |
| 500 | 0 | `internal_error` | 服务内部错误 |
| 502 | 0 | `upstream_unreachable` / `upstream_invalid_response` | 无法连接到 AI 服务；或上游返回了无法解析的内容（多半是接口地址或协议选错） |
| 503 | 0 | `runtime_unavailable` / `no_answer` / `incomplete_response` / `upstream_auth` / `upstream_rate_limited` / `upstream_error` | AI 运行时未就绪、无有效答案、回答被截断、上游鉴权失败、上游限流或其它上游错误 |
| 504 | 0 | `upstream_timeout` | AI 服务响应超时 |

上游返回 400/401/402/403/404/413/422（请求被拒、鉴权或额度问题）、429、超时、连接失败或无法解析的响应时直接失败，不再换提示词重试；其中 429、超时和连接失败已由 SDK 按 `API_MAX_RETRIES` 自动重试过。空答案或上游 5xx 才会用保留全部选项的简化提示词再试一次。

### 2. 健康检查接口（存活探针）

**URL**: `/api/health`　**方法**: `GET`

**认证**: 无令牌也可访问；未通过认证时只返回最小状态（`details: "protected"`），通过认证（或本机访问且未设置令牌）时返回详细配置。

```json
{
  "status": "ok",
  "message": "AI题库服务运行正常",
  "version": "2026.6.10.1739",
  "runtime_ready": true,
  "runtime_error": null,
  "cache_enabled": true,
  "cache_size": 42,
  "uptime_seconds": 12345.67,
  "config_source": "ccswitch",
  "model": "deepseek-v4-pro",
  "base_url": "https://api.deepseek.com/anthropic",
  "access_protection": "token",
  "ccswitch": {"raw_model": "deepseek-v4-pro[1M]", "is_proxy": false, "model_sanitized": true, "config_keys": ["..."]},
  "config_keys": ["ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL"]
}
```

`access_protection`：`token`（已设令牌）/ `loopback-only`（未设令牌，仅本机）/ `open`（未设令牌且允许远程）。

### 3. 就绪接口（就绪探针）

**URL**: `/api/ready`　**方法**: `GET`　**认证**: 无

运行时可用返回 200 `{"ready": true}`，否则 503 `{"ready": false}`。容器编排可用 `python healthcheck.py --ready` 做就绪检查；`python healthcheck.py`（不带参数）仍是存活检查，未配置密钥时不会触发重启循环。

### 4. 配置重载接口

**URL**: `/api/config/reload`　**方法**: `POST`　**认证**: 需要（拒绝跨站请求，结果写入审计日志）

运行时重新读取 ccswitch `settings.json`（不可用时回退 `.env`），重建 AI 客户端与缓存。`settings.json` 暂不可读（例如 cc-switch 正在写入），或上次来自 ccswitch 而这次文件暂时不存在（正在替换文件）时，会稍后重读一次；仍不可读则返回 500（`error_code: reload_failed`）并保留原配置与可用运行时。

```json
{
  "success": true,
  "message": "配置已从 ccswitch 重新加载",
  "config_source": "ccswitch",
  "model": "deepseek-v4-pro",
  "base_url": "https://api.deepseek.com/anthropic",
  "runtime_ready": true,
  "ccswitch": {"raw_model": "deepseek-v4-pro[1M]", "model_sanitized": true}
}
```

### 5. 缓存清理接口

**URL**: `/api/cache/clear`　**方法**: `POST`　**认证**: 需要（拒绝跨站请求，写审计日志）

```json
{"success": true, "message": "缓存已清除 (42条)", "count": 42}
```

未启用缓存时返回 409 `{"success": false, "message": "缓存未启用", "error_code": "cache_disabled"}`。

### 6. 统计信息接口

**URL**: `/api/stats`　**方法**: `GET`　**认证**: 需要

```json
{
  "version": "2026.6.10.1739",
  "config_source": "ccswitch",
  "uptime": 1234.5,
  "runtime_ready": true,
  "model": "deepseek-v4-pro",
  "cache_enabled": true,
  "cache_size": 42,
  "cache": {"size": 42, "max_size": 10000, "hits": 30, "misses": 12, "evictions": 0, "hit_rate": 0.7143},
  "qa_records_count": 12,
  "access_protection": "loopback-only",
  "rate_limit_per_minute": 60,
  "prompt_version": "2026.09.26",
  "metrics": {
    "search_requests": 42, "search_success": 40, "search_cached": 30,
    "failures": {"rate_limited": 1, "uncertain_answer": 1}, "failure_rate": 0.0476,
    "ai_calls": 13, "ai_retries": 1, "retry_rate": 0.0769,
    "ai_failures": {"empty": 1}, "extraction_paths": {"single_option": 10},
    "qps_1m": 0.35, "latency_ms": {"p50": 12.1, "p95": 2300.5, "max": 5100.0, "samples": 42}
  },
  "config_keys": []
}
```

### 7. OpenAPI 契约

**URL**: `/openapi.json`　**方法**: `GET`　**认证**: 无

返回 OpenAPI 3.0 文档；测试用例会逐一核对其路径/方法与实际路由、错误码枚举与代码一致。

## 页面路由

| 路由 | 功能 | 认证 | 说明 |
|------|------|:----:|------|
| `/` | 问答测试 | — | 令牌通过 `X-Access-Token` 请求头发送（非 ASCII 令牌回退到请求体） |
| `/dashboard` | 统计面板 | 需要 | `?token=` 会被换成会话 cookie 并跳转；DataTables + ccswitch 详情 + 重载/清除按钮 |
| `/docs` | API 文档 | — | `api_docs.md` 渲染为 HTML |
| `/openapi.json` | OpenAPI 契约 | — | 机器可读接口定义 |

## OCS配置示例

在 OCS 的自定义题库配置中添加（令牌放在 `headers`，不出现在请求网址里；未设置令牌时删除 `headers`）：

```json
[
  {
    "name": "AI智能题库",
    "homepage": "https://github.com/LynnGuo666/ocsjs-ai-answer-service",
    "url": "http://localhost:5000/api/search",
    "method": "get",
    "contentType": "json",
    "headers": {
      "X-Access-Token": "your_access_token"
    },
    "data": {
      "title": "${title}",
      "type": "${type}",
      "options": "${options}"
    },
    "handler": "return (res)=> res.code === 1 ? [res.question, res.answer] : [res.msg, undefined]"
  }
]
```

旧写法 `"data": {..., "token": "your_access_token"}` 仍兼容，但令牌会出现在请求网址中。

## 运行参数速查

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `ACCESS_TOKEN` | 无 | 访问令牌；局域网/Docker 部署必须设置 |
| `ALLOW_REMOTE_WITHOUT_TOKEN` | `false` | 无令牌时是否允许非本机调用（高风险） |
| `RATE_LIMIT_PER_MINUTE` | `60` | 每客户端每分钟 AI 调用上限，0 表示不限 |
| `MAX_TOKENS` / `SHORT_ANSWER_MAX_TOKENS` | `500` / `1024` | 输出上限；简答题至少取后者 |
| `TEMPERATURE` / `OBJECTIVE_TEMPERATURE_CAP` | `0.7` / `0.3` | 简答题用前者；客观题不高于后者 |
| `API_TIMEOUT` / `API_MAX_RETRIES` | `30` / `2` | 单次上游超时与 SDK 重试次数 |
| `MAX_QUESTION_LENGTH` / `MAX_OPTIONS` / `MAX_OPTIONS_LENGTH` / `MAX_REQUEST_BYTES` | `2000` / `64` / `8000` / `262144` | 输入上限 |
| `CCSWITCH_ENABLED` | `true` | 服务模式是否读取 ccswitch 配置 |

**超时预算**：最坏耗时 = `API_TIMEOUT × (API_MAX_RETRIES + 1) × 2`（默认 180 秒）；gunicorn worker 超时 = 该值 + 120 秒；便携版等待 = 该值 + 30 秒（不少于 120 秒）；OCS 客户端自身约 60 秒放弃等待。

**单进程**：gunicorn 固定 1 个 worker（4 线程），缓存、限流计数与仪表盘记录都在该进程内存中；增加 workers 不会线性扩容。

## ccswitch 模型名净化

ccswitch settings.json 中的模型名可能包含上下文长度后缀（如 `deepseek-v4-pro[1M]`），服务商 API 不识别此格式。服务端与各协议客户端共用同一张净化规则表（`provider_clients.MODEL_SUFFIX_PATTERNS`）：

```
deepseek-v4-pro[1M]   →  deepseek-v4-pro
claude-opus-4-7[200K] →  claude-opus-4-7
```

健康检查接口的 `ccswitch.model_sanitized` 字段指示是否发生净化，`raw_model` 保留原始值。

## 配置重载工作流

```
1. 用户在 ccswitch 中切换 API / 模型
2. settings.json 自动更新
3. POST /api/config/reload → 重新读取 settings.json（半写时重读一次，仍失败则保留原配置）
4. 服务新建 AI 客户端与缓存；进行中的请求用完旧客户端后再关闭
5. 后续 /api/search 请求使用新配置
```

可在仪表盘 `/dashboard` 点击「重载配置」按钮完成。

## 注意事项

1. **选项答案格式**: 单选/多选题会把 AI 返回的 `B`、`A#C`、`A,C` 等字母答案按本次 `options` 映射为真实选项文本；单选模型返回 `B，因为...` 或 `北京，因为...` 也会归一化为真实选项文本。
2. **提示词隔离**: 题干与选项放在 `<题干>`/`<选项>` 定界块内（伪造的定界标记，包括带空格和全角括号的写法都会被去掉）；系统提示要求照常完成题目本身的作答要求，但不执行其中改变身份、忽略或泄露规则、改变输出格式的语句；疑似注入语句会记录告警（只记摘要，不记原文）。
3. **费用与额度**: 模型服务有使用限制和费用，确保账户额度充足；限流默认每客户端每分钟 60 次 AI 调用。
4. **网络连接**: 确保服务所在机器能访问所配置的模型服务地址。
5. **题库域名**: OCS 脚本头部元信息 `@connect` 中需新增题库配置涉及的域名。
6. **日志隐私**: 日志默认只记录题目长度、题型与哈希摘要，不写题目原文；开发服务器的访问日志只记录路径、不记录查询串；仪表盘问答记录只在内存中保留最近 100 条。
