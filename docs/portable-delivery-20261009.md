# EduBrain 便携交付记录

更新：2026-10-09。状态：`release-verified`。

本轮完成 52 条优化建议对应的源码优化，并用 Claude Code `claude-opus-5-5`（effort max）做了多轮独立复查，复查结论全部修复后重新构建 Windows 11 x64 便携包。

## 本次交付

| 项目 | 值 |
|---|---|
| GitHub 仓库 | [48ytw4q7zg-sudo/ocsjs-ai-answer-service](https://github.com/48ytw4q7zg-sudo/ocsjs-ai-answer-service) |
| 源码分支 | `main`（同步推送 `optimize-2026-09-review`） |
| 本次发行位置 | [portable-20261009](https://github.com/48ytw4q7zg-sudo/ocsjs-ai-answer-service/releases/tag/portable-20261009) |
| 本地发行目录 | `D:\1\ocsjs-ai-answer-service\dist\EduBrain-Windows-x64-20261008-224558-9d1ef5` |
| ZIP | `EduBrain-Windows-x64.zip` |
| ZIP 大小 | 39,215,376 bytes |
| ZIP SHA256 | `c8810677af006d3e4af29aa3e68c9e218c9cca7e9a130206ddddb7ccb96b9a49` |
| 实际构建源码提交 | `d3d3dd5f8221289a337f713152e7975a4a22d987` |
| 构建证据 | `.build\windows-20261008-224558-9d1ef5\evidence\` |
| bundle 验收记录 SHA256 | `6F5F405CCEF9A9AD6B7581B69A1015998F9AE7FBCE1A0463358A9E88B5907EB2` |

解压后保留完整的 `EduBrain` 文件夹和 `_internal`，不要直接在 ZIP 内运行，也不要只复制 EXE。便携包自带运行库，不需要安装本机 Python。双击 `EduBrain.exe` 打开控制窗口；`EduBrain-console.exe` 用于控制台检查。

包内 README 是构建时的快照，其中“最新发行”一栏指向上一版；最终源码提交只追加本记录与 README 发行信息等文档更新，实际构建代码版本以上表为准（构建时 49 项源码输入与该提交逐字节一致）。

## 本轮主要改进

- 访问控制：未设置 `ACCESS_TOKEN` 时只接受本机直连；旧式网址/请求体令牌可用 `ALLOW_LEGACY_TOKEN_LOCATIONS=false` 关闭，关闭后首页仍可通过请求头进入统计面板；`/api/session` 先读完请求体再拿全局锁。
- 上游错误：三种协议下无法解析的响应（HTML、空或截断的 JSON、字段不符）统一返回 502 `upstream_invalid_response`。
- 答案缓存：按“协议/模型/提示词版本”分命名空间；可选 SQLite 磁盘缓存只存题目哈希与答案；磁盘读写不占全局锁和缓存锁；“清空缓存”对内存、磁盘和在途写入都生效；热门答案定期刷新访问时间；关闭磁盘缓存后释放文件句柄。
- 便携配置：备份 `profile.json.bak` 只保留能用当前密码解开的密钥；生成新口令后提醒重新保存；清空缓存提示写清磁盘缓存范围。
- 依赖与部署：cryptography 放宽到 `<51`（50.0.1 修复 CVE-2026-69247），`requirements-lock.txt` 记录已测试版本，Docker 按锁文件安装；健康检查不再加载 SDK（新模块 `provider_settings.py`）；打包闸门要求 4 项故障提示自检。

## 检查结果

| 检查 | 结果 |
|---|---|
| Python 回归（10 个套件） | 203 个测试全部通过 |
| Node 浏览器脚本 | `test_browser_navigation.cjs`、`test_dashboard_logic.cjs` 通过 |
| 快照完整性 | `packaging/test_snapshot_integrity.py` 19 个测试通过 |
| 构建门禁 | 源码自检、无控制台审计、依赖锁定与第三方资源哈希通过；`pip check` 无冲突 |
| 冻结 GUI / 控制台自检 | 各 25 项通过（含 4 项故障提示可读性），退出码均为 0 |
| 包内文件核对 | 1,159 个文件逐项核对 ZIP、展开文件、SHA256SUMS 与 bundle 清单；ZIP CRC 通过 |
| 迁移与运行环境 | 中文空格路径迁移、无关工作目录、最小 PATH、阻断外部程序均通过 |
| 依赖安全 | OSV 查询 0 条命中（2026-09-27）；打包环境 cryptography 50.0.1 |

## 独立复查

复查使用 Claude Code CLI，模型 `claude-opus-5-5`，effort `max`（用户指定）。2026-09-27 查询 Anthropic 官方模型页时，Opus 5.5 在当前可用模型列表中；页面另列有定位更高的 Fable 5.1，本账号调用时提示额度用尽，因此按用户指定使用 Opus 5.5。复查只读，不读取 `.env` 和 cc-switch 配置。

| 轮次 | 会话 ID | 范围 | 结论 | 处理 |
|---|---|---|---|---|
| 全量复查 | `2234d19a-b54f-4486-8e8d-37695f22dccb` | `5663d55..dbe56ca` | 无阻塞；5 个 P2、8 个 P3 | `79d753a`、`9d69c9f` 全部修复 |
| 修复复查 | `cb153462-d23b-40ed-958e-98084d4d2f07` | `dbe56ca..9d69c9f` | 无阻塞；1 个 P2、6 个 P3 | `656d55c` 修复 |
| 终审 | `4ca1d7a0-74fc-4e97-9da3-2c720c278c22` | `9d69c9f..656d55c` | 无 P1/P2；3 个 P3 | `b0f2016` 修复 |
| 收尾确认 | `8ba5a965-0a3a-4f12-b512-5b1b08ca11a7` | `656d55c..b0f2016` | 3 项修复成立；发现 1 个本批引入的小概率竞态（P3） | `d3d3dd5` 修复 |
| 竞态修复确认 | `ed646012-109b-44ed-b240-f97b52011882` | `b0f2016..d3d3dd5` | 无阻塞，FINDINGS 为空；4 条可选建议 | 记为后续可选项 |

另有几次复查因账号额度上限在出结论前中断，结果未采用。

## 清理记录

- 已移除被本次新包取代的发行目录：`dist/EduBrain-Windows-x64-20260913-002234-e843f4`（上一版，其 ZIP 仍保存在 GitHub 草稿发行 portable-20260913）以及本轮中间构建 `20260927-111852-47c548`、`20261008-170508-1fa298`、`20261008-174507-fcfaf0`、`20261008-222826-f0ceaa`。
- 删除前确认要保留的新包 ZIP 哈希与上表一致，旧目录中没有链接或重解析点，也没有用户数据。
- `.build/` 下全部构建证据按项目规则保留。`.env`、环境配置变体、可变 `data/` 和测试临时目录不进入源码提交。

## 后续可选项（复查提出、暂未实施）

- 退出时等待后台关闭线程改为共用一个总截止时间（目前每个线程最多等 5 秒）。
- 为“清空期间运行时重建”补一个带磁盘库、连续两次重建的回归测试。
- 清空接口返回的条数取各次清空中的最大值，新旧实例内容不同时显示可能偏小（只影响显示）。
- 清空期间若重建切换到另一个磁盘文件，旧文件可能未被删除，之后切回该文件时在过期前可能读回旧答案（触发条件苛刻，改动前即存在）。

## 验收边界

- 实测主机为 Windows 11 Pro x64（26H2，build 26300.9550）；其他 Windows 构建及无预装运行库的干净系统未实测。
- Windows 10 x64 未进行实机测试，用户于 2026-09-08 豁免，非阻塞；这不是实机通过声明。
- 实体 USB 文件系统及受管设备策略未验证、未豁免。
- 真实提供商账号、额度、计费及实际模型可用性未验证；协议验收使用合成场景。
- Docker 镜像构建需要联网下载，未在本机运行（锁文件中 32 个包均声明支持 Python 3.12）。
- HawkScan 动态安全扫描未运行（本机未配置 `HAWK_API_KEY`）。
- Windows 7/8.1、32 位系统和原生 ARM64 不在本次支持范围。
