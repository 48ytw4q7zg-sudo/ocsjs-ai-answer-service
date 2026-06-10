# AI题库服务API文档 v2.1.0

## 概述

AI题库服务是一个基于 Anthropic 兼容协议的智能题库服务，专为 [OCS (Online Course Script)](https://github.com/ocsjs/ocsjs) 设计，通过 AI 自动回答题目。实现与 OCS AnswererWrapper 兼容的 API 接口，集成 ccswitch 动态配置，无需手动管理 API 密钥。

**核心特性**:
- 自动读取 `~/.claude/settings.json` 中的 ccswitch 配置
- 模型名自动净化（去除 `[1M]` 等上下文长度后缀）
- 运行时配置重载（无需重启服务）
- 5 级模型名回退策略

## 接口详情

### 1. 搜索接口

**URL**: `/api/search`

**方法**: `GET` 或 `POST`

**认证**: ACCESS_TOKEN（可选，通过 `X-Access-Token` 头或 `?token=` URL 参数）

**参数**:

| 参数名   | 类型   | 必填 | 说明                                                     |
|---------|--------|------|----------------------------------------------------------|
| title   | string | 是   | 题目内容（最大 2000 字符）                                |
| type    | string | 否   | 题目类型 (single-单选, multiple-多选, judgement-判断, completion-填空) |
| options | string | 否   | 选项内容，通常是A、B、C、D选项的文本                       |

**成功响应** (HTTP 200):

```json
{
  "code": 1,
  "question": "问题内容",
  "answer": "AI生成的答案"
}
```

**失败响应**:

```json
{
  "code": 0,
  "msg": "错误信息"
}
```

**错误码**:

| HTTP 状态码 | code | 说明 |
|------------|------|------|
| 200 | 1 | 成功 |
| 200 | 0 | 业务失败（AI 未返回有效答案） |
| 400 | 0 | 请求参数错误（空问题、过长问题、无效 JSON） |
| 403 | 0 | 令牌验证失败 |
| 500 | 0 | 服务内部错误 |
| 502 | 0 | 无法连接到 AI 服务 |
| 503 | 0 | AI 服务返回错误 |
| 504 | 0 | AI 服务响应超时 |

### 2. 健康检查接口

**URL**: `/api/health`

**方法**: `GET`

**认证**: 无需

**响应** (v2.1.0 增强):

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

**ccswitch 字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `raw_model` | string | settings.json 中的原始模型名（可能含 `[1M]` 后缀） |
| `is_proxy` | bool | 是否通过 ccswitch 本地代理连接 |
| `model_sanitized` | bool | 模型名是否经过净化处理 |
| `config_keys` | [string] | settings.json env 中所有配置键名列表 |

### 3. 配置重载接口 (v2.1.0 新增)

**URL**: `/api/config/reload`

**方法**: `POST`

**认证**: 需 ACCESS_TOKEN

**说明**: 运行时重新加载 ccswitch settings.json 配置，无需重启服务。ccswitch 配置变更后调用此接口使服务即时生效。

**成功响应**:

```json
{
  "success": true,
  "message": "配置已从 ccswitch 重新加载",
  "config_source": "ccswitch",
  "model": "deepseek-v4-pro",
  "base_url": "https://api.deepseek.com/anthropic",
  "raw_model": "deepseek-v4-pro[1M]"
}
```

**回退响应** (ccswitch 不可用时回退到 .env):

```json
{
  "success": true,
  "message": "ccswitch 不可用，已回退到 .env 配置",
  "config_source": ".env",
  "model": "deepseek-v4-pro"
}
```

### 4. 缓存清理接口

**URL**: `/api/cache/clear`

**方法**: `POST`

**认证**: 需 ACCESS_TOKEN

**响应**:

```json
{
  "success": true,
  "message": "缓存已清除 (42条)",
  "count": 42
}
```

### 5. 统计信息接口

**URL**: `/api/stats`

**方法**: `GET`

**认证**: 需 ACCESS_TOKEN

**响应** (v2.1.0 增强):

```json
{
  "version": "2.1.0",
  "config_source": "ccswitch",
  "uptime": 1234567.89,
  "model": "deepseek-v4-pro",
  "base_url": "https://api.deepseek.com/anthropic",
  "cache_enabled": true,
  "cache_size": 42,
  "qa_records_count": 100,
  "ccswitch_raw_model": "deepseek-v4-pro[1M]",
  "ccswitch_is_proxy": false
}
```

## 页面路由

| 路由 | 功能 | 认证 | 说明 |
|------|------|:----:|------|
| `/` | 问答测试 | — | Bootstrap 5 表单 + Axios 调用 `/api/search` + XSS 防护 |
| `/dashboard` | 统计面板 | — | Jinja2 渲染 + DataTables + ccswitch 详情 + 重载/清除按钮 |
| `/docs` | API 文档 | — | `api_docs.md` 渲染为 HTML |

## OCS配置示例

在OCS的自定义题库配置中添加如下配置：

```json
[
  {
    "name": "AI智能题库",
    "homepage": "https://github.com/LynnGuo666/ocsjs-ai-answer-service",
    "url": "http://localhost:5000/api/search",
    "method": "get",
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

## 安全设置

在 `.env` 中设置 `ACCESS_TOKEN=your_token` 后：

| 受保护接口 | 令牌传递方式 |
|-----------|-------------|
| `/api/search` | `X-Access-Token: <token>` 头 或 `?token=<token>` 参数 |
| `/api/cache/clear` | 同上 |
| `/api/stats` | 同上 |
| `/api/config/reload` | 同上 |

> `/`、`/dashboard`、`/docs`、`/api/health` 不受令牌保护。

## ccswitch 模型名净化 (v2.1.0 新增)

ccswitch settings.json 中的模型名可能包含上下文长度后缀（如 `deepseek-v4-pro[1M]`），DeepSeek API 不识别此格式。

`ccswitch.py` 的 `_sanitize_model_name()` 函数会自动去除方括号后缀：
```
deepseek-v4-pro[1M]  →  deepseek-v4-pro
claude-opus-4-7[200K] → claude-opus-4-7
```

健康检查接口的 `model_sanitized` 字段指示是否发生净化。

## 配置重载工作流 (v2.1.0 新增)

```
1. 用户在 ccswitch 中切换 API / 模型
2. settings.json 自动更新
3. POST /api/config/reload → 重新读取 settings.json
4. 服务新实例化 Anthropic 客户端
5. 后续 /api/search 请求使用新配置
```

可在仪表盘 `/dashboard` 点击「重载配置」按钮完成。

## 注意事项

1. **多选题答案格式**: 对于多选题，OCS期望的答案格式是用`#`分隔的选项，例如`A#B#C`。本服务通过 4 种模式自动检测并转换。
2. **API请求限制**: 注意 DeepSeek API 有使用限制和费用。确保账户有足够额度。
3. **网络连接**: 确保服务所在服务器能访问 `api.deepseek.com`。
4. **题库域名**: OCS 脚本头部元信息 `@connect` 中需新增题库配置涉及的域名。
5. **模型名后缀**: 使用 ccswitch 时，服务会自动去除模型名中的 `[1M]`/`[200K]` 等后缀，无需手动修改。
