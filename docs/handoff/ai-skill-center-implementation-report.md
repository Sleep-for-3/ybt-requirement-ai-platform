# AI Skill 配置中心实施与续做报告

## 当前检查点

- 更新日期：2026-09-30
- 状态：A6 核心参考实现已验证，B1/B2 持续产品化，B3 已推进字段候选、影响复核、跨语言检索边界与受控候选模型重排；当前线程执行，不安排模型交接
- 基线 HEAD：`3e94e54`
- 当前阶段：B（产品化执行中，外部依赖验收另列）
- 当前工作包：B2 两类跨层 Mapping 核验/采用与过期页面保护已验证；B3 字段候选跨语言召回已验证；B3-R1 受控候选模型重排（Mock/确定性路径 + 门禁）已验证，真实模型质量未验证
- ready_for_sol：不适用（用户取消交接，当前线程持续执行）
- 核心开发完成：true（SQLite + Mock/确定性/Replay 已验证；PostgreSQL 与真实模型未验证）
- 第二部分完整验收：false
- next_action：继续 B3 受控模型查询改写/依赖式多跳与条款比较，扩展固定业务语料评测，随后推进 B4/B5/B6。真实模型质量、PostgreSQL 与真实数据源环境验收仍未完成。

## 权威文档

- 完整需求：`docs/upgrade/AI-Skill配置中心与一般影响问题-执行提示词.md`
- 执行拆分、门禁与提示词：`docs/upgrade/AI-Skill配置中心-两阶段执行方案.md`
- 详细设计：`docs/design/ai-skill-configuration-center-design.md`
- A0 冻结契约与迁移决策：`docs/design/ai-skill-a0-contract-baseline.md`
- P0 交付：`docs/handoff/ai-p0-remediation-goal-report.md`

## 基线说明

P0 报告标记 verified，真实模型 Provider 端到端未验证。本轮抽查确认已有上下文哈希、执行类型和引用保存基础，Prompt user template 仍只读未渲染；未发现 Skill 控制面的实现。P0 历史测试不能替代新改动的验证。

报告中的旧“部分具备/缺失”章节包含修复前盘点，必须结合其最终结论和代码阅读，不能据此重复修复。本轮已核验源码调用方、迁移唯一 head 和隔离 SQLite current；没有读取用户运行库 current 或数据库内自定义 Prompt，未检查用户现有运行服务。

## 工作包状态

| 工作包 | 状态 | 验收证据 |
| --- | --- | --- |
| A0 基线与契约 | verified | 新契约 27 项 + P0 34 项组合共 61 passed；隔离 SQLite 空库到唯一 head 通过；冻结契约已落盘 |
| A1 版本与控制面 | partial | 四表、草稿/发布/绑定/恢复 API 和 SQLite 迁移已验证；PostgreSQL 环境不可用 |
| A2 运行时与输入 | partial | 固定绑定、编译、密级、预算、引用和日志已验证；业务适配在 A4/A5 |
| A3 评测门禁 | partial | 五模式记录、快照门禁、独立审批、原子发布、反馈幂等已验证；完整指标与产品界面仍待补 |
| A4 血缘闭环 | partial | 主链浏览器七项检查通过；九类 Provider 与结构化制度对照已实现，A0–A4 组合 113 passed；真实模型仍未验证 |
| A5 需求/Mapping 保护 | core_verified | 需求与四类 Mapping 原生接入；组合 56 passed、保护 52 passed；固定导出/多脚本 27 + 修复后 1 passed；完整业务浏览器产品化留 B2/B6 |
| A6 复杂扩展与接入契约 | core_verified | 字段候选 17；RAG 范围 36；复核 11；事件/缓存 21；固定样例 12；治理与血缘修订 40；证据组不累加为唯一用例 |
| B1 | in_progress | 当前线程继续配置页面产品化，取消模型交接 |
| B2 | in_progress | 需求/场景映射来源、制度对照、固定版本文档辅助及两类跨层核验/采用页面已验；完整人工编辑与总体业务验收仍待完成 |
| B3 | in_progress | 目录候选浏览器 5 项、复核浏览器 4 项；检索边界回归 45 项通过；查询分解/模型重排等未完成 |
| B4～B6 | pending | 依两阶段方案继续；外部依赖与生产验收未完成 |

## 规划轮记录

仅新增两阶段方案、本报告，并在原提示词增加编排入口；未修改业务代码，未执行数据库迁移、测试或构建。执行文档差异检查，不将其记作功能验收。

初始工作区存在大量既有未跟踪资料、日志、数据库与构建产物，未删除或修改。未提交、未推送、未部署；本轮没有启动服务或测试进程。

## A0 执行检查点（2026-09-27）

- 开始时 HEAD：`3e94e54`；保留上轮三个规划文档改动及所有既有未跟踪文件。
- 实际模型：运行时未向本任务提供可核实的具体模型 ID；未调用工具切换模型，不据计划名称声明模型实际身份。
- 目标：完成调用方盘点、范围/输入/证据/运行身份契约与负例，冻结后续权限、状态机、兼容与迁移方案。
- 新增代码：`backend/app/schemas/ai_skill.py`，严格范围坐标、证据来源/密级、跨范围一致性、事实/制度引用分类、Legacy/Skill 身份和 context_hash；Skill key 最长 91，兼容旧 Prompt key 的 100 字符列。
- 新增测试：`backend/tests/test_ai_skill_contracts.py`，黄金输入、缺来源/假条款/重复 ID/越权坐标/错误引用/伪 Skill 身份/哈希变化等负例。
- 新增设计：`docs/design/ai-skill-a0-contract-baseline.md`，包含八个业务调用入口（七个实际旧 key）、未接模型的推荐标签、Embedding/连接测试例外及后续迁移表。
- 本轮未改业务入口、运行时、数据库模型/迁移、前端。契约验证不是授权，也不代表发布门禁已实现。
- 权限决定：新控制面必须真实用户，不能继承 optional auth 下 legacy-system 的管理员特例；项目知识管理权限可编辑/测试/提交，正式发布由有权机构/平台管理员审批。
- 固定版本决定：显式采纳继承版本，不动态追 latest；停用/归档不能偷偷回落到其他版本；恢复生成新草稿重新过门禁。
- 后续重点：schema_freeze 与 Model 注册方式；平台绑定 NULL 唯一性；发布事务与双人审批；旧日志派生 Skill 标签不可回填成真实发布身份。
- 启动额度快照：五小时剩余约 81%，周剩余约 97%；仅 codex 额度桶，不用于估算剩余开发时长。

### 测试与隔离环境

命令工作目录：`backend`；解释器：`.venv/Scripts/python.exe`；设置 `DATABASE_URL=sqlite:///:memory:`、LLM/Embedding 为 Mock；测试 conftest 进一步覆盖 Provider 配置。未请求外部模型。

