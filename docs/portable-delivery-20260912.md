# 便携交付索引（2026-09-12）

追加源码优化和源码层复核已完成；构建启动被宿主执行策略拒绝，尚未重新打包或推送 GitHub。状态：`source-verified-build-blocked`（更新：2026-09-13）。

用户已撤销“9 月 16 日前不推送”的限制，授权在本次整体优化和验收完成后上传。下表保留追加修改前候选包的路径和哈希，不能将其作为本次追加优化后的最新版发布。

## 追加优化与回归结果

- `health_smoke.py` 保留已有 JSON 报告重构，统一单项失败、`failure_reasons`、退出码、标准输出和文件报告的结果；区分无效载荷、网络、HTTP、超时及报告写入失败。
- 严格检查 UTF-8、非有限 JSON 数值、Unicode、响应大小和 HTTP 截断；异常 HTTP 内容不写入报告。JSON 使用 ASCII 转义，兼容 Windows 控制台编码；断管后保持失败退出码一致。
- 报告使用独立临时文件原子替换，失败时保留旧报告并清理本次临时文件。新增 `test_health_smoke.py` 的 18 项测试通过，包括真实回环 HTTP 和 CLI 子进程。
- 保留现有 Windows 10 豁免生产逻辑及文档。打包回归共 19 项通过；新增测试执行真实 `verify()` 和 JSON 写入路径，验证生成证据中的豁免及未验证字段。原生可执行文件启动在该合成测试中使用替身，不等于重新构建验收。

## 2026-09-13 源码层收尾

- 便携 Anthropic 客户端隔离宿主认证令牌及自定义头，不修改进程环境；异常日志只记录安全描述、类别和数字状态。
- 运行时引用覆盖实际请求和响应处理；重载等待旧请求释放后再关闭旧客户端，旧答复不能回填已清理或替换的缓存。
- 三种协议只接受明确的最终成功状态，同时兼容省略可选状态的旧响应；失败、取消、排队、工具回合、过滤及未知状态不会被当作答案或缓存。
- 统计面板的清除缓存、重载配置操作恢复正常；源码批处理优先使用项目解释器，经实际 HTTP 就绪检查后才打开真实监听地址，并保留失败退出码。
- 源码运行要求为 Python 3.10+，Anthropic SDK 范围为 `>=1.0,<2`，本机已测试版本为 1.4.0；运行数据、环境配置变体和临时测试目录已从 Git 排除。

| 验证组 | 最终有效结果 |
|---|---|
| 既有后端套件 | 85 通过；另 1 项模板文档断言按约定未加载 |
| 新服务端回归 | 21 通过 |
| 独立提供方状态重放 | 41 场景通过 |
| 健康检查 | 18 通过，另 10 组独立 CLI 场景通过 |
| 打包快照及豁免证据 | 19 通过，包含实际 JSON 生成路径 |
| 统计面板操作 | 10 场景通过，令牌与超时清理回归通过 |
| 真实 CMD 启动入口 | 4 通过，使用合成应用，覆盖复杂路径、解释器选择及退出码 |

关键源码、测试及配置的哈希已与独立复核结果逐项比对，记录在 [源码验证记录](source-verification-20260913.json)。记录属于源码层证据，不是冻结发行包批准。

两个隔离 Windows 构建启动命令均在创建进程前被宿主拒绝，返回仅为 `blocked by policy`，没有更具体原因。本轮未以其他方式重试该构建。仍需完成新便携包构建及运行验收、更新交付路径和哈希、清理过时候选，再同步 GitHub；下面的历史候选不能替代这些步骤。

## EduBrain（ocsjs-ai-answer-service）

| 项 | 值 |
|---|---|
| 发行目录 | `D:\1\ocsjs-ai-answer-service\dist\EduBrain-Windows-x64-20260912-064325-306783` |
| ZIP | `EduBrain-Windows-x64.zip`（38,104,343 bytes） |
| ZIP SHA256 | `EE0F6825D4DB526FA6C21433201A14C56211B2B2ADF5116837F081AF2A4DA01C` |
| 构建证据 | `.build\windows-20260912-064325-306783\evidence\` |
| 验收主机 | Windows 11 Pro 25H2，build 26200.9168，AMD64 |

解压 ZIP 后保留整个 `EduBrain` 文件夹，双击 `EduBrain.exe`。勿拆分 `_internal`，勿在 ZIP 内直接运行。

**生成证据中的豁免/未验证字段**（`bundle-verification.json` → `release_status`）：

- Windows 10 x64：`physically_tested=false`，`user_waived=true`，`blocking=false`（用户 2026-09-08 豁免，非阻塞）
- 实体 U 盘：`user_waived=false`，明确未验证
- 真实模型账号/凭据/计费：`user_waived=false`，明确未验证

## HyperBatteryHealthCalc

| 项 | 值 |
|---|---|
| 发行目录 | `D:\1\HyperBatteryHealthCalc-main\dist\HyperBatteryHealthCalc-Windows-x64-20260912-064031-f7e2b9` |
| ZIP | `HyperBatteryHealthCalc-Windows-x64.zip`（15,333,816 bytes） |
| ZIP SHA256 | `D0A9124C40C56E4D26CAA025AB92663BD2FE5709FD22899885D0DF1F0A2D3313` |
| 构建证据 | `.build\windows-20260912-064031-f7e2b9\evidence\` |
| 验收主机 | Windows 11 Pro 25H2，AMD64 |

解压 ZIP 后保留整个 `HyperBatteryHealthCalc` 文件夹，双击 `HyperBatteryHealthCalc.exe`；命令行用 `HyperBatteryHealthCalc-cli.exe`。

**兼容性说明**（见 `packaging/verify_portable.py` → `release_status`）：

- Windows 10 x64：未实机测试；用户已豁免（2026-09-08），非阻塞
- 实体 U 盘：未验证，未豁免

## 此前候选已包含的源码要点

- ocsjs：默认回环监听、无 CORS 通配、short-answer、Win10 豁免结构化证据、healthcheck degraded
- HyperBattery：三端学习容量 `round` 对齐、内层 ZIP 512MB 上限、report_io CRLF 修复、评分区间补洞

## 仍有限制

1. Windows 10 实机启动/功能未测（已豁免）
2. 实体 USB / 受管设备策略未测
3. 真实供应商账号、额度、计费未验证
4. Windows 7/8.1、32 位、原生 ARM64 不在范围

此前历史 ZIP / 旧 dist 清理记录保持不变；下一次构建验收后再更新交付路径与哈希，并据此清理过时候选。
