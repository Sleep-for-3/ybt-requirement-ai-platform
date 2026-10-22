# 《银行监管数据智能平台 VNext 2 长时间开发成果与验收报告》

> 本报告只记录**本轮实际执行并有证据**的结论。证据级别沿用任务书口径：
> `MOCK`（合成夹具/替身）、`REAL_COMPONENT`（真实 PostgreSQL/Redis/Milvus/浏览器/队列）、
> `REAL_MODEL`（公司 DeepSeek 开发网关）、`BUSINESS_VERIFIED`（银行专家独立标注）、`UNVERIFIED`。
> 本轮**没有**任何 `BUSINESS_VERIFIED` 结论：所有业务规则均为合成口径，不能表述为真实监管准确率。

---

## 第一部分：本次开发基线

| 项目 | 实际值 |
| --- | --- |
| 仓库 | `https://github.com/Sleep-for-3/ybt-requirement-ai-platform` |
| 分支 | `dsh/vnext-business-accuracy-20261021` |
| 本轮起始 HEAD | `6b75384e4bacd94dfae70c58900f09282c7fcde5`（与 `origin/` 同名分支一致，工作树干净） |
| 本轮结束 HEAD | 见 `git log`（本轮提交序列如下，全部在开发分支，未合并 `main`、未推送远端） |
| 提交序列 | `08f8e9b` P0-A → `b5e5ae8` P0-B → `525190d` P0-C 后端 → `7d37cc7` P0-C 浏览器/P1-B 一 → `182d479` P1-B 二 → `2475d46` P1-A → `a5249f3` P1-C → `34ef423` P2-A/P2-B → 全量回归与报告归档提交 |
| 开发/验收模型 | 公司 DeepSeek 网关 `deepseek-v4.1-flash`（`openai_compatible`）；`deepseek-v4-flash` 本轮已从网关下线 |
| 数据库 | PostgreSQL 16（WSL2 Docker，`ybt-postgres`，库 `ybt_dsh_handoff_v2`） |
| 队列 | Redis 7 + Celery（worker `--pool=solo`，Beat 3 条计划任务） |
| 向量库 | Milvus 2.5.4（`ybt-dev-milvus-1`，etcd + minio） |
| Embedding | 本地 `scripts/local_embedding_server.py`（fastembed `bge-small-zh-v1.5`，512 维） |
| 前端 | Next.js dev（`npx next dev -p 3010`），桌面 Chromium（Playwright） |
| 运行环境 | Windows 11 + WSL2 Ubuntu；后端 `backend/.venv` Python 3.12 |

**基线核对结论**：任务书给出的 SHA 与本地一致；工作树无未提交改动；`docs/` 下 VNext 验收材料与源码一致
（`VNEXT_UPGRADE_ACCEPTANCE_REPORT`、`VNEXT_REAL_COMPONENTS`、`VNEXT_PHASE0_CAPABILITY_MATRIX`、
`VNEXT_PHASE5_WORKSPACE`、`VNEXT_REAL_MODEL_GOLDEN`、`VNEXT_CELERY_RECOVERY`）。

**与任务书声明的偏差（必须记录）**：仓库历史日志 `pytest-final-20261021-round3.log` 尾部是
`2 failed, 1902 passed, 1 skipped`，与提交说明中的 “1910 passed / 1 skipped / 0 failed” 不一致；
失败两例为 `test_llm_runtime.py` 的 provider 回退用例。本轮这两例已通过，最终全量回归结论见第六部分。

---

## 第二部分：原始痛点（逐条：缺陷 → 代码入口 → 复现依据）

### P0-A 冻结快照时效性

1. **冻结后新增的待确认问题不阻断送审/交付。**
   `backend/app/services/requirement_review.py::review_readiness` 只看
   `RequirementRevision.content_json` 里的 `gaps`；`finalize_formal_delivery` 只看
   `script_basis_changes/comparison_issues/path_issues`。
   复现：`backend/tests/test_vnext2_review_freshness.py` 改前 **7 failed / 2 passed**，
   `review_readiness` 在冻结后新建 `PendingQuestion` 时仍返回 `eligible=True`。
2. **`accepted` 被误当已解决的风险**：问题状态机有 `open/assigned/answered/accepted/rejected/closed`，
   `accepted` 只表示接手；原 UI 以绿色徽标呈现，且关闭不要求解决依据。