1. `python -m pytest tests/test_ai_p0_security.py tests/test_ai_execution_metadata.py tests/test_generator_context_adapters.py tests/test_llm_gateway.py tests/test_lineage_edge_explanation.py -q`：34 passed，25.79s，退出码 0。
2. `python -m alembic heads`：唯一 `202609200041`；使用任务新建的系统临时目录 SQLite 文件执行 `upgrade head`，查询 `alembic_version` 为 `202609200041`，退出码 0；连接关闭后临时目录已清理。
3. 首批 `python -m pytest tests/test_ai_skill_contracts.py -q`：22 passed，0.52s，退出码 0；随后新增五项任务范围/缺依据/共享证据/长度边界测试，需看下面最终组合结果。
4. 最终组合：`python -m pytest tests/test_ai_skill_contracts.py tests/test_ai_p0_security.py tests/test_ai_execution_metadata.py tests/test_generator_context_adapters.py tests/test_llm_gateway.py tests/test_lineage_edge_explanation.py -q`：61 passed（新契约 27 + P0 34），13.49s，退出码 0。

观察到一条现有 Starlette TestClient/httpx 弃用警告；不影响通过，本轮不升级依赖。

### 验证分类与边界

- 确定性：Schema/引用/哈希契约与隔离迁移。
- Mock：P0 流程回归；没有新增 Skill 业务运行流程。
- 真实模型/Replay/人工评审：本轮未执行；不声明完成。
- PostgreSQL 新增迁移、前端、浏览器：本轮没有对应改动，留待相关阶段。
- 后台状态：全部测试进程已退出；无新增服务端口、容器或持久业务数据库；隔离迁移临时目录已清理。

### 下一轮 A1 首个切片

先 `git status --short`，读取本报告与 A0 契约，再核对 `backend/app/models/__init__.py`、模型基类、`backend/app/schema_freeze/` 和初始迁移的表加载方式，确认唯一 head。实施四张控制面表及必要可空关联和隔离迁移约束测试；涉及文件限于 models、对应迁移、schema_freeze 必需兼容位置、定向测试及报告。暂不开放发布 API、不修改旧 Prompt 默认行为；新迁移必须验证 SQLite 与可用的任务专用 PostgreSQL，环境不可用需如实记录。

## 每轮必须追加的检查点格式

## A2/A3 连续执行检查点（2026-09-27）

- A2：新增固定绑定解析与运行服务；任务绑定优先、项目继承版本固定，不追踪上级 latest。密级不符、模板越权、超 UTF-8 字节/保守 token 预算时调用前拒绝；输出坏引用或 Provider 失败时保留事实和缺口。新增真实 Skill FK 和 input_contract_version 日志字段，旧行保持 NULL。
- A3：新增三张评测表与 `202609270043` 迁移；确定性、Mock、真实模型、Replay、人工评审分别记录；人工评审需独立授权审核，Mock 不能计入真实模型。
- 发布要求：最新确定性测试与对应 Provider 模式测试均通过；内容哈希、测试集快照、test_epoch、模型配置指纹一致；编辑/回退草稿使旧测试失效；编辑者不得自己审批。版本/Prompt 快照/绑定/审计/事件同一事务写入，绑定冲突时全部回滚。
- 已发布模型配置漂移会阻断解析，不偷偷换模型。恢复旧版本只生成新草稿；deprecated 保留现有固定调用但不能新增绑定。
- A2 定向验证：`test_ai_skill_runtime.py test_ai_skill_control.py test_ai_execution_metadata.py test_llm_gateway.py`，29 passed，19.62s。
- A3 首轮失败：一项测试把非机构成员被拒绝的 404 误写为 403；修正测试夹具，先授予机构权限再验证编辑者不可自审批，未放宽产品权限。
- 组合验证：`test_ai_skill_releases.py test_ai_skill_control.py test_ai_skill_runtime.py test_ai_skill_migration.py test_ai_p0_security.py test_ai_execution_metadata.py test_lineage_edge_explanation.py`，45 passed，69.72s，退出码 0。涵盖新测试集/模型变更失效、回退失效、事务回滚、真实 API 路由授权、SQLite 全迁移往返和旧行为回归。
- 新增服务 `evaluation.py`、`releases.py`，新增运行/结果/评审、测试用例/批次、绑定、提交/发布/恢复相关 API；旧 `release_gate_unavailable` 实现已被实际服务端门禁替代（历史检查点描述的是当时状态）。
- 当前无测试进程、外部模型或用户数据库写入。PostgreSQL/浏览器/真实模型仍未验证；继续 A3 收尾与 A4。

## A1 连续执行检查点（2026-09-27）

- 新增 `models/ai_skill.py` 四表与独立历史 DDL `202609270042`；旧 schema_freeze 无需修改，历史迁移不会提前创建新表。
- 新增 `schemas/ai_skill_control.py`、`services/ai_skills/control.py`、`api/ai_skills.py` 并注册路由：稳定身份、分范围草稿、乐观锁编辑、内容校验、差异和恢复。所有控制面拒绝匿名/Legacy 用户，模型配置与安全开关使用受限 Schema。
- 版本号通过数据库原子计数器分配；作用域绑定使用非空 scope_key 唯一约束，跨定义版本 FK 受数据库约束；发布和提交暂时硬阻断，不能用客户端成功标志绕过。
- `test_ai_skill_migration.py + test_ai_skill_contracts.py`：28 passed，15.95s。SQLite 从 0041 → 0042 → 0041 → 0042，历史 Prompt 数据保持；迁移表字段与 ORM 一致。
- `test_ai_skill_control.py + test_ai_skill_contracts.py`：39 passed，8.13s（控制面 12 + 契约 27），包括跨租户/Legacy/已发布不可编辑、恢复新草稿、模板属性访问拒绝、stale 编辑、审计与 FK/唯一约束。
- PostgreSQL 未验证：PATH 与常见安装位置均未发现 Docker/PostgreSQL 可执行程序；未安装工具、未连接用户数据库。此项保留验收缺口，不阻断 A2/A3 独立开发。
- 无外部模型调用、无服务进程、无提交/推送/部署。继续下一切片，不等待用户再次确认。

```text
日期 / 实际模型（可确认时） / 阶段 / 工作包 / 最小切片：
开始时 HEAD / 既有改动摘要：
本轮目标与验收标准：
决定及冻结契约（代码路径、关键符号）：
新增或修改文件：
运行命令 / 环境 / 退出码 / 结果 / 证据路径：
确定性 / Mock / Replay / 真实模型 / 人工评审分别状态：
失败及是否修复：
未完成编辑或测试：
后台进程、端口、隔离数据库/构建目录及清理状态：
额度快照（可用时；不可据此承诺剩余工作时长）：
下一条具体命令或代码入口 / 允许修改范围：
ready_for_sol 与各门禁证据：
```

## 待补的交接材料

## A3/A4 连续执行检查点（2026-09-27，浏览器主链已通过）

