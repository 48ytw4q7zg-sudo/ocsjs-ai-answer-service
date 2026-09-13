# EduBrain 便携交付记录

更新：2026-09-13。状态：`release-verified`。

本次源码优化、Windows 11 x64 便携包构建及独立发行复核已完成。旧的通用进程包装命令曾被拒绝；之后通过同一执行工具提交项目原生构建入口并成功执行，没有修改审批或安全规则。

## 本次交付

| 项目 | 值 |
|---|---|
| GitHub 仓库 | [48ytw4q7zg-sudo/ocsjs-ai-answer-service](https://github.com/48ytw4q7zg-sudo/ocsjs-ai-answer-service) |
| 源码分支 | `main` |
| 本次发行位置 | [portable-20260913](https://github.com/48ytw4q7zg-sudo/ocsjs-ai-answer-service/releases/tag/portable-20260913) |
| 本地发行目录 | `D:\1\ocsjs-ai-answer-service\dist\EduBrain-Windows-x64-20260913-002234-e843f4` |
| ZIP | `EduBrain-Windows-x64.zip` |
| ZIP 大小 | 38,112,495 bytes |
| ZIP SHA256 | `04167abcebdbc34992bbaec0ee63f0a8ba0bb38afc58667dc420652cc76a1810` |
| 实际构建源码提交 | `228b38c611bd23c0aeaedf10bb2dfcf678d718aa` |
| 构建证据 | `.build\windows-20260913-002234-e843f4\evidence\` |
| bundle 验收记录 SHA256 | `B752C0984B1DF09BA8E643745B65FA5849EDAF9EE585F8B8F223BFA8EFF2736C` |

解压后保留完整的 `EduBrain` 文件夹和 `_internal`，不要直接在 ZIP 内运行，也不要只复制 EXE。Windows 便携包自带运行库，不需要安装本机 Python。

双击 `EduBrain.exe` 打开控制窗口；`EduBrain-console.exe` 用于控制台检查。配置和运行数据保存在应用的数据目录中。

两份电池 HTML 和答题服务 `health_smoke.py` 属于源码交付，不作为独立文件放入 EXE 包。最终源码提交可以包含本记录等文档更新；实际构建代码版本以上表为准。

## 验收与主要改进

- 便携客户端隔离宿主认证信息，错误日志不记录上游回显正文。
- 配置重载保护在途客户端，旧响应不能回填已清理或替换的缓存。
- 三种协议的非最终响应和待处理工具回合不作为成功答案或缓存。
- 统计面板操作、源码启动入口和健康检查失败语义已修复。
- 源码运行要求 Python 3.10+；当前 Anthropic SDK 依赖范围为 `>=1.0,<2`。

| 检查 | 结果 |
|---|---|
| 既有后端回归 | 85 通过；另 1 项模板文档断言按约定未加载 |
| 新服务端回归 | 21 通过 |
| 独立协议状态重放 | 41 场景通过 |
| 健康检查 | 18 通过，另 10 组独立 CLI 场景通过 |
| 快照完整性及 Windows 10 豁免 | 19 通过 |
| 统计面板操作 | 10 场景通过，令牌及超时回归通过 |
| 实际 CMD 启动测试 | 4 通过，使用合成应用 |
| 新冻结 GUI / 控制台 | 各 21 项检查通过，退出码均为 0 |
| 源码 / Analysis / 资源绑定 | 48 项源码输入、39 项快照输入、27 项资源匹配 |

新包的 1,157 个文件已逐项核对 ZIP、展开文件、校验清单及 bundle 清单。中文空格路径迁移、不同工作目录、最小 PATH 和包内运行库均有通过记录。

独立审核使用 Codex `gpt-6-astra / max`，运行 ID 为 `01a09670-b319-7e60-9ccb-7c1a648289e4`，批准范围为上述精确源码与产物。详细源码哈希和检查记录见 [source-verification-20260913.json](source-verification-20260913.json)。

## 清理记录

- 已移除被本次新包替代的旧发行目录 `dist/EduBrain-Windows-x64-20260912-064325-306783`。
- 删除前确认旧归档哈希及展开文件一致，没有额外文件、重解析点或用户数据。
- 保留新发行包及全部必要构建证据。
- `.env`、环境配置变体、可变 `data/` 和测试临时目录不进入源码提交。

## 验收边界

- 实测主机为 Windows 11 Pro x64，build 26200；其他 Windows 构建及无预装运行库的干净系统未实测。
- Windows 10 x64 未进行实机测试，用户于 2026-09-08 豁免，非阻塞；这不是实机通过声明。
- 实体 USB 文件系统及受管设备策略未验证、未豁免。
- 真实提供商账号、额度、计费及实际模型可用性未验证；协议验收使用合成场景。
- Windows 7/8.1、32 位系统和原生 ARM64 不在本次支持范围。