### P0-B 引用可信性

3. **C08 复合结论只被部分支持时按“整段”判定**：`citation_validator.check_citation_support` 以整段 answer
   作为 claim，一条 citation supported 就可能让整段答案判为可信。
4. **C09 冲突证据不可见**：裁判 prompt 与解析只接受 `verdicts`，没有冲突输出；检索排序靠前的一份证据
   即可决定结论，另一份矛盾证据被静默丢弃。
5. **C10 版本不会被确定性拦下**：`pinned_versions` 只存在于评测脚本，产品链路没有“需求固定的制度版本”
   与“引用版本”的比对，知识库升级后旧需求可能引用新版本。
6. **真实模型 7/10 → 失败原因不可解释**：`docs/audit/VNEXT_REAL_MODEL_GOLDEN-20261021.json` 显示 C08/C09/C10
   与合成期望不一致；本轮先修产品，不改黄金期望。

### P0-C 真实交付链路

7. **`refresh-lineage` 接口 100% 500**：`backend/app/api/requirements.py` 以位置参数调用
   `record_audit(db, action, project_id, user_id, message)`，而签名是
   `record_audit(db, *, action, resource_type, ...)` → `TypeError`。此前无人调用故未被发现。
8. **AI 候选的 gaps 无法关闭**：采用候选会把 `candidate:<item>:<hash>` 缺口写入 `content["gaps"]`，
   但产品只有“补齐字段内容”路径，没有任何 API 能用说明关闭非字段派生缺口 → 采用带缺口的候选后
   需求永久无法送审/交付。
9. **证据/物理引用采用契约前后端不一致**：`requirement_candidates.SPECIAL_FIELDS` 只允许 lineage 章节写
   `physical_references`，前端却对任何章节渲染该勾选项 → 业务章节采用 422「请选择有效候选差异」。
10. **重复关闭已关闭缺口静默成功**：`resolve_gap` 对已关闭缺口直接返回旧修订（201、版本不变），
    前端又对已关闭项继续渲染关闭按钮 → 用户/脚本反复点击但内容版本永远不前进。
11. **blocked 项的重试被重试预算拦死**：`retry_requirement_generation` 只判断
    `job.status ∈ {failed, partially_completed, cancelled}`，而“单轮内 blocked”任务状态是 `completed` →
    409「当前任务不可重试」。
12. **真实模型返回空正文时被伪造占位候选**：`openai_compatible.chat_structured` 在首轮 JSON 校验失败后进入
    “只回传 schema 的格式修复”路径；推理模型 2048 输出预算耗尽时 `content=""`，修复请求于是编造
    `{"final_content":"Repaired JSON object conforming to the provided schema."}` 并被当成候选。
13. **普通角色进入项目页必得 403**：`frontend/app/projects/page.tsx` 对所有角色无条件请求
    `GET /admin/institutions`。

### P1-A Agent 决策

14. **人工否决后可直接 retry 重跑同一被否决结论**：`retry_task` 把所有 `failed/blocked` 步骤无差别重置为
    `pending`，人工 reject 产生的 `blocked` 也在其中 → 与“不能重新偷偷采用被否决的结论”冲突。

### P1-B SQL 语义与影响传递

15. **`gbase` 方言直接崩溃**：`sqlglot` 不认识 `gbase`，`_semantic_ast` 未捕获 → 上传 GBase SQL 时 500。
16. **CTE 内部变化被吞**：CTE 谓词/投影变化不进入任何语义维度，只落“未归因 AST 变化”。
17. **CTE 名称参与签名**：仅重命名 CTE 被报为“取值/加工规则变化，可能改变监管口径”（误报）。
18. **普通 SELECT 的 WHERE 变化无结构化归因**：只有 lineage edge 带 filter 时才有 `filter_changed`。
19. **未归因兜底项宣称影响口径**：`transformation_changed` fallback 因 `category ∈ CALIBER_AFFECTING`
    被渲染成“可能改变监管字段统计口径”，虚增口径影响计数。
20. **别名/表限定符重写产生噪声**：`l.LOAN_AMT` → `LOAN_AMT` 等等价重写被报为变化。
21. **影响分析把目标字段 ID 当需求 ID**：`semantic_impact.py` `requirement_ids=sorted(set(target_field_ids))`，
    `api/lineage.py` 又用它反查 `TargetField` → “SQL 变化→关联需求”实际关联错对象；
    既有测试把该错误语义固化（`test_sql_lineage.py:859`、`test_lineage_impact_detail.py:176`）。