- 新增 `202609270044` 数据库不可变历史保护；发布版本与兼容 Prompt 快照禁止篡改/删除，SQLite 原生写入负例通过。PostgreSQL DDL 尚未执行验证。
- 反馈转 Skill 用例校验项目、实际运行 Skill FK 和完整输入哈希，唯一 source_feedback_id 保证幂等。人工评审改为状态 CAS，并记录项目审计；发布校验返回实际服务端门禁，不再固定返回未实现。
- A4 `lineage_adapter.py` 已接固定血缘版本、原始边/资产/脚本清单、有界路径及当前有效条款。模板不得丢掉四类输入，超预算明确阻断，检索或模型失败保留事实/缺口。未接入 Provider 明示缺口。
- 新增 `/ai-control/skills` 最小配置界面与 `SkillEvidenceLayers` 四层结果/反馈；旧 Prompt 页面区分 Legacy 与 Skill 快照。重试绕过当前缓存，显式重新生成可以读取新绑定。完整 B1 产品化仍未完成。
- 后端定向 23 passed（血缘/发布/旧行为）；后续控制面/发布/血缘/迁移 28 passed。新增界面读 API 后组合 57 passed / 9 failed：旧 runtime 夹具先设置 published_at、查询时 autoflush，再补指纹，触发不可变约束。修正夹具先计算指纹后发布，runtime 10 passed（4.58s）；没有降低产品约束。
- 制度有效性新增七种参数用例：完整有效条款、过期/撤回/停用/技术材料/缺条款定位/跨项目，另有检索故障保留事实。定向血缘 11 passed（7.98s）。截图复查发现检索服务内部 commit 与 savepoint 冲突，新增默认兼容的 `commit=False` 参数由 Skill 管理事务；血缘+知识回归 32 passed（16.14s）。
- 前端已有全套 `node --test tests/*.test.mjs` 156 passed（44.72s），`tsc --noEmit --incremental false` 通过；隔离生产构建通过（已有其他页面 Hook 警告）。后续上下文缺口标签/Skill 测试超时定向 9 passed。
- 第一轮浏览器已通过：真实 HTTP + 真实权限服务 + 测试身份注入 + Mock 模型；草稿→固定用例→确定性/Mock→独立审批发布绑定→血缘四层→反馈转回归→恢复新草稿，零 pageerror。证据：`docs/ux/acceptance/ai-skill-browser-20260927/results.json` 及五张截图。未测试真实登录/真实模型，不冒充全量验收。修复检索事务后的最终浏览器复验正在进行。
- 浏览器首次脚本选择器未考虑 select 的可访问名称包含 options，修正后通过；初始构建目录需显式设置 NEXT_DIST_DIR。均为测试驱动问题，保留真实结果记录。
- 本轮只用临时 SQLite；测试服务端口 18427，仅 loopback，lifespan off。旧服务已中断，新服务 session 74941/PID 3904 正在用于复验；构建 session 40691 仍需回收结果。本轮两个临时目录 `ai-skill-browser-ciadqglb`、`ai-skill-browser-i79u901i` 清理命令被工具策略拒绝，保留于当前用户 Temp，未换方式绕过。
- 下一切片已开始：带事实/条款双侧引用、冲突理由及强制人工确认的 `SkillPolicyComparison`，运行与 Replay 共用验证；输出 schema 纳入发布依赖指纹。该新增切片尚需完成测试、类型/构建和浏览器复验，不能记为已验收。
- ready_for_sol=false；A4 扩展 Provider、A5/A6、PostgreSQL 与真实模型仍待完成；未提交、未推送、未部署。

API/Schema 和错误码；状态机与权限矩阵；范围绑定优先级；不可变版本和恢复策略；输入/输出及缺口样例；发布测试的哈希关联；旧 Prompt 兼容表；数据库迁移记录；最小浏览器验收脚本；真实模型未验证清单；B 阶段逐工作包代码入口。A0～A6 执行中逐步填充，不能在只有规划时标记交接完成。

## A4 收尾与 A5 共享契约检查点（2026-09-27）

- 本段覆盖前文仍标为运行中的 A4 状态：A0–A4、知识检索、旧血缘解释和执行元数据组合 **113 passed，5 warnings，118.55s**。最终隔离前端生产构建通过。最终浏览器 **7 checks passed，errors=[]**，证据保存在 `docs/ux/acceptance/ai-skill-browser-20260927/results.json`，包含四类辅助上下文启用、反馈与恢复新草稿。测试使用 Mock 和测试身份注入，真实模型/真实登录未验证。
- 已实现 `lineage_context.py`：固定语句与文件哈希、历史字段约束、历史质量聚合（不含明文采样）、父修订差异、截止修订时间的人工历史。缺失历史明确留缺口；不查询真实源数据、不自动采用建议。
- `SkillPolicyComparison` 采用事实/条款双侧引用、冲突理由和强制人工确认；执行及 Replay 同步校验，输出 Schema 纳入发布依赖指纹。上述组合测试和构建均覆盖该切片。
- A5 首个保护修复：每次纠错调用重新校验并记录实际 UTF-8 输入字节，超过预算阻断，不截断。定向 2 passed。
- A5 共享契约：新增 `services/requirement_candidate_contract.py`，后台任务复用同一输出模型与白名单校验；保留旧 import 入口及自我纠错测试接缝。引用 ID 必须是正整数，不接受布尔、字符串、浮点隐式转换。首轮共享契约/纠错/已有智能性基准组合 **29 passed，3.97s**。
- 后续切片已添加固定目标投影：要求 field_id 在固定 field_ids 内且恰有一个目标，section 在固定 sections 内；深复制保留人工正文与全部证据。错误任务在模型准备前返回 409。对应测试正在执行，结果后续补记。
- 上轮 A5 大组合测试句柄已失效，无法获取最终结果；不能计作通过。本轮重新执行双层 Mapping、场景人工事实/追踪、需求生成/采纳、快照及 Word 回归，尚待最终结果。
- A4 临时服务已停止，无持续浏览器服务；本轮测试未连接用户业务库。前端 tsconfig 中隔离构建自动添加的 types 路径已移除，保留构建产物。先前清理两个临时测试目录的命令被工具安全策略拒绝，目录保留，没有换方式绕过。
- 当前未完成：需求候选及四类 Mapping 的 Skill 原生结构输出适配、A5 全量验收、A6、PostgreSQL、真实模型。`ready_for_sol=false`，不得将共享契约提取等同于业务已切换到 Skill。

## A5 需求候选 Skill 接入检查点（2026-09-27）

- 已完成共享契约/固定目标复验：**37 passed，1 warning，6.94s**。首次新增目标检查时，已有智能性基准手工夹具缺少真实输入具备的 field_ids/sections，出现 1 failed / 36 passed；仅为夹具补这两个字段后通过，保留用户原有自我纠错实现。
- A5 原有保护基线最终收齐：双层 Mapping、场景人工事实/追踪、需求生成与人工采纳、草稿快照、Word 合计 **68 passed，1 warning，562.22s**。此基线在原生 Skill 接入前启动，不能替代接入后的定向回归。
- 新增 `ai_skills/requirement_context.py` 与 `requirement_adapter.py`：读取已授权且已固定的需求输入，字段/章节严格限定；制度条款独立于物理/脚本事实；固定任务/项目绑定，无绑定保留 Legacy，有绑定失败禁止静默 Legacy 回退。
- `runtime.RequirementOutput` 保留 RequirementCandidate 业务字段；新增输出键 requirement_candidate_v1，编译前检查任务匹配与固定目标；模型/Replay 复用同一引用校验，确定性测试含原生未知证据负例；输出 Schema、专用安全提示与评测版本参与依赖指纹。
- 候选记录实际 Skill/模型身份、引用、回归输入。调用仍处于现有 worker 的租约与调用后重新鉴权链路内，生成不自动采用、不改正式需求。失败输出被阻断且保留模型日志。
- 新增测试真实走控制面 API：确定性/Mock/Replay→独立审批发布→固定版本调用；业务 API 验证有效候选、越界输出、无绑定、模型配置漂移四分支。无真实外部模型调用。
- 接入后的候选契约/纠错/运行/发布/需求生成回归 **57 passed，16.69s**；需求/运行/发布/血缘/控制组合 **53 passed，20.63s**；需求四分支/人工采用/纠错/智能性基准 **22 passed，9.93s**。这几组存在重叠，不累加为唯一用例数。
- 前端创建需求 Skill 草稿默认选择原生候选输出与对应提示词；需求输入说明使用固定字段/章节/资料，不显示血缘路径选项。最终 `tsc --noEmit --incremental false` 通过；原生负例/发布/候选契约最终组合 **41 passed，1 warning，12.30s**。
- 发布依赖评测版本已升级；旧版本若依赖指纹不匹配，需要显式恢复新草稿、重新评测/审批，不能偷偷继续或切换模型。没有迁移或改写用户数据库中的版本。
- 设计与下一步入口：`docs/design/ai-skill-a5-business-contract.md`。四类 Mapping 尚未适配，需求前端浏览器与完整固定修订导出验收未完成；A6/真实模型/PostgreSQL 保留缺口，ready_for_sol=false。

