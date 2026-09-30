# A5 业务候选接入契约

更新：2026-09-27。本文约束后续实现；仅“已实现”表中的内容可以计作完成。`ready_for_sol=false`。

## 已实现

| 边界 | 代码 | 验证 |
| --- | --- | --- |
| 需求候选统一输出模型与引用白名单 | `backend/app/services/requirement_candidate_contract.py` | 物理字段三元组、证据 ID、脚本规则 ID、制度来源分类、冲突说明负例 |
| 固定目标投影 | 同文件 `project_candidate_context` | 字段缺失/重复/越界、章节越界阻断；保留人工正文、全部证据且不修改原快照 |
| 后台任务复用契约 | `requirement_generation_worker.py` | 保留租约 fencing、调用后重新鉴权、候选独立保存与显式采纳链路 |
| 纠错输入预算 | 同文件 `generate_candidate` | 每次实际输入重新计算字节并阻断超限；不沿用第一次字节数 |

共享契约与纠错、现有智能性基准及真实 Mock 候选 API 合计 37 passed。Mock 生成后正式需求不变。该结果不代表 Skill 适配已完成。

## 输出契约选择

需求候选和 Mapping 必须保留业务原生结构。不得把现有 `GroundedOutput` 的自由文本 claims 拼接为正式业务字段，也不得只修改执行日志标签就宣称已接入 Skill。

后续注册表采用服务端固定的 task_key → 结构模型与校验器映射，不接受配置中的模块路径、Python 表达式或任意 JSON Schema。注册项应同时用于实际运行、Mock、Replay、确定性负例和发布依赖指纹。

| task_key | 业务模型 | 调用后仍需保留的检查 |
| --- | --- | --- |
| requirement_candidate_generation | `RequirementCandidate` | 固定物理字段/证据/脚本白名单；租约；当前权限；只保存候选 |
| scenario_business_mapping | `ScenarioBusinessOutput` | 不可变 Context 投影；业务人工事实保护；当前草稿及快照一致性 |
| scenario_technical_lineage | `ScenarioTechnicalOutput` | 物理字段白名单；技术人工事实保护；当前草稿及快照一致性 |
| source_to_mart_mapping | `SourceToMartOutput` | 双层 Mapping 可编辑状态；调用后短事务重鉴权/行锁/快照比较 |
| mart_to_ybt_mapping | `MartToYbtOutput` | 同上；目标与来源必须保持项目范围 |

原生业务模型放在明确的候选字段中，与事实、制度依据、缺口及执行元数据并列。候选模型不得包含 adopted、confirmed_by 或人工确认状态。业务入口在输出校验失败时拒绝写入候选/草稿，保存失败调用证据，不自动回退为另一个模型或最新版本。

## 输入与权限

1. 入口先恢复真实 actor，并执行现有业务权限和输入完整性检查，再解析任务/项目固定 Skill 绑定。
2. 没有绑定才走原 Legacy；存在但不可用的绑定必须报错，不静默忽略。
3. 需求输入使用既有已授权 `RequirementGenerationInput` 固定快照。只选当前字段和章节，不重新查询最新资料替换快照。
4. Mapping 使用已有 `GenerationContextEnvelope` 及其不可变 projection。不得绕过 readiness、密级、截断检查或扩大证据范围。
5. 制度条款与物理/脚本事实分层；技术材料不能升级成制度依据。完整来源、版本、定位与密级进入输入哈希。
6. 调用后继续既有重新鉴权、状态锁、快照比较、人工内容保护。模型返回后持有的 ORM 值不能替代短事务内重新加载的权威状态。

## 实施顺序和通过标准

1. 原生输出注册表及共享校验：发布依赖指纹覆盖 Schema 和校验器版本；增加任务与输出类型不匹配负例。
2. 需求候选适配：固定版本和元数据贯穿日志/候选；无绑定 Legacy、有效绑定 Skill、失效绑定拒绝三路测试。真实 Mock 生成后正式需求完全不变。
3. 逐项接入四类 Mapping：保留原处理输出逻辑，每项覆盖人工内容不覆盖、调用期间撤权/状态变更/快照变更、越界物理引用拒绝。
4. 对固定修订导出做 Word/Excel 一致性验收；真实模型单独列状态，不能用 Mock 成功替代。

第 1～2 项的需求候选分支现已实现：`runtime.RequirementOutput`、`requirement_context.py`、`requirement_adapter.py`，输出键为 `requirement_candidate_v1`。编译前检查任务与输出键一致、固定目标有效；运行、Mock、Replay 共用共享白名单校验；确定性评测包含原生未知证据 ID 负例。需求专用安全提示、输出 Schema 和校验器版本纳入发布依赖指纹。

真实 API/隔离 SQLite 验证覆盖独立审批发布、固定版本调用、无绑定 Legacy、非法引用阻断、模型配置漂移阻断，以及候选不改变正式需求。候选保存执行身份、完整回归输入和引用，现有租约/调用后鉴权/人工采纳不变。

四类 Mapping 现已接入 `mapping_adapter.py` 与 `mapping_context.py`，保留各生成器调用后的短事务/人工保护，仅替换模型边界。统一输出键 mapping_candidate_v1，由服务端固定注册表选择四种具体业务 Schema；额外字段、越界引用和未证明物理来源均被拒绝。

Context 的同名旧引用保留全部来源成员和最高密级，显式标注歧义；参考定义/检索摘要不当作制度条款，保留 missing_basis 并降低置信度。生成器仍只写原有 AI 草稿字段，不覆盖正式人工正文。

2026-09-28 原生业务/运行/发布组合 56 passed；既有 Mapping/场景人工与并发保护 52 passed；歧义成员/密级定向 1 passed；固定导出与多脚本组 27 passed 加失败夹具修复后 1 passed。原生测试覆盖四类独立评测/发布、真实 Context+Mock、非法引用、模型期间人工改写和撤权。Word/Excel 同一固定修订、历史资料后续变更不进入导出已验证。

2026-09-29 A6 核心参考实现已验证，用户取消模型交接，由当前线程继续 B 阶段。B2 需求候选生成/来源/人工采用及两类场景 Mapping 来源浏览器验收通过 7 项（真实 HTTP、隔离 SQLite、Mock）；四类 Mapping 后端来源读取均有真实 Context 验证。完整业务页面覆盖及真实模型验收仍待 B2/B6 补齐。兼容 Prompt 发布快照现按任务保存原生输出 Schema，五类发布路径回归通过。