### P2-A 身份与稳定性

22. **legacy 身份物化的 savepoint 覆盖错误**：`actors.ensure_actor_user_id` 的 `db.flush()` 在
    `begin_nested()` 之外，唯一键竞态会打挂外层事务（PostgreSQL `current transaction is aborted`）。
23. **匿名 legacy principal 恒为平台管理员**：`permission_service.is_platform_admin` 只看
    `is_legacy_system`，没有校验 `AUTH_MODE=optional`。

### P2-B 工作台

24. **“已接收处理”与“已解决结案”视觉无差别**；关闭按钮不要求解决依据，关闭后仍阻断但用户无从得知。
25. **正式交付面板缺少冻结快照哈希与 SQL 变化复核状态**，审核状态与复核状态混在一起。

---

## 第三部分：实际开发成果

### 3.1 新增能力

| 能力 | 位置 | 证据级别 |
| --- | --- | --- |
| 当前交付安全检查层（冻结事实层之外，覆盖 readiness/submit/审批/finalize） | `backend/app/services/requirement_delivery_safety.py` | `MOCK` + `REAL_COMPONENT`（PG 并发） |
| 问题写入与定稿共享 Requirement 行锁（防 TOCTOU，不新增锁体系） | 同上 `lock_project_requirements` + `api/deliverables.py` | `REAL_COMPONENT` |
| 引用裁判主张级 + 冲突契约 + 确定性版本裁决 | `services/rag/citation_trust.py`、`citation_support.py`、`citation_validator.py` | `REAL_MODEL`（合成期望） |
| 缺口说明关闭通道（字段派生缺口禁止绕过） | `services/requirement_revisions.resolve_gap` + `POST .../gaps/{gap_id}/resolve` | `REAL_COMPONENT`（浏览器） |
| 生成模型空正文/占位正文守门 + 输出预算配置 | `llm/openai_compatible.py`、`requirement_candidate_contract.py`、`core/settings.llm_max_output_tokens` | `REAL_MODEL` |
| SQL 行数上限 / CTE 归因（38/39 家族） | `services/lineage/{sql_parser,version_diff,sql_semantic_diff}.py` | `MOCK`（合成 SQL 矩阵） |
| 等价重写归一（表别名、CTE 名称、裸列限定符） | `services/lineage/version_diff.py` | `MOCK` |
| 真实需求关联（按 `Requirement.scope_json` 求交，项目隔离） | `services/lineage/semantic_impact.py` | `MOCK` |
| Agent 人工否决重试守卫 | `services/agent/runtime.retry_task` | `MOCK` |
| 黄金集结构化标注 + 真实性级别 + 未执行族 `not_run` | `services/evaluation/regulatory_golden.py` | `MOCK` |
| 工作台问题语义/责任人/阻断说明、交付面板快照与复核状态 | `frontend/app/questions/page.tsx`、`RequirementDeliveryPanel.tsx` | `REAL_COMPONENT`（浏览器） |
| legacy 身份安全边界（savepoint + 模式校验） | `services/auth/{actors,permission_service}.py` | `MOCK` + `REAL_COMPONENT`（PG 竞态） |

### 3.2 修复缺陷

第 1–25 条均已定因并落地处置：除第 5 条（C10 的 `pinned_versions` 尚未接入产品生成链路，
见 3.4 与本部分风险第 5 项）之外，其余均已修复并有回归或真实组件证据。其中影响最大的是：
冻结后问题绕过（P0-A）、引用裁判版本/冲突（P0-B）、真实模型空正文伪造候选（P0-C）、`refresh-lineage` 500、
需求关联错位（P1-B）、legacy savepoint 打挂事务（P2-A）、人工否决后重试重跑（P1-A）。

### 3.3 已有能力验收（未重做，仅核对）

字段重排有界淘汰赛、引用级/主张级计数分离、60 例合成黄金集、待确认问题阻断与结案、
PG/Redis/Milvus 真实冒烟、本地 Embedding、知识上传审核生效检索、Celery 重复投递/崩溃扫描/迟到写围栏、
混合检索分数饱和修复、optional 模式任务外键、工作台 Chromium 点检。