- 本轮收尾：全部本轮测试/类型检查进程已结束；没有运行中的测试服务端口。未提交、未推送、未部署。临时目录清理受此前工具策略阻止，继续保留。主线程审查了需求 worker 的新增分支、共享契约、发布依赖和候选采纳边界，现有用户自我纠错与其他未提交改动保留。
- 下一切片具体入口：`services/mapping/source_to_mart_generator.py` 与 `services/mapping/context_adapters.py`；先定义物理/证据引用的原生输出校验，再扩展服务端注册映射与同一评测，保持生成后的短事务/人工锁。依次接入 mart_to_ybt、scenario_business、scenario_technical，避免并行改写耦合链路。

## A5 四类 Mapping 接入检查点（2026-09-28，扩大验证中）

- 四类 Mapping 均接入 `mapping_adapter.generate_mapping_if_bound`，仅替换模型调用边界；原有 Context 构建、readiness、调用后重新鉴权/行锁/快照比较/人工内容策略保持。
- `mapping_context.py` 保存授权固定投影、完整已选事实、物理来源白名单与人工快照。原生业务模型采用 forbid-extra，配置输出键为 mapping_candidate_v1；运行、Replay、确定性未知引用/未知物理来源负例共用校验。
- 服务端注册四种固定任务类型，不接受配置提供可执行代码/任意 Schema。原生输出 Schema、安全提示及评测版本进入依赖指纹，ModelCallLog 保存实际 Skill 身份及原生引用。
- Context 的监管定义/检索摘要不能直接成为有效制度条款：当前适配保留为参考事实并报告 missing_basis，所有存在缺口的输出降为 low，追加待核验问题。A6/B 阶段还需扩展受治理条款投影，不把这些参考当作制度确认。
- 首轮 11 passed / 2 failed 暴露场景 Context 旧引用编号对应多个不同来源。现保留全部来源为显式成员集合、版本内容哈希、最高密级，并标明歧义缺口；没有删除成员或放宽唯一引用约束。复验四类主链、发布评测及白名单 **13 passed，82.93s**。
- 新增四类各三项调用后保护测试：错误引用、并发人工编辑、权限撤销。并发写入正式内容可能先触发既有 FINAL_CONTENT_PRESENT 治理保护，测试接受此保护或快照冲突，不能限定必须走到后一层。
- 前端新建 Mapping 草稿自动选原生输出与提示词，显示固定业务输入说明；类型检查通过。
- 扩大导出/多脚本回归首次 26 passed / 2 failed：两个 Legacy 单元测试使用无真实 actor 的 SimpleNamespace 输入，现显式隔离 Skill 分支，仍测试原预算与脚本引用；真实身份/绑定行为由完整 API 测试覆盖。产品鉴权没有放宽。
- 跨轮测试句柄失效且已无对应进程，未取得最终摘要的两组不计通过。重新执行并将完整日志与 JUnit 写入 `docs/evaluation/ai-skill-a5-20260928/`（native、protection、exports），避免续做时丢失结果。三组当前运行中。
- 无生产库连接、真实模型调用或提交/推送/部署；ready_for_sol=false。接入实现完成不等于 A5 总体验收已全部通过。

## A5 收齐验证与 A6 首片（2026-09-28）

- `native.xml`：**56 passed，233.29s**，四类 Mapping 原生评测/发布/真实 Context 与 Mock、错误引用、调用期间并发编辑/撤权，连同需求原生输出、运行与发布回归。
- `protection.xml`：**52 passed，570.73s**，既有双层 Mapping 与场景人工事实/并发/调用链保护。`ambiguity.xml`：**1 passed，5.26s**，歧义引用全部成员和最高密级保留。
- `exports.xml`：27 passed / 1 failed，失败仍是 Legacy 自我纠错夹具缺少任务 item.id；补齐合成任务 ID 后 `exports-repair.xml` **1 passed，6.28s**。因此该组 28 个用例均有通过证据，保留初始失败记录，不把原 XML 改成全绿。包括 Word/Excel 同一固定修订与多脚本/多目标隔离。
- 前端类型检查已通过；没有为本次原生业务 UI 单独声称完整浏览器验收。此前 A4 真实 HTTP/Mock 浏览器证据继续有效，但不是 A5 新页面的验收替代。
- A6 新增 `ai_skill_ranking.py`、`ai_skills/field_candidates.py` 及两个只读 API；严格目录项目/启用/关联白名单，固定哈希绑定 actor/项目/目标/来源版本，重排必须完整排列现有候选。重排验证前重新鉴权和召回，禁止自动写推荐或正式映射，禁止连接真实数据源，禁止返回连接凭据。
- 字段候选初轮 9 passed / 1 failed 是 Legacy 身份应返回 401 而非测试写的 403；修正期望并补分值/跨用户回放负例后 `field-candidates-final.xml` **17 passed，5.74s**。目前为确定性召回与重排建议验证，无真实 Embedding/重排模型效果声明。
- `HybridRetriever` 增加目标字段/场景的项目归属核验，发生于 token 化/Embedding/向量服务之前；保留既有检索与用户修改。`retrieval-scope.xml` **36 passed，18.74s**，含四个越界/不存在负例、知识与血缘回归。
- 日志和 JUnit 均在 `docs/evaluation/ai-skill-a5-20260928/`；各组合有重叠，不相加当作唯一用例总数。剩余 A6 约束见 `docs/design/ai-skill-a6-extension-contract.md`。
- 所有本轮测试进程已结束，无测试服务监听；无提交/推送/部署。此前被工具安全策略拒绝清理的临时目录保持原样。ready_for_sol=false，真实模型和 PostgreSQL 仍未验证。

## A6 收尾并继续 B1（2026-09-29）

