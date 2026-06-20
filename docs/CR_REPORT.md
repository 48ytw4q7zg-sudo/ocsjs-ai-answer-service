# Q-CR 审查报告 — v2026.6.10.1739 终审

## 审查轮次
- **第 1 轮**: v2026 initial → R-14(type注解) / R-15(引号语法) / R-16(选项字母正则) ✓
- **第 2 轮**: 修复后终审 → R-17(dead code) / R-18(类型注解残留) ✓
- **第 3 轮**: 最终审查 → **零发现**

## 已修复索引
| ID | 文件:行 | 问题 | 轮次 |
|----|---------|------|:---:|
| R-14 | app.py:88 | _extract_text_from_response 含 str\|None 注解 | 1 |
| R-15 | utils.py:122 | _build_instructions 中文引号语法错误 | 1 |
| R-16 | utils.py:156 | _OPTION_LETTER_PREFIX_RE 缺少 ? 可选 | 1 |
| R-17 | utils.py:143-150 | _build_instructions 重复 single+has_options dead code | 2 |
| R-18 | app.py:110 | _call_ai 残留 # type: 注解 | 2 |

## 当前版本
- **版本号**: 2026.6.10.1739
- **提交**: d1d463e (pushed)
- **状态**: 干净（仅 .env 未跟踪）

## 2026-06-20 追加优化轮次

### Codex 自审发现
- **R-19**: `Config.MAX_TOKENS` 未被 `_call_ai()` 默认调用使用，实际仍写死为 300。
- **R-20**: `ccswitch.extract_all_env()` 会把 `ANTHROPIC_AUTH_TOKEN` 等敏感配置值带入运行态展示数据。
- **R-21**: `/dashboard` 在配置 `ACCESS_TOKEN` 后仍可无令牌访问完整运行信息。
- **R-22**: `/api/health` 在配置 `ACCESS_TOKEN` 后仍向无令牌请求暴露 `base_url`、`config_keys` 等详细信息。
- **R-23**: 仪表盘的「重载配置」「清除缓存」请求未携带访问令牌，启用 `ACCESS_TOKEN` 后按钮会失败。
- **R-24**: `python -m unittest discover` 默认未发现新增测试。

### 已修复
| ID | 文件 | 修复 |
|----|------|------|
| R-19 | `app.py`, `tests/test_security_and_config.py` | `_call_ai()` 默认使用 `Config.MAX_TOKENS`，显式 `max_tokens` 仍可覆盖。 |
| R-20 | `ccswitch.py`, `app.py`, `tests/test_security_and_config.py` | 新增 `sanitize_env_for_display()`，对 `TOKEN`、`API_KEY`、`SECRET`、`PASSWORD` 类字段统一显示 `<hidden>`。 |
| R-21 | `app.py`, `tests/test_security_and_config.py` | 设置 `ACCESS_TOKEN` 后，`/dashboard` 必须带有效令牌访问。 |
| R-22 | `app.py`, `tests/test_security_and_config.py` | 设置 `ACCESS_TOKEN` 后，`/api/health` 无令牌只返回最小状态，带令牌才返回详细配置。 |
| R-23 | `templates/dashboard.html`, `tests/test_security_and_config.py` | 仪表盘从 URL 查询参数读取 token，并在受保护操作中发送 `X-Access-Token`。 |
| R-24 | `tests/__init__.py` | 默认 unittest discovery 可发现并运行新增测试。 |

### 验证
- `python -m unittest discover -v`：10 项通过。
- `python -m py_compile app.py config.py ccswitch.py utils.py logger.py test_service.py tests\test_security_and_config.py`：通过。
- Flask test client 烟测：`/api/health`、`/`、`/dashboard`、`/docs`、空 `/api/search` 均按预期返回。