### 3.4 未完成项

检索规模性能（缺容量基线）、Worker/Beat 进程自动重启（部署层）、
`pinned_versions` 接入生成链路、AI 候选“检索召回 vs 模型比较”前端标识、知识上传在浏览器闭环中重复。

---

## 第四部分：真实业务闭环

**场景**：合成“借据 → 合同 → 产品 → 产品期限/方案 → 客户 → 来源库 SRC → 数据集市 MART → 一表通目标表”
链路，目标字段取客户统一标识/产品余额；制度文本为合成 `2026-v1`（明确“产品ID+期限编号”组合业务键，
**不代表任何真实银行口径**）。

**执行方式**：主链路全部走 HTTP API 与真实页面，夹具只预置元数据/知识/映射；真实模型、真实 Celery、
真实 PostgreSQL、真实 Next.js。

| 步骤 | 证据 |
| --- | --- |
| 建需求 → 冻结内容 v1 → 生成输入 → `generation-runs` | 真实模型生成 business/lineage 候选（15–50s/次） |
| 候选展示 → `adopt` 采用（真实 `candidate_hash`） | 内容 v1→v2→v3 |
| 缺口逐条关闭（`resolve_gap`）+ 人工技术确认（来源系统/来源表/来源字段） | v4…v10，新增 `edited_lineage` 缺口被血缘刷新清除 |
| `refresh-lineage` 建立字段血缘快照 | v11，`review-readiness` → `eligible=true, blocking_count=0` |
| 送审 → 业务审核 → 技术审核 → 终审（三个独立角色） | 每次审批重跑 readiness；不通过则 409 并保留原状态 |
| 正式交付 → 下载 Excel / Word | `docs/audit/vnext2-p0c-browser/requirement-v1.{xlsx,docx}` |
| 快照校验 | 导出响应头 `X-Requirement-Snapshot-Hash` 与 DB `RequirementFormalDelivery.snapshot_hash`、文件 sha256 三处一致 |
| 交付后新建修订 | 内容版本前进，历史 `formal-deliveries` 内容与文件哈希不变 |
| 反例：交付前新建关键问题 | 定稿被 409「存在 N 项当前待确认问题」阻断；回答+关闭（带解决依据）后放行 |

- 后端闭环（`AUTH_MODE=optional` + `TASK_QUEUE_PROVIDER=inline`）：
  `tests/test_vnext2_p0c_real_delivery.py` → **4 passed**；开启真实模型 → **4 passed / 159.94s**。
- 浏览器闭环：`scripts/vnext2_p0c_browser_e2e.mjs` → **66 步 PASS / 1019 次 API**，
  截图与 JSON 证据在 `docs/audit/vnext2-p0c-browser/`、`docs/audit/VNEXT2_P0C_BROWSER-20261022.json`。
- 文档质量：导出的 Word/Excel 覆盖业务背景、报送对象、数据范围、目标字段、源字段、来源系统、取数路径、
  关联关系、唯一性/去重、加工逻辑、日期口径、NULL 与码值处理、制度依据、SQL 证据、待确认问题、
  人工确认记录与审核版本。**未做**逐项字段覆盖率打分（无独立标注基线，标记 `UNVERIFIED`）。

浏览器闭环中顺带修复：`refresh-lineage` 500、缺口无关闭通道、已关闭缺口重复关闭静默成功、
业务候选证据采用 422、lineage 物理引用采用 422、普通角色项目页 403、生成失败重试提示与重试预算耗尽路径。

---

## 第五部分：AI 质量（样本量 + 真实性级别）