- 需求复核真实双连接并发/过期 ORM/回滚及旧 API 11 passed，证据 recheck-final.*。首轮 10 passed/1 failed 揭示 start_workflow 内部 commit；新增默认兼容的 commit=False 组合模式并由 API 最终提交，修复回滚。
- 脚本事件锁父记录，新增/删除 NULL 版本对和普通变更重复只生成一个事件、一份影响和三条审核任务；版本越界拒绝、不同内容重放冲突。首轮新增夹具漏 StoredFile 外键 5 errors/现有 SQL 血缘 31 passed，补齐 FK 后事件与缓存合计 21 passed。
- cache_contract 以真实服务端血缘构建和成功 ModelCallLog 作为来源。命中先重新鉴权和条款效力验证，绑定/模型/密级/权限/输入变化失效；命中保留原执行来源，未启用业务结果缓存。
- 纯合成固定评测 JSON 实际由测试读取，中英文召回和有依据答案/冲突/非法引用共 12 passed。治理/血缘不可变修订回归 40 passed。全部日志/JUnit 在 docs/evaluation/ai-skill-a5-20260928/，失败原始证据保留。
- 主线程核对改动 diff、默认工作流兼容性及 ingestion/jobs 最终事务，git diff --check 通过。无子代理（当前权限不满足用户对子代理的沙箱约束）；无实际模型身份声明。
- 用户明确取消模型交接，要求当前线程持续做后续。A6 核心参考实现完成后直接开始 B1；真实模型/重排质量、PostgreSQL 及完整 B 阶段仍未验收。不提交、不推送、不部署。

## B1 首轮验收与 B2 需求来源（2026-09-29）

- B1 增加服务端 /ai-skills/capabilities 与版本创建/编辑人信息，页面按权限和独立审批约束启用按钮；新增变量光标插入、未保存修改保护、可读发布/测试摘要与双栏版本差异。
- 权限/控制/发布组合 28 passed（b1-capabilities.*）；TypeScript 通过，隔离生产构建通过（b1-frontend-build-final.log）。
- 真实 HTTP + 真实权限 + 测试身份注入 + Mock 浏览器 10 checks passed、errors=[]，证据 docs/ux/acceptance/ai-skill-b1-browser-20260929-verified/results.json。主线程查看差异截图，布局正常。首次验收构建漏 NEXT_PUBLIC_API_BASE_URL 导致连接默认端口；第二次测试 textarea 精确标签选择器未匹配，改用实际 textbox 可访问名称前缀后通过。两份失败目录保留。
- B2 首片：需求候选详情只返回白名单执行来源字段，不返回完整 Prompt/回归输入；页面区分 Skill 固定版本与 Legacy、Mock 与真实执行，显示已有固定脚本引用。需求原生/采用回归 10 passed（b2-provenance-final.*）；类型检查通过。首次命令写错不存在的测试文件导致未执行，保留 b2-provenance.*，后续正确组合通过。B2 UI 尚未单独浏览器验收。
- B1 测试服务端口 18427 已停止，构建及测试已结束。构建自动新增 tsconfig 的隔离 types 路径待最终收尾移除。未提交/推送/部署。
- 下一项：Mapping 四类草稿的持久运行来源读取与页面展示；必须精确按项目、映射类型和映射 ID 查审计，不能用项目最新模型日志冒充该候选来源。旧记录未保存输出关联哈希时需明确“历史记录，当前草稿未核验”，不伪装为当前来源。B1 仍有完整多范围绑定/注册/人工评审产品化待续做，不能标记整个 B1 完成。

## B2 四类 Mapping 来源继续记录（2026-09-29）

- 四类生成器在现有成功审计中保存 AI 草稿正文哈希，不新增数据库字段、不改生成后人工保护。新增 /mappings/{type}/{id}/generation-provenance，按精确项目/类型/对象/成功动作读取来源；Skill 来源还需关联真实成功 ModelCallLog。
- 明确区分 current_text、text_changed、historical_unverified、unavailable；旧记录缺关联哈希不猜测当前来源。响应仅白名单元数据，不返 Prompt/完整输入/凭据。页面还对显示正文与服务端哈希进行比对，防止并发变更后错误标记一致。
- 四类真实 Context+固定 Mock 生成后，通过实际 HTTP 验证来源、正文变化、历史缺哈希和 Legacy 拒绝，4 passed（b2-mapping-provenance.*，其余 28 deselected，未计为通过）；额外来源隔离/缺日志关联与需求组合 8 passed（b2-provenance-isolation.*）。
- 场景业务/技术页面及实时字段编辑器新增来源展示；需求独立修订编辑器不读取最新 Mapping 记录冒充固定历史。已确认 DocumentPreview 的独立修订分支使用 RequirementContentEditor。类型检查通过；最后增加显示正文哈希核对后待再检查。
- B2 原生候选与 Mapping 页面还需独立浏览器验收；B1 的 10 项浏览器检查不替代 B2。无测试服务运行。下一步完善 B2 浏览器夹具与验收，再继续 B1 多范围绑定/人工评审和 B3；按用户要求不安排模型交接。

## B2 浏览器完成与 B1 人工评审继续（2026-09-29）

- B2 隔离临时 SQLite、真实 HTTP、测试身份注入与 Mock 浏览器 7 checks passed，errors=[]：需求 Skill 测试/独立发布，页面生成不改正文，来源明确为 Skill+Mock，人工采用创建待审核 v2、v1 保持不变，两类场景 Mapping 正文关联哈希一致，后续修改撤销一致标识。证据 docs/ux/acceptance/ai-skill-b2-browser-20260929-verified/results.json；初次五项及扩展六项记录保留。主线程已查看需求候选与 Mapping 截图。
- B1 新增独立人工评审意见及通过/不通过操作；发起人不可自审，待评审结果不再误标失败。服务端返回 run.created_by 支持权限展示，后端仍执行独立身份及一次性状态更新检查。权限/发布组合 15 passed（b1-review.*），隔离构建通过，B1 浏览器增加评审流程后 11 checks passed，errors=[]（ai-skill-b1-review-browser-20260929），主线程查看评审截图。
- 检查发布代码发现兼容 Prompt 快照固定使用通用 grounded schema，已改为按真实任务保存需求/Mapping 原生 schema；五类发布路径 5 passed/27 deselected（b2-native-snapshot.*）。不修改已发布历史快照。
- 已完成上述进度记录后继续固定版本采用页面与可选版本接口；保持当前线程执行，不安排模型交接。真实模型、PostgreSQL、完整 B1/B2 及 B3–B6 尚未全部验收。

## B1 固定采用闭环（2026-09-29）

- 新增 binding-options，只列出同一能力在可兼容平台/机构/项目/任务范围内的已发布版本元数据，不暴露上级草稿或完整提示词；模型停用或依赖变化标为不可采用。采用仍调用原有独立权限、依赖重验与绑定 CAS 服务。
- 页面新增固定采用、当前绑定提示与配置哈希；需机构审批权限，未保存编辑期间禁止切换绑定，上级更新不自动生效。
- 初轮 b1-binding.* 1 passed/1 failed：测试错误假设缺机构权限返回 403，既有鉴权为防泄露返回 404；修正测试期望后与发布回归合计 13 passed（b1-binding-final.*），未放宽产品权限。
- 隔离生产构建通过（b1-binding-build.log）；B1 浏览器完整 12 checks passed、errors=[]，含独立人工评审、发布 v2 后明确重新绑定 v1 且两个已发布版本均不修改。证据 docs/ux/acceptance/ai-skill-b1-binding-browser-20260929/results.json；主线程已查看固定绑定截图。
- 最终 TypeScript 检查通过（b1-b2-final-types.log）；移除本轮隔离构建添加的 tsconfig types 路径，保留原有开发路径。临时 HTTP 测试服务已停止，无持续测试进程。
- B1 仍待完整平台/机构/任务范围编辑及多能力注册；B2 仍待制度、固定版本文档辅助及全部业务页面覆盖；B3–B6 未完成。后续按上述顺序继续，不需要模型交接。未提交、推送或部署。

