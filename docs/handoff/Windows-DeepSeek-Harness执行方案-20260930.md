# Windows 上的 DeepSeek Harness 执行与 Codex 监督

2026-09-30，用户已确认产品与操作系统。此文件是实施方案，未在目标电脑执行安装、调用模型或连接远程主机。

## 选定方案

优先在安装 dsh 的 Windows 电脑上部署项目副本和具有本地项目/终端权限的 Codex。Codex 分派工作包，dsh 单独实施；dsh 退出且目录停止写入后，Codex 检查 diff 并复跑测试。验收通过再发下一包，失败则发有编号的返工单。

无需把云端作为第一步。云端监督本地 dsh 仍要额外的通信与结果同步通道；同机调用先减少这一层依赖。当前电脑没有在 PATH 中检测到 dsh，这不能代表另一台目标电脑的安装状态。

## 官方接口核实

官方 CLI 提供 headless 单任务，以及 SDK JSON-RPC 和 ACP stdio 接口。第一阶段选 headless；需要结构化会话控制时再使用 SDK，先验证恢复和终止行为，不假定 headless 可用未记录的 resume 参数。[CLI 官方文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/README.md)

官方 Desktop 可通过应用菜单 Manage dsh Command 安装命令，Windows 注册到当前用户 PATH。安装后重开终端核实版本；不要为找不到命令就盲目叠装另一个发行版。[Desktop 官方文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md)

Python SDK 文档支持 Windows x64。其 sdk-minimal 示例缺少部分长任务能力，工作目录设置也不是文件访问沙箱；因此不直接把 minimal 示例当作长期监督运行器。[SDK 官方文档](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/python-sdk.md)

## 第一步：目标电脑检查

在目标电脑新开 PowerShell，执行以下只读检查，输出不含 API Key：

```powershell
Get-Command dsh -All | Select-Object Name, Source
dsh --version
dsh --help
Get-Command pwsh -ErrorAction SilentlyContinue | Select-Object Name, Source
py -0p
node --version
npm --version
git --version
```

记录 dsh 是官方 Desktop 自带命令、npm 安装还是其他构建，以及目标模型/provider 是否已在 headless 所用配置中可用。桌面端登录成功不作为 headless 凭据已打通的证据；不要复制登录令牌或把密钥放进项目文档/提示词/日志。这里只需要报告版本和配置是否可用。

## 第二步：代码迁移

按 `DSH-Codex协作方案-20260930.md` 的打包清单复制当前源码。目标路径示例为 `C:\work\ai-platform`，它不是已经创建的路径。

保留完整的 backend/app、alembic、tests 和 frontend/app、components、hooks、lib、tests，以及依赖清单、脚本、设计、进度和隔离验收资料。必须包含未跟踪源码。重建依赖，不搬运行库、真实 .env、凭据、node_modules 或 .venv。

原电脑已提供 `scripts/pack_dsh_handoff.py`。在项目根目录执行 `python scripts/pack_dsh_handoff.py`，会在 `handoff-packages/` 生成带时间戳的 ZIP；`--dry-run` 仅显示文件数量和体积。包中 `HANDOFF-MANIFEST.json` 记录每个实际打包文件的 SHA-256，结束时进行 ZIP CRC 校验。脚本按路径排除环境文件/运行库/缓存，不代表已对源码与文档完成敏感内容审计。打包期间不要同时修改源码；它是文件快照，不含 Git 历史或可直接启动的依赖环境。

项目源码交给 dsh 所配置的模型处理本身也是数据传输边界；先确认这些代码/资料允许发送到该 provider。项目内部测试使用 Mock，只表示测试不调用真实业务模型，并不表示执行编码任务的 dsh 免费或离线。

## 第三步：发第一单

先由目标电脑上的 Codex 检查 M0 任务范围、模型和执行权限。以下为已核实 CLI 语法的使用示例，不会在当前机器自动运行：

```powershell
Set-Location -LiteralPath 'C:\work\ai-platform'
dsh --profile headless '阅读 docs/handoff/DSH接手提示词-20260930.md。本次仅完成第5节 M0 环境复现与交接基线，不进入 B3-R1，不提交或推送，不修改业务代码，不使用生产库或凭据。将实际命令、退出码、失败与未验证项写入 docs/handoff/dsh-M0-result.md，然后退出。'
```

首次调用可能需要配置该 profile 的模型和授权；配置未完成就停在该步骤，不自动切模型或从其他应用提取凭据。要把 Codex/dsh 权限限制到实际需要的范围；提示词中的“禁止”不能替代操作系统权限控制。

M0 通过后，每次只发一个功能包。例如 B3-R1 的任务描述必须包含接手提示词第6节约束，并明确“完成后退出，等待监督验收”，避免执行方越过审查同时修改下一条链路。

## 第四步：监督协议

每个任务目录包含以下文件（约定，不是 dsh 内置 API）：

| 文件 | 负责人 | 内容 |
| --- | --- | --- |
| task.md | Codex | 目标、基线、文件范围、禁止事项、验收命令 |
| status.json | 调度器 | task_id、状态、PID、开始/更新时间、退出码 |
| result.md | dsh | 改动、证据、未完成项；成功文字不等于验收通过 |
| review.md | Codex | 复核结果、返工项、是否进入下一包 |

单次启动保存任务唯一 ID；重复派单先查状态，避免双写。同一项目只允许一个实现任务活动。心跳过期先检查进程与输出，不直接再启动一份；超时或限额中断时保存断点，不无限重试。

Codex 审查阶段至少核对实际新增/修改文件、关键负例和测试退出码。未跟踪文件也必须审查，不能只看 git diff。不得自动合并、推送或部署。既有进度记录是恢复入口，不把聊天历史当唯一状态库。

## 连续运行与跨电脑

长任务需要主机保持在线、工作区可读写、模型可用且执行端保持运行。当前聊天不会在结束后天然成为后台守护进程。先完成本地闭环，再在实际运行端配置定时检查或常驻调度；没有建立状态源与调用通道之前，不宣称“正在持续盯着”。

若仍希望由当前电脑监督另一台电脑，可在后续选定受控远程执行或任务队列通道；只接受结构化任务、返回状态与成果，不开放任意公网 shell。Codex Cloud 则更适合独立仓库任务和审查，不是本机 dsh 的默认控制通道。

## 接收电脑给 Codex 的启动提示词

> 你是此项目的监督代理。先读取 docs/handoff/Windows-DeepSeek-Harness执行方案-20260930.md、DSH接手提示词-20260930.md 和 ai-skill-center-implementation-report.md。核实本机 dsh 版本、模型配置、权限和项目根目录。先组织 M0，确认结果后再按工作包调用 DeepSeek Harness。每包 dsh 结束后，你检查实际改动并复跑关键测试，写审查记录；通过才继续下一包，失败则给具体返工指令。禁止双代理同时修改同一目录，禁止未经授权提交、推送、部署及访问生产凭据。额度或依赖阻塞时保存完整断点，不能伪报完成。
