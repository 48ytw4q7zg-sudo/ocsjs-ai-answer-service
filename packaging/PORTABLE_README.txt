EduBrain：Windows x64 便携答题服务

开始使用
1. 将整个 ZIP 解压到可写文件夹，双击 EduBrain.exe。
2. 可以把整个 EduBrain 文件夹复制到 U 盘或其他电脑。
   必须保留 _internal，不能只复制 EXE，也不要直接在 ZIP 内运行。
3. 原生窗口内可填写协议、服务地址、模型标识及自己的 API Key，应用后提交问答。
4. 网页是可选入口。原生功能不需要安装 Python、Node、Docker 或浏览器。
5. 关闭窗口会停止本地服务。等待退出完成后再拔出 U 盘。

系统及网络
- 目标系统：Windows 10/11 64 位 x64。32 位 Windows 和 ARM64 原生运行不在范围内。
- Python、Tk、服务依赖、网页静态资源和 CA 证书均随包提供。
- 本机服务只监听回环地址。接口地址和端口以窗口显示为准。
- 离线可打开窗口、查看本地说明；向在线模型问答仍需网络、有效账号及额度。
- 此包不包含模型权重、真实账号、API Key、已保存配置或日志。
- 不要求管理员权限。请选择可写目录，不要放在 Program Files 等受保护位置。

配置与移动
- 默认数据位置为 EXE 旁的 data 文件夹，发行时该文件夹为空。
- 密钥默认不保存。选择密码加密保存后，在另一台电脑需要同一密码解锁。
- 密码不会随包保存。请勿将真实密钥写入普通地址、模型名称或文档。
- 复制接入配置会包含本地访问口令，使用后请妥善保管，不要公开分享。
- 界面打开或配置应用成功，只表示本地程序就绪，不代表真实模型请求已成功。

合成自检
在 PowerShell 中使用绝对 JSON 输出路径，例如：
  .\EduBrain.exe --self-test --self-test-output "D:\便携测试\gui.json"
  .\EduBrain-console.exe --self-test --self-test-output "D:\便携测试\console.json"

EduBrain.exe 没有控制台。等待进程结束后查看 JSON 的 passed 字段。
相邻的 *.runtime.json 是打包验收补充记录，记录输出流、运行库路径和回环调用。
自检仅使用生成的数据、合成凭据及本机回环协议服务，并创建和关闭自己的 Tk 窗口。
自检不验证真实账号，不调用外部模型，也不启动浏览器或其他程序。
EduBrain-console.exe 是保留控制台输出的诊断入口；正常使用请选择 EduBrain.exe。

文档与许可
- 原项目说明已打包为 _internal\README.md，本地 /docs 页面使用该文件。
- 网页组件声明见 _internal\THIRD_PARTY_NOTICES.md；原始许可证随组件保留。
- 项目许可证见 LICENSE.txt；Python 许可证见 _internal\licenses\python。
- 本发行包未做代码签名。构建者保留完整哈希及本机验收记录。
- 兼容性只以实际验收系统为证；Windows 10 x64 实机测试已由用户豁免（非阻塞），其他 Windows 构建、真实 U 盘及真实模型账号仍需单独验证。