## B1 多范围配置与能力注册（2026-09-29）

- 配置页支持平台、机构、项目、任务四种精确范围；配置所属范围与测试项目分离，平台/机构版本继续使用所选项目固定用例。任务标识校验格式并提示与业务入口及用例一致；未保存编辑或进行中操作锁定页内范围切换。
- 平台管理员可注册服务端白名单内的多种能力，已注册项不可重复选择；需求及 Mapping 使用原生输出，其他任务使用对应任务提示词。注册记录不等于相关业务适配已全部完成。
- 无权限范围显示服务端错误，返回项目后重新加载；测试保存/运行按钮补充编辑权限限制。未放宽后端权限。
- 后端控制/能力权限/绑定回归 19 passed（b1-scopes.*）；最终隔离构建通过（b1-scopes-build-final.log）。浏览器真实 HTTP + 隔离 SQLite + Mock 16 checks passed、errors=[]，证据 docs/ux/acceptance/ai-skill-b1-scopes-browser-20260929-accepted/results.json。覆盖三种新增范围精确坐标、未保存切换保护、第二种能力注册、越权拒绝和项目恢复，保留原 12 项流程。主线程查看注册截图。
- 三次未通过浏览器记录保留：同名 region/select 选择器、过严提示词正则、未等待 React 禁用状态更新。分别修正选择器、匹配文本和状态等待后复验通过，没有放宽业务断言。
- 已移除隔离构建自动加入的 tsconfig types 路径，临时测试服务停止；未提交/推送/部署。全局项目导航的未保存保护及更完整的任务评测体验仍待补强，不能把本次入口补齐等同第二部分全部完成。
- 下一步继续 B2 制度与固定版本文档辅助接入，再推进 B3；实际模型质量和 PostgreSQL 仍单独列为未验收。

## B2 制度对照来源与人工结论保护（2026-09-29）

- 核对既有制度对照链路：候选来自固定需求生成输入，人工判断保存在不可变需求修订，缺失制度、过期条款和冲突仍阻断确认/送审。本轮复用该链路，不另建可覆盖人工结论的生成入口。
- 修复 ai_suggestions 直接返回完整执行元数据的问题，复用 safe_execution_metadata 白名单，只提供实际执行类型、模型、Skill 固定版本、运行及输入哈希。完整 Prompt、回归输入和配置不进入对照响应。
- 制度对照页面接入统一 SkillRunProvenance，区分 Legacy/Skill、Mock/真实执行，并将候选状态显示为中文；仍由独立人工表单填写判断，不自动采用模型结论。
- 扩展真实 API 回归为 Legacy 与绑定 Skill 两条路径：模型建议匹配时，已有人工冲突保持不变；历史版本不出现后来候选；完整性哈希继续校验；注入 Prompt/完整回归输入/配置后确认不会暴露。Skill 路径通过运行服务生成合成候选并返回持久运行编号，未使用真实模型。
- 初步组合 19 passed（b2-policy-provenance.*），扩展原生 Skill 后组合 20 passed（b2-policy-native.*）；类型检查通过（b2-policy-types.log），隔离构建通过（b2-policy-build.log）。本轮不声明制度对照 UI 已完成单独浏览器验收。
- 清除构建自动增加的隔离 tsconfig 路径；无测试服务运行，无提交/推送/部署。下一项为制度对照浏览器验收与固定版本背景/业务说明/差异分析/缺失信息辅助，后者尚未实现，现有字段候选不能算作完整 P2-3。

## B2 制度浏览器与固定版本文档辅助首版（2026-09-29）

- 制度对照浏览器先完成 5 项：固定条款/脚本、人工冲突保存为新修订、Skill 合成匹配建议不覆盖人工冲突、历史视图不混入后续候选、实际来源可见。证据 ai-skill-policy-browser-20260929。
- 随后继续实现固定文档辅助：新增 requirement_document_assistance / document_assistance_v1，四类逐段事实引用候选，接入共享编译、原生校验、确定性/Mock/Replay 评测、发布快照及运行日志；注册页面可选择该任务，工作台提供固定修订辅助面板。
- API 只读明确修订并检查哈希、权限和固定制度效力，调用后重验权限/依据/绑定锁。无绑定报错，不隐式走 Legacy；未知引用降级，候选不写回任何需求版本。完整历史修订首版仅支持 local_only 配置，外发需要后续逐来源授权投影。
- 后端文档/需求/发布组合 22 passed（b2-document.*）；增加本地限制 6 passed（b2-document-local.*）；增加失效依据 7 passed（b2-document-final.*）；补齐段落引用写入日志后文档/共享运行回归 21 passed（b2-document-citations.*）。各组重叠，不相加当唯一用例数。
- 文档+制度联合真实 HTTP、隔离 SQLite、合成 Mock 浏览器 7 checks passed、errors=[]，证据 docs/ux/acceptance/ai-skill-document-browser-20260929/results.json。配置通过真实测试和独立审批后，页面生成带修订事实引用的背景候选；现有冲突和修订 v2/v3 完整不变。主线程查看了截图。合成模型用于流程验证，未声称真实模型生成质量。
- 隔离构建通过（b2-document-build.log），最终 TypeScript 检查通过（b2-document-types-final.log），git diff --check 通过。构建自动增加的 tsconfig 路径已移除，临时 HTTP 服务和测试进程均结束。未提交/推送/部署。
- 冻结接口、边界和限制见 docs/design/ai-skill-b2-document-assistance.md。Word/Excel 继续只读取既有固定修订；本轮没有自动将文档候选合入正式导出。下一步核对 B2 尚未覆盖的业务入口并推进 B3，不把新增白名单能力注册当作其全部业务集成完成。

## B3 字段候选页面首版（2026-09-29）

- 字段场景页接入只读目录召回：补充检索词、限定本项目数据源、候选数量、词面分数/依据、目录出处与版本、上下文快照及服务端复核。修改输入、请求失败或切换场景清除旧候选；不连接源库、不写推荐/映射、不跳过现有选择与安全探查。
- 当前为确定性词面召回，不标记成真实模型语义重排；后续继续查询改写/跨语言评测和正式采用链路整合。
- 验证：`b3-fields.xml` 17 passed；`b3-fields-build.log` 生产构建通过；`docs/ux/acceptance/ai-skill-field-candidates-browser-20260929/results.json` 5 项真实 HTTP 浏览器检查通过，errors 为空；含目录出处/快照复核、输入失效、范围拒绝、重试恢复及映射前后不变。
- 下一进度：核验已有需求影响清单和复核任务页面，补齐端到端“历史版本不变、人工明确建立新修订”的证据。

## B3 影响复核及跨语言边界（2026-09-29）