| 维度 | 样本 | 结果 | 真实性级别 |
| --- | --- | --- | --- |
| 引用裁判（合成 C01–C10） | 10 | 改前 7/10；改后 **10/10**，`degraded=0`，主张级 9/10，检出冲突 2，平均 4338.6ms | `REAL_MODEL` + 合成期望，`UNVERIFIED` 业务准确率 |
| 引用输出契约 | — | claim_id/citation_id/supported-unsupported-unknown/依据/版本/适用时点/覆盖率/失败状态齐备；确定性规则优先（版本不匹配/越界/引用不存在） | `REAL_MODEL` |
| Agent 五类决策 | 5 | 信息充分→按工具链产出候选并在人工采用处停；缺输入→阻断并给下一步；Skill 未绑定→显式 gap 不静默绑定；需人工确认→`waiting_human` 保留证据；人工否决→禁止直接 retry，必须 replan | `MOCK`（机制级） |
| Agent 回归 | 224 例 | 全通过 | `MOCK` |
| SQL 语义家族 | 39 类 | 38 类可归因；仅 `order_by` 明确 limitation（单独 ORDER BY 不宣称影响口径） | `MOCK`（合成 SQL 矩阵） |
| GBase/Hive 语法矩阵 | 15 解析 + 8 变更 | 15/15 状态符合预期，8/8 变更期望符合；不可解析两侧不伪造归因 | `REAL_COMPONENT`（sqlglot）+ 合成期望 |
| 复合业务键 | 3 | 单键对复合键→`cardinality=unknown` + 复合唯一键 gap，不自动拼接键；双键全联→`complete/unique`；单列键行为不变 | `MOCK` |
| SQL 影响传递 | 4（2 正 2 反） | JOIN 类型/取值逻辑变化正确关联到 owner 需求与复核任务；无关需求/其他项目不误关联；仅注释格式不触发复核 | `MOCK` |
| 字段匹配 Top1/Top3/MRR | 60 例黄金集 | 本轮未执行真实召回排序 → `not_run`，指标 `None` | `UNVERIFIED` |
| 文档交付 | 1 份真实 Word/Excel | 章节齐备；无独立专家评审 | `UNVERIFIED` |
| 合成期望一致率 vs 业务准确率 | — | 前者可报（10/10）；后者一律 `UNVERIFIED`/N/A，不出现无依据 100% | — |

黄金集保持 60 例不变（字段语义 10 / 多表关联 10 / 引用 10 / SQL 10 / Agent 10 / 交付 10），
本轮只补齐“案例作者 / 预期答案作者 / 独立标注人 / 审核时间 / 标注依据 / 状态 / 争议处理 / 数据集版本”
的结构化管理；`reviewer_id` 非空**不再**被当作独立标注完成的证据。

---

## 第六部分：工程验收

| 项目 | 结果 |
| --- | --- |
| 后端定向回归（各工作包） | P0-A 9+3、P0-B 18+27、P0-C 4（真实模型 4/159.94s）、P1-A 5（agent 全量 224）、P1-B 365、P1-C 19、P2-A 5（真实 PG）、auth 子集 153 |
| 后端全量回归 | 第一次（默认 `.env`：真实 Celery/Redis）`2 failed, 1981 passed, 5 skipped, 1 error / 2534s`，原始日志 `docs/audit/VNEXT2_FULL_REGRESSION-20261023a.log`；两例均已定因（一例测试断言写错已修、一例内存 SQLite 线程连接抖动，单跑通过）。复跑（`AUTH_MODE=optional` + `TASK_QUEUE_PROVIDER=inline`）**`1983 passed, 5 skipped, 0 failed / 2362.45s`**，日志 `docs/audit/VNEXT2_FULL_REGRESSION-20261023b.log` |
| 前端 `npm test` | 308 例：307 passed / 1 failed（`semantic-catalog-browser` CDP 8s 超时，单跑 12/12 通过，判定并行负载时序抖动） |
| 前端 TypeScript | `npx tsc --noEmit` 通过 |
| 前端构建 | `next build` 成功（`exit 0`，日志 `docs/audit/VNEXT2_FRONTEND_BUILD-20261023.log`） |
| PostgreSQL | 真实迁移 head、真实事务/行锁/并发（P0-A 3 例、P2-A 竞态 1 例） |
| Redis/Celery | 真实 worker/beat；重复投递幂等、崩溃扫描重投、迟到写围栏为既有验收，本轮未回归破坏 |
| Milvus | 真实重启后 16 行数据与 HNSW 索引可查（21.8ms），无“必须重建索引”问题 |
| 模型调用 | 全部经 `ModelCallLog`/审计记录；本轮真实调用集中在 C01–C10、P0-C 4 次生成；不发送真实客户资料，输入为合成数据 |
| 浏览器 | P0-C 66 步全链路、P2-B 6 项断言；桌面 Chromium |

数据库变更：本轮**没有**新增迁移（沿用既有 head），所有改动为服务/接口/前端与测试；
未修改历史正式记录，未删除正式 Milvus Collection（探针集合用完即删）。

---

## 第七部分：风险和剩余缺口

1. **无银行专家独立标注**：全部“准确率”只对合成期望负责。影响：不能对外宣称监管口径正确率。
   下一步：由业务方提供 20–30 条真实脱敏案例做独立标注。
2. **真实模型仍有概率性违规输出**：`policy_comparisons` 越界引用会被合规闸门拦成 `blocked`
   （需要重试/新建轮次），属于“正确阻断”，但用户会感到中断。下一步：提示词中显式列出可引用规则白名单。
3. **检索规模性能未验证**：3 查询/4 文档的链路证据不足以支撑容量结论。下一步：按用户给定容量准备合成知识库。
4. **Worker/Beat 自动重启缺失**：仓库无 supervisor。下一步：提供 systemd/Docker restart policy 模板并在隔离环境演练。
5. **`pinned_versions` 未进产品生成链路**：引用裁判已能确定性裁决，但生成时仍依赖 `script_basis.policy_snapshot`。
6. **AI 候选阶段标识不足**：无法在 UI 区分“仅检索召回/分批模型比较/最终比较”。
7. **知识上传播链未在浏览器闭环重复**（API 级已覆盖）。
8. **前端浏览器测试在并行负载下会超时**：需调高 CDP 超时或串行化，非产品缺陷。

---

## 第八部分：下一轮优先级（≤5 项）

1. **真实案例独立标注**：与业务方共建 20–30 条脱敏真实案例，产出 `BUSINESS_VERIFIED` 基线。
2. **检索规模与权威优先**：按给定容量做小/中/大三档测评（延迟、召回、误召回、同分稳定性、重排成本）。
3. **生成链路版本固定（Round 6 已部分完成，见第十部分）**：`pinned_versions` 已接入需求快照与问答链路；剩余工作是“新制度自动触发复核提醒”与生成候选侧的版本引用审计。
4. **部署韧性**：systemd/Docker 重启策略 + Milvus/Redis 断连演练 + 长任务租约续期验证。
5. **工作台收口**：AI 候选阶段标识、跨页待办入口、知识上传播链的浏览器化。

---

## 第九部分：普通使用者说明

**现在能完成什么**
- 把一个监管需求拆成目标字段，自动生成“业务口径 + 技术溯源”候选，并列出每条候选引用的制度条款与物理字段；
- 人工确认后形成需求独立版本，逐步关闭待确认缺口，刷新字段血缘，送业务、技术、终审三级审批；
- 审批通过后固定正式交付版本，下载 Word/Excel；下载文件与数据库快照哈希一致，事后修订不会改动旧文件；
- SQL 变更会被解析成语义变化（JOIN 类型、过滤条件、分组、去重、行数上限、CTE 等），并关联到受影响的需求与复核任务。

**哪些能自动执行**
- 生成候选、计算缺口、检索证据、解析 SQL、计算影响、生成文档、记录审计；每一步都会留下模型/来源/版本信息。

**哪些必须人工确认**
- 任何“确认口径”：AI 给的都是候选；没有人工确认不会变成 confirmed，没有审批不会产生正式交付；
- 待确认问题的回答与结案：必须写解决依据，“接受处理”不等于解决，“驳回”也要写依据才解除阻断；
- 正式交付：必须三级审批通过，且交付前不能有关键新增问题。

**如何查看字段来源与监管依据**
- 工作台“血缘”页签看 Source/Mart/YBT 字段路径与刷新后的血缘快照；
- “证据”页签看引用的制度条款、版本、生效时间与定位；引用若与需求固定的版本不一致会被判为不支持。

**如何生成并交付需求文档**
- 需求工作台 → 生成候选 → 选择差异加入采用清单 → 应用 → 关闭缺口 → 补齐人工技术确认 → 刷新血缘 →
  可送审后提交 → 各角色在“任务”页审批 → 审核与正式交付面板固定版本 → 下载 Excel/Word。

**SQL 变化之后**
- 系统会生成影响分析与复核记录，工作台“审核与正式交付”会显示“SQL 变化复核”状态；
- 历史正式交付文件保持不变，需要按复核结论建立新修订并重新走审批。

**目前仍不可靠的场景**
- 真实银行监管口径的准确性（无专家独立标注）；
- 大规模知识库下的检索质量与延迟；
- 推理型模型在超长输入下可能返回空正文（系统会明确失败并可重试，不会伪造内容）；
- 产品 ID 与期限等复合业务键：只有制度或人工依据支持时才会采用，系统不会自动拼接键。