- 持续推进下一检查点：复用已有影响清单与需求复核组件，新增隔离浏览器场景，从 `/work` 创建复核待办，再进入需求工作台明确创建 v5。v4 固定文档前后完全相同；重复事件复用相同任务；未重新核验的 v5 关联被 409 拒绝，复核保持 pending。
- 证据：`docs/ux/acceptance/ai-skill-recheck-browser-20260929/results.json` 4 项通过、errors 为空；`b3-recheck.xml` 8 passed。此轮未实现新的自动影响解释模型，未自动关闭复核。
- 修复已有跨语言词面扩展的英文子串误命中：forecast 不再扩展 EAST，imbalance 不再扩展 balance，subcontractor 不再扩展 contract，110400 不再扩展 1104。保留 BALANCE_AMT、DUE_BILL 等标识符边界匹配和中文词组召回；关键词打分采用同一边界；同义词顺序固定，避免进程集合遍历顺序引起不稳定。
- `b3-retrieval-boundaries.xml` 45 passed，覆盖新增 10 项边界用例、既有范围隔离、知识 RAG 与合成智能评测。保留原有领域词典内容，未将相关词等同于制度事实；没有重建用户现有索引，没有调用外部模型或执行源库查询。既有关键词索引如需完全移除历史扩展项，应按正式索引维护流程重建。
- 本轮共三个检查点；核心目录召回 17、复核 8、检索回归 45 分组报告，非整个项目全量测试。前端构建和最终类型检查通过（保留既有 lint warnings），两套浏览器检查共 9 项通过；隔离 HTTP 服务已结束。
- B3 仍为 in_progress：未完成查询多轮分解、真实模型重排、候选正式采用链路整合及业务专家质量验收；第二部分完整验收仍为 false。

## B3 有界分句检索与排名样例（2026-09-29）

- 新增真实身份授权的 planned-search API 与知识检索页可选入口：原问题 + 至多三个显式分句，固定关键词/当前生效范围。超过预算保留完整查询，带引号的表达式不拆分；不调用语言模型或 Embedding。
- 结果保留真实引用、内容/版本哈希，按权威等级及 reciprocal-rank fusion 合并，同分稳定排序；显示检索计划和每条证据的命中轮次。项目、查询和模式变化清理旧结果，空检索不生成回答。
- 返回前重验授权、当前资料效力和固定内容；跨轮变更或失效拒绝返回。子日志与汇总日志同事务，失败不留下部分成功日志。既有单轮默认入口保留。
- 详细契约：`docs/design/ai-skill-b3-planned-retrieval.md`。
- 验证：初轮 31 passed；补资料失效保护后 53 passed；最终固定样例组合 `b3-planned-golden-final.xml` 58 passed，含 5 个合成排名对比，不将前后轮次累加。两个样例召回改善，其余保留权威顺序/稳定同分/空证据行为。
- `b3-planned-build.log` 生产构建通过；`docs/ux/acceptance/ai-skill-planned-search-browser-20260929/results.json` 5 项真实 HTTP 浏览器检查通过，errors 为空；已检查截图。隔离 HTTP 服务已停止。
- 限制：显式分句与确定性名次合并不能替代模型查询改写、依赖式多跳、模型语义重排或业务质量验收；B3/第二部分仍未完成。

## B3 字段候选进入人工采用链路（2026-09-29）

- 新增 prepare API 与“加入来源候选”按钮，复验真实用户、项目/场景、召回快照和候选白名单，重复加入复用记录；加入本身不创建或改写技术映射。通过审计保存目录版本哈希，后续选择、实际探查、采用都会拒绝已变更/失效的新流程候选。
- 接通已有选择→安全探查→人工采用，并补服务端探查门禁：必须匹配同推荐/项目/字段/场景/数据源/列的最新成功或有效部分成功任务及统计快照。不能仅凭前端按钮或 profile_status 采用。选择新候选会清除页面旧探查状态；选择失败显示错误。
- 真实角色验收发现并修复通用守卫误分类：场景映射读取原先错误要求编辑权限，列探查被提前归为目录管理，POST 分句/混合检索被归为知识管理。现按实际读取/检索/探查权限处理；上传和写入权限保持独立，未给项目经理扩充 profile.request。
- 后端首轮 34 passed；最终组合 `b3-preparation-final.xml` 58 passed，含 5 条既有 JUnit 属性格式警告；不将测试轮次累加。`b3-preparation-build-final.log` 构建通过，`b3-preparation-types-final.log` 类型检查通过，diff check 通过。
- 浏览器最终证据：`docs/ux/acceptance/ai-skill-candidate-preparation-browser-20260929-final/results.json`，4 项通过、errors 为空。技术分析员实际通过安全执行器读取临时 SQLite 合成源库（3 行），人工采用后 API 和页面均显示 balance，技术状态仍为 draft、加工规则待确认。没有访问用户数据源或生产库，没有外部模型调用。
- 初轮项目经理无 profile.request、随后技术角色被错误守卫拦截的失败证据保留；修复后重新验收通过。一次测试服务尚未监听时的连接拒绝也保留，服务就绪后重试通过。隔离服务已结束。
- 设计：`docs/design/ai-skill-b3-candidate-adoption.md`。旧目录推荐增加探查门禁但不追溯伪造目录快照；新固定版本保护适用于 bounded_catalog_recall。B3 及第二部分完整验收仍未完成。

## B2 跨层核验与过期候选采用保护（2026-09-30）

- 源到集市、集市到一表通核验页已接入实际 GET/生成/采用 API；显示候选正文、固定 Skill/模型执行来源与人工最终内容，采用后仍为 draft。
- 工作台当前视图提供入口；历史固定需求不显示实时入口，字段未保存时先阻止此导航。
- 采用端显式 technical.edit 权限、映射锁后重读、人工内容/审核状态保护。新增严格 expected_draft_hash 契约，缺失或正文不一致拒绝；页面收到专用错误码后清空失效内容与确认，重新读取后才可确认。
- 新核验页不提供自由编辑；不将本次采用保护当作所有旧 PUT 编辑路径已完成治理。
- 验证：`b2-cross-layer-confirmation-final.xml` 17 passed（含既有端到端与四类原生 Mapping 回归），错误码修订后 `b2-cross-layer-errors-final.xml` 12 passed；证据组不累加为唯一用例。
- 浏览器：`docs/ux/acceptance/ai-skill-cross-layer-browser-20260930-final/results.json` 六项通过、errors=[]；覆盖两类固定发布 Mock 生成、过期页面采用拒绝、重新读取后明确采用、人工内容不可重复覆盖。
- 构建：`b2-cross-layer-confirmation-build-final.log` 成功；保留现有 Hook lint warnings。构建临时 tsconfig include 已移除。
- 初轮失败为测试夹具缺 created_by，随后启用外键约束后修正为用户 ID；旧端到端允许覆盖人工内容的断言改为验证 409 且内容不变。浏览器初轮发现全局错误文案掩盖具体原因，已用专用错误码和页面本地文案修复并重跑通过。
- 未进行真实模型、PostgreSQL 或生产验收；未提交、推送或部署。设计见 `docs/design/ai-skill-b2-cross-layer-adoption.md`。

## B3 字段候选跨语言召回（2026-09-30）