---

## 第十部分：Round 6 增补（引用版本钉扎闭环，2026-10-23）

本部分补充第八部分第 3 项在本轮的实际落地，以及过程中发现的确定性缺陷。

### 10.1 原问题

P0-B 阶段已让引用裁判支持 `pinned_versions`（需求冻结时固定的制度版本），但**没有任何产品调用方传入它**：
`backend/app/services/rag/grounded_answer_service.py` 调用 `check_citation_support(...)` 时未带钉扎参数，
`backend/app/api/knowledge_rag.py` 的问答接口也不接受需求版本。结果：

- 需求固定制度 v1、知识库已启用 v2 时，问答会用 v2 的引用去回答 v1 的问题；
- 裁判看不到“版本不匹配”这一确定性信号，只能靠语义判断，导致 C10 场景实际不可控；
- 冻结快照只保存哈希，用户无法在问答里“只看我这一版对应的制度”。

### 10.2 实际改动

1. 新增 `backend/app/services/requirement_pins.py::pinned_versions_for_requirement(db, project_id, requirement_id, content_version)`：
   从冻结的 `RequirementRevision.content_json` 推导 `{来源标题: 监管版本}`；走 `load_revision` 的哈希完整性校验；
   空白/占位版本不参与；同一标题出现多个版本时标记为 `_conflicting:<标题>` 并排除，避免钉扎一个自相矛盾的版本。
2. `backend/app/services/rag/grounded_answer_service.py`：把钉扎版本传给 `check_citation_support`，成功时在响应回显 `version_pin`。
3. `backend/app/api/knowledge_rag.py`：`AskRequest` 新增 `requirement_id` / `requirement_content_version`；
   只给其一时 400（不猜测）；该版本没有任何可用钉扎时 422 保守拒绝；成功时回显 `version_pin`。
4. **修复的真实缺陷**：`backend/app/services/rag/citation_trust.py::normalize_version` 原实现只解析年份，
   `2026-v1` 与 `2026-v2` 归一化后相等 —— 需求固定 v1 时，v2 的引用不会被判为版本违规。
   现保留 `v<数字>` 修订号，`2026-v1 != 2026-v2`。
5. 前端接线（`ai-platform/frontend`）：
   - `lib/knowledge-contract.mjs` 的 `askPayload` 支持可选钉扎参数（缺任一 id 不发送，绝不默认“最新版本”）；
   - 新增 `pinNotice(pin, versionPin)` 纯函数，区分“已固定”和“请求固定但未回显”；
   - `app/knowledge/ask/page.tsx` 读取 `requirementId` + `contentVersion`，提交时携带，并在页面顶部显示钉扎状态；
   - `components/requirement-workspace/RequirementDeliveryPanel.tsx` 增加“带本版本制度版本提问”入口（携带需求与内容版本）。

### 10.3 验证

| 验证项 | 命令 | 结果 |
| --- | --- | --- |
| 版本钉扎后端 | `pytest tests/test_vnext2_pinned_versions.py -q` | 10 passed |
| 引用信任域 | 同上 + `tests/test_vnext2_citation_trust.py` | 28 passed |
| 引用/知识/问答域回归 | `pytest tests -k "citation or rag or knowledge or grounded or ask or pin"` | 334 passed（900.65s） |
| 前端契约 | `node --test tests/knowledge-contract.test.mjs` | 6 passed |
| 类型检查 | `npx tsc --noEmit -p tsconfig.json` | 通过（exit 0） |

证据级别：`REAL_COMPONENT`（真实 PostgreSQL 驱动的服务级测试 + 真实前端契约测试）；
“业务准确率”仍为 `UNVERIFIED`（无银行专家独立标注）。

### 10.4 仍然缺口

- 新制度发布后**自动提醒**“该需求引用的 v1 已被 v2 取代、需要复核”：目前只有引用裁判在问答时拒绝越版引用，没有主动推送。
- 需求生成（generation-run）链路的候选仍在提示层使用当前知识库内容，未把钉扎版本传给生成模型输入；候选审计里也还没有“引用版本”字段。
- 前端问答入口只在需求工作台与知识问答页，尚未在“待确认问题处理”页内直接带版本提问。