- 在 B2 记录完成后继续实施：新增六类有界字段概念匹配，改善中文目标到英文目录字段、英文目标到中文字段的候选排序；说明中保留人工核验边界。
- 修正词面精确匹配边界，balance_amt 能命中 balance，而 imbalance 不再得到完整匹配分；近似候选仍可能保留，不能把匹配分解释为业务置信度。
- 召回与词汇版本纳入快照，词汇版本变化后拒绝旧提案；不新增模型调用、数据库连接或自动采用。
- 证据：`b3-field-vocabulary-final.xml` 58 passed，覆盖七个固定跨语言样例及既有候选/准备链路；`b3-field-vocabulary-types.log` 类型检查通过。B2 最终生产构建之后只改了本组件的分数标签，未将旧构建冒充新功能构建证据。
- 设计：`docs/design/ai-skill-b3-field-vocabulary.md`。下一工作包仍是受控模型查询改写/依赖式多跳及候选模型重排，不把本地规则包装为模型能力。

## B3-R1 受控候选模型重排（2026-09-30）

- 新增显式端点 `POST /ai-skills/field-candidates/model-rerank`：仅在用户点击后，对当前**已有界**字段候选调用固定发布的 `field_semantic_matching` Skill；请求体不含 skill_key，无有效固定绑定时 409 `skill_binding_required`，不回落 Legacy 或确定性伪成功。
- 调用前后各重新鉴权并重建召回快照：调用前 `context_hash` 不一致即 409 且零模型调用；调用后复核发现快照变化则丢弃模型排序并如实标注 `candidate_snapshot_changed_after_call`。
- 输出强 schema `field_ranking_v1`：ID 集合必须与白名单完全相等（缺/重/陌生 ID 拒绝）、分数严格 0–1 有限、`evidence_refs` 必须属于白名单；模型输出非法或 Provider 失败一律降级为**确定性召回**，`execution_metadata.execution_kind="deterministic"`，绝不把确定性排序标成模型成功。
- 不外发：envelope 只带目录元数据（无连接串/主机/账号/密钥/源库数据行），密级下限取 `max(项目密级, confidential)`，因此非 local_only 云模型在调用前即被既有 `ensure_external_allowed` 拒绝（409 `external_model_data_denied`）。Mock 与 local_only 为当前可用路径。
- 前端 `FieldCandidateRecall` 新增“模型重排（显式请求）”按钮、执行类别（真实模型/Mock/确定性/降级）中文标签、固定 Skill 版本/作用域/运行编号/模型名与失败原因；输入、项目、场景变化即废弃旧响应（请求序号 + 属性变化重置），不自动调用、不自动选择、不写映射。
- 契约变更（已列于设计文档供复核）：`SkillContent.output_schema_key` 新增 `field_ranking_v1`；`schemas/ai_skill_ranking.py` 新增 `RankedCandidate`/`FieldRankingCandidate`/`FieldRerankRequest` 与 `validate_field_ranking`；`runtime.py` 新增 `FIELD_RERANK_TASK`/`FieldRerankOutput` 与四个分支；`evaluation.mandatory_assertions` 增加本任务 native 未知引用与伪造证据负例探测；Mock 增加合成排序分支（仅流程验证）。
- 定向验证：`b3r1-field-rerank.xml` **22 passed**（Mock 正常路径、非法输出五类、Provider 失败、调用后快照变化、无绑定、停用/漂移绑定、六类快照与权限门禁、预算、云模型外发拒绝、schema 负例）；既有 `test_ai_skill_control/releases/runtime/field_candidates/candidate_preparation/field_candidate_vocabulary` 组合 **86 passed**（证明既有任务依赖哈希未漂移）。前端 `tsc --noEmit` 通过，`node --test` 156 passed。
- 浏览器（真实 HTTP + 隔离 SQLite + Mock，仅 loopback）：`docs/ux/acceptance/ai-skill-field-rerank-browser-20260930/results.json` 四项通过、errors=[]；覆盖“未点击不产生模型调用”“显式点击后才重排并显示固定 Skill 与 Mock 标签”“模型重排不写映射/推荐”“修改检索词废弃旧模型排序”。截图 `field-rerank.png` 已由主线程查看。
- 未验证：真实模型重排质量与成本、PostgreSQL、业务专家质量评测；Mock 通过只证明流程与门禁。B3 仍为 in_progress，第二部分完整验收仍为 false。
- 设计：`docs/design/ai-skill-b3-model-rerank.md`；工作包报告 `docs/handoff/dsh-B3-R1-result.md`。下一工作包为受控模型查询改写/依赖式多跳与条款比较，随后 B4/B5/B6。

## PostgreSQL 数据恢复与天津演示重建检查点（2026-09-30）

- 代码包未回退：`scripts/项目启停.ps1` SHA256 与源机一致（`C0272418…F604`）；第 149 行 `MissingCatchOrFinally` 已定位为本机代码页差异（ACP=gb2312 读取无 BOM 的 UTF-8 文件），同一字节流按 UTF-8 解析 **0 错误** → 非代码缺陷，文件未被修改。
- 数据包 `dsh-postgres-data-20260930-v2` 的 SHA256SUMS **19/19 通过**；在本机便携 PostgreSQL **18.4**（仅 127.0.0.1:5432，locale Chinese (Simplified)_China.936）恢复为**全新库 `ybt_dsh_handoff_v2`**，迁移 `202609180039` → **`202609270044`**，**6 个项目 / 25 源用户 + 1 交接管理员**；第一次尝试的库 `ybt_dsh_handoff_20260930` 作为失败现场保留未删。
- 执行方式透明：使用「加 UTF-8 BOM + 修正 1 行 UPDATE 结果校验（psql 命令标签导致误判）」的脚本副本；原脚本逐字节未改（SHA256 `4615F0AA…4D31`）。孤儿引用修复有审计 `restore-audit.csv`。
- 文件预览实测：`stored_files` 24 行中 **4 行对象存在（HTTP 200）**、20 行缺失（404）；磁盘另有 5 个无数据库行的对象 → 预览功能正常，属交接包数据完整性差异。
- 组件拓扑（分开判定）：**Redis + Celery Worker + Beat + 真实 FastEmbed Embedding 已实测通过**（`/health/ready` 的 redis/task_queue/embedding_provider = healthy；`POST /v1/embeddings` 返回 512 维；真实异步任务 `job 116` queued→completed）。**Milvus/etcd/MinIO 未恢复**（本机无 Docker、WSL 无发行版、进程未提权），故 `vector_store=disabled`、`semantic_index=disabled` → **完整组件拓扑未通过**。
- 天津农商演示重建：项目 **ID 7**、批次 **ID 1**、数据架构 revision **2**、后台任务 **116**；落库 **18 张目录表**（14 ODS→layer_1、4 监管集市→layer_4）、**4 个固定脚本版本**（`version_no=1`、`parse_status=parsed`、`dialect=hive`）、**64 条跨 ODS→监管集市列级血缘边**（另 `reads_from` 15、`maps_code` 13）。
- 记录在案的差异：源库项目 2 名称本来就是 12 个 `?`；上传时 ZIP 中文文件名在 multipart 丢 `.zip` 后缀（改用内容哈希一致的 ASCII 名副本）；PS 5.1 `Invoke-RestMethod` 未按 UTF-8 发送请求体导致中文写成 `?`（已用 UTF-8 字节体与定向 SQL 修复，并据此解释源库现象）。
- 仍未验证：Milvus/向量检索、真实模型质量、服务器全库（项目 28 / 批次 17 / revision 10 未迁入）、PostgreSQL 生产形态。第二部分完整验收仍为 **false**。
- 报告：`docs/handoff/dsh-pg-restore-and-tianjin-acceptance-20260930.md`。