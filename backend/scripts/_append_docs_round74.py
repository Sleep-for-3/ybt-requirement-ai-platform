"""一次性：把 round 74（T_5_1 主线 + 逐列比对 + 审批阻断）的章节续写到 5 份交付文档。

只追加，不改已有内容；重复运行会因 `## 79.` / `### 7.76` 等锚点已存在而退出。
"""

from __future__ import annotations

import pathlib
import sys

BASE = pathlib.Path(__file__).resolve().parents[2] / "docs" / "requirement-delivery-upgrade"


REAL_RUN = """## 79. round 74：目标表 T_5_1 从跑批脚本走到冻结导出

### 79.1 起点：这张表现在没有需求

交接时 `T_5_1 产品业务基本信息`（target_table_id=59、18 个绑定字段、16 条集市映射、跑批脚本
`YBT_T_5_1.sql`）在项目 9 里没有任何需求记录。本轮要验证的是"脚本 → 需求 → 生成 → 采纳 → 冻结 →
导出"这条线在真实数据上能不能走通，而不是再造一个演示接口。

### 79.2 脚本预览：先看脚本能解析出什么

`POST /projects/9/requirements/script-preview`（body `{"script_version_ids":[32]}`，脚本版本
`YBT_T_5_1.sql` v32）返回 4 条语句、1 个目标表（`SAFE_INSTANCE_GB.T_5_1`，29 列）、75 条规则，
`preview_hash=dfde201152829cf1d751c39b5fb15a210ce3ca56b0dc74d68548854d548b370d`。
75 条规则是导出里"处理逻辑/处理逻辑类型"两列的唯一来源——不解析脚本，这两列只能是空的。

### 79.3 一键建需：18 个字段全部绑定

`POST .../author-from-scripts`（body `{"table_codes":["T_5_1"]}`）→ 201：`requirement_id=30`、
`content_version=2`、`target_table_id=59`、模板版本 2（`YBT_SURVEY_2022`，R2022100101）、
`bound_field_count=18/18`、`rule_count=75`、`gap_count=48`、`scenario_id=2`（既有的"一表通监管报送
（20261024 跑批）"）。字段 18 个（E010001–E010018 里缺 E010006，另有 `SFJJGDM` 省局分局机构代码）、
集市映射 16 条；`SFJJGDM` 与 `E010017` 没有集市映射。

### 79.4 生成：36 个条目，33 条可用、3 条阻断

`POST .../generation-inputs` → input 49（18 字段 × business/lineage 两段，`input_hash=0c499bd3…`），
`POST .../generation-runs` → job 83。服务端约 60–70 s 一条，36 个条目跑完，终态
`partially_completed`：**completed 33 / blocked 3 / failed 0**。

三条阻断都是校验闸门拦下的，不是排队或网络问题，逐条记在这里（不靠重试"试出来"）：

| 条目 | 字段 | 段落 | 原因 |
| --- | --- | --- | --- |
| 409 | E010004 产品编号（981） | business | `generation_validation_blocked`：生成结果引用了范围外的物理字段 |
| 414 | E010007 产品类别（983） | lineage | 同上 |
| 430 | E010015 产品状态代码（991） | lineage | `generation_validation_blocked`：候选正文主张与固定事实冲突（c1/code_mapping_unrelated） |

前两条的闸门在 `backend/app/services/requirement_candidate_contract.py:105`：候选给出的
`physical_references` 必须落在冻结输入的 `physical_sources`/`mapping_sources` 白名单里，模型引用了
白名单外的物理字段，于是整条候选被拒。这类结果不能"采纳一半"，也不能放宽白名单让它过——正确处置
是**不采纳该候选**，该字段业务口径保持"待业务补充"，等人工补。

### 79.5 采纳：一次批量写入，因为单条采纳必然 409

`backend/app/services/requirement_candidates.py:109` 要求 `expected_version` 同时等于生成输入里的
`content_version` 和需求当前 `content_version`。第一次采纳会把需求推进到 v3，第二次再送 v2 必然 409。
前端工作台同此设计：右侧"加入采用清单"，最后一次性提交。

本轮逐个核对 33 条候选差异后，用 `POST .../generation-candidates/adopt` 一次写入：
**content_version 2 → 3**，revision `content_hash=729a18698a043c3740b5e381841e6c51f126c5bd4183d3e2267b10d1660d808b`。

这里有个必须写清楚的坑：**送审用的哈希和冻结用的哈希不是同一个哈希**。

- 送审 `expected_content_hash` = revision 存盘时的 `content_digest(content_json)`（`729a1869…`）；
- 冻结导出 `expected_hash` = delivery-status 的 `current_content_hash` =
  `jsonable_encoder(document_content(...))` 的摘要
  （`8dacc2b9a96a80edd0ce2e641d5681d0b42767e02f2bc6c5d9a14cdc45e09f18`）。

`document_content` 会补表级元数据与场景分组，两者的摘要必然不同。用错了就是 409"需求内容已变化，
请重新加载后送审"——本轮前两次送审撞的都是这个，换成 revision 哈希后才露出真正的审批阻断（见 §81）。

### 79.6 冻结导出：快照 44、产物 68

`POST .../freeze-and-export`（form：`format=xlsx`、`layout=survey`、`expected_version=1`
用 requirement_version 而不是 content_version、`expected_hash=8dacc2b9…`）→ 200：

- `x-requirement-snapshot-id: 44`、`x-requirement-snapshot-created: true`、快照哈希 `8dacc2b9…`；
- `x-requirement-render-artifact-id: 68`；
- `x-requirement-rendered-file-sha256: 958e91c8b22d5829b2093dd100658df19276a2897bb90ce1c79e1bdea03b2d62`；
- `x-requirement-renderer-version: survey-requirement-doc-v10+0db3941019ea`，文件 16650 字节。

### 79.7 导出的表长什么样

`backend/scripts/out/probe/t51_survey_v10.xlsx`：47 行 × 56 列、28 个合并区。表级 6 行在第 3–8 行
（A 列标签、C 列起取值）；第 10 行 8 个分组标题：`一表通数据基础信息`、`EAST5.0同源映射列`，以及三组
`业务口径-*` / `溯源-*`；第 11 行 56 个列名；第 12–29 行 18 个字段；第 31–39 行交付完整度
（含"场景分组数=3""场景覆盖字段=18（其余字段按来源系统分组）"）；第 41–47 行来源说明。

三组场景是：借记卡（溯源-借记卡系统）、信用卡（溯源-贷记卡系统）、代销理财（溯源-理财销售系统），
每组 6 列业务口径 + 9 列溯源。场景正文全部来自 `ai_generated_content`，渲染器强制加
"（AI 生成草稿，待业务确认）/（AI 生成草稿，待技术确认）"前缀——**这是演示数据，不是已确认口径**，
库里的 `confidence_level=low`、确认状态是 `draft`，可被人工覆盖。

## 80. 与客户示例逐列比对：13 条差异，每条都有"为什么/下一步"

### 80.1 比对方法

`backend/scripts/requirement_doc_compare.py`（只读：不写库、不重渲、不读产物以外的文件）同时打开
`C:\\Users\\李儒伟\\Desktop\\需求文档输出示例.xlsx` 与本轮导出，比五类：表级 6 行标签与取值、
第 10 行分组标题、第 11 行列名序列、数据行第 1 列编码集合、每列非空率。输出
`backend/scripts/out/doc_compare.json`（机读）与 `backend/scripts/out/doc_compare.md`
（人读，逐条带为什么/下一步）。

### 80.2 已经对齐的部分

- 第 11 行前 11 个基础列名逐字一致（`base_columns_match=true`），包括本轮去掉的三个表头换行；
- 版式骨架一致：第 3–8 行表级 6 行、第 10 行分组标题、第 11 行列名、第 12 行起数据行；
- 每个场景组结构一致：业务口径 6 列 + 溯源 9 列，标题形如 `业务口径-<场景>` / `溯源-<系统>`。

### 80.3 13 条差异分四类

| 类别 | 条数 | 差异 | 结论 |
| --- | --- | --- | --- |
| 表级取值 | 6 | 数据分类/采集范围/与EAST差异 平台写"待业务补充"；数据主题名称/数据表名称 缺"（五）/表5.1"编号前缀；报送范围确认平台是"默认报送数据域" | 元数据缺口 + 编号口径，渲染器不编造，等业务补 |
| 列组内重复取值 | 3 | 示例在 row6/7/8 每个场景组首列分别写该场景的采集范围/报送范围/EAST差异（重复 31/150/18 处），平台只有一处表级值 | 需求正文只有单一 inclusion/objective/exclusion，没有按场景拆分的元数据 |
| 分组标题 | 1 | 示例 43 个组标题（10 个业务口径场景 + 对应溯源 + comstar 8 列窄组），平台 8 个（3 场景 + 2 基础 + 回退来源组） | 场景数量与"按部门/条线再拆"的差异 |
| 列名/编码/非空率 | 3 | 列数 328 vs 56（差异全部来自分组数量）；示例 19 个数据行含 2 行"补充字段"、平台 18 行；非空率差异集中在人工确认人/截图列与未覆盖字段整组留空 | 列定义本身一致，缺的是场景覆盖与人工确认 |

每条差异的示例值/平台值/为什么/下一步都落在 `doc_compare.md` 里，不在这里重复。

### 80.4 场景对齐

示例 10 个业务口径组，平台 3 个，交集 3：**借记卡、信用卡、代销理财**；仅示例有 7 个
（代销保险、代销贵金属、代销基金、储蓄存款、贷款产品、两条同业/债券组合长名组），仅平台 0 个；
公共溯源系统：借记卡系统、贷记卡系统。

这 3 个场景是 `backend/scripts/seed_t51_scenarios.py` 按"集市映射 + 脚本血缘"推导的演示场景
（正文只在 `ai_generated_content`，`confidence_level=low`，确认状态 `draft`，`created_by=demo-seed`）。
示例里另外 7 个场景涉及部门/条线拆分与 comstar 窄组，没有可靠依据，本轮不编。

### 80.5 逐列完全一致还差什么

按优先级：①目标表元数据（theme/filing_note/reporting_domain_*）与表号/主题编号由业务补齐；
②场景主数据补到示例的 10 个业务场景，并把"部门/条线"作为场景维度或新增窄组类型；
③需求正文支持按场景给出采集范围/报送范围/EAST差异，渲染器才能像示例那样在每组首列重复写；
④人工确认人/截图类列需要真实确认流程产出，不是渲染器能生成的。

## 81. 三级审批为什么没走通：589 项阻断，不做假闭环

### 81.1 送审被 409 挡住的真实过程

`POST /projects/9/requirements/30/review-submissions` 三次尝试（证据
`backend/scripts/out/probe/p1_submit_attempt.json`）：

1. 用 delivery-status 的 `current_content_hash`（`8dacc2b9…`）→ 409 `需求内容已变化，请重新加载后送审`；
2. 用 `GET .../requirements/30/document` 返回的 `content_hash`（同一个 `8dacc2b9…`）→ 同样 409；
3. 换成 revision 哈希（`729a1869…`）→ 409 `存在 589 项阻断条件，请先处理后再送审`
   （`error_code=state_conflict`，trace `98e585dc97b54cc6bde464b412630a50`）。

第 3 次才是真正的业务阻断。前两次是哈希用错（见 §79.5）。

### 81.2 589 项阻断是什么

`GET .../review-readiness?content_version=3`：`eligible=false`、`blocking_count=589`，构成：
scope 类 125、candidate 类 344、每字段 4–9 条共 120 条（978–995 共 18 个字段）。
`GET .../requirements/30/gap-breakdown`：`open_gap_count=510`、`field_gap_count=385`、
`scope_gap_count=125`、`category_count=281`；头部类别："未核验上游元数据 91""缺少明确纳入的知识证据，
正文仅为待核验候选 33""缺少可定位的来源表或字段 18""缺少来源到集市字段的加工映射 16""缺少依据 12"。

`review_readiness` 没有项目级豁免通道：`return {"eligible": not unique, ...}`，只要剩一条 reason 就不能送审。
横向看也不是 T_5_1 特例：项目 9 现有 4 条需求全部不可送审（rid 10 435 项、rid 8 202 项、rid 25 304 项），
`requirements-status.summary.formal_delivered=0`。

### 81.3 为什么不批量"核验"把缺口关掉

`resolve_gap`（`backend/app/services/requirement_revisions.py:241`）一次只能关一条，每关一条就
`append_revision` 一次；字段类缺口还明确禁止用说明关闭（`该缺口需通过补齐字段内容解决`）。要清掉 589 条，
至少要 589 次版本推进和对应的真实证据，本质是数据治理工作，不是本轮代码任务。用"已核验"的假说明批量
关闭会直接违反"不伪造审批"的红线，**不做**；结论按根因记录，不按"跑通了"记录。

### 81.4 因此本轮交付的形态

- 冻结**草稿快照**（snapshot 44）+ 渲染产物（artifact 68）不依赖审批，仍可复核、可重放；
- **正式交付**（三级审批通过 + finalize）在本环境不可达，`formal_delivered` 保持 0；
- 导出件与 UI 身份面板都写明"快照 #44（内容未变，复用已有快照）· 产物 #68"，不冒充正式交付。

### 81.5 演示环境"同一管理员代签"的说明（本轮未走到，但必须写清）

任务书要求若走审批则说明"演示环境同一管理员代签，非真实三岗"。本轮连送审都没通过，因此不存在代签；
但代码里有一道与角色无关的闸门：`backend/app/services/requirement_review.py` 的
`validate_review_decision` 在 approved 时取 `_content_authors(revision, step_key)`（来源
`content_json["manual_ownership"]`，为空则回退 `revision.created_by`——本轮是 ybt-lead），
命中即 409"内容维护人或送审人不能审核自己负责的内容"。也就是说即便 589 项清空，单一管理员也过不了
business/technical 两步，必须由另外的真实三岗账号参与。这一点如实记录，不用改库或换账号伪造。

### 81.6 下一步

①先补"未核验上游元数据"与"来源到集市字段的加工映射"两类缺口（91 + 16 条，占阻断的绝对多数），
它们来自脚本血缘的证据链，是最可能靠自动化补齐的；②字段级"缺少业务定义"（如 981/983）只能靠人工口径；
③清到 0 之后再走送审 + 三岗审批 + finalize，用真实账号，不代签。
"""

EVIDENCE = """## 102. round 74 T_5_1 主线接口证据

- 脚本预览：`POST /projects/9/requirements/script-preview`（`{"script_version_ids":[32]}`）→ statements 4 / targets 1 / rules 75 / `preview_hash=dfde2011…`；`ai-platform/backend/scripts/out/probe/p1_script_preview.json`
- 一键建需：`POST /projects/9/requirements/author-from-scripts` → `requirement_id=30, content_version=2, bound_field_count=18/18, rule_count=75, gap_count=48`；`ai-platform/backend/scripts/out/probe/p1_author.json`
- 生成：`POST .../requirements/30/generation-inputs` → input 49；`POST .../generation-runs` → job 83；终态 `partially_completed`（33/3/0）；`ai-platform/backend/scripts/out/probe/p1_runs_final.json`
- 采纳：`ai-platform/backend/scripts/adopt_t51_candidates.py`（先 GET 候选详情取 `changes[].field`，再 `POST .../generation-candidates/adopt` 一次写入）→ content_version 3；`ai-platform/backend/scripts/out/probe/t51_adopt_plan.json`、`t51_adopt_result.json`
- 送审被拒：`POST .../review-submissions` 三次 409（哈希用错 2 次 + 589 项阻断 1 次）；`ai-platform/backend/scripts/out/probe/p1_submit_attempt.json`
- 审批阻断：`GET .../review-readiness?content_version=3` → 589；`GET .../requirements/30/gap-breakdown` → 510/385/125/281；`ai-platform/backend/scripts/out/probe/readiness_30_3.json`
- 冻结导出：`POST .../requirements/30/freeze-and-export` → snapshot 44 / artifact 68 / 16650 B / sha `958e91c8…` / renderer `survey-requirement-doc-v10+0db3941019ea`；`ai-platform/backend/scripts/out/probe/p1_freeze_export.json`、`ai-platform/backend/scripts/out/probe/t51_survey_v10.xlsx`
- 导出结构：`ai-platform/backend/scripts/out/probe/p1_t51_xlsx_structure.json`（47 行 × 56 列、8 个分组标题、18 个数据行、场景分组数 3）

## 103. round 74 逐列比对与场景分组证据

- 比对脚本：`ai-platform/backend/scripts/requirement_doc_compare.py`（只读；比表级 6 行、第 10 行组名、第 11 行列名、数据行编码、每列非空率）
- 比对结果：`ai-platform/backend/scripts/out/doc_compare.json` + `ai-platform/backend/scripts/out/doc_compare.md`（13 条差异，每条含示例值/平台值/为什么/下一步；`base_columns_match=true`；场景交集 3）
- 场景分组渲染器：`ai-platform/backend/app/services/requirement_survey_export.py`（`SURVEY_DOC_VERSION="survey-requirement-doc-v10"`；`_scenario_groups` / `_column_plan` / `_scenario_business_values` / `_scenario_source_values` / `_scenario_notes`）
- 场景数据进冻结内容：`ai-platform/backend/app/services/requirement_scope.py`（`document_content` 读时补 `scenario_groups`，与 `current_content_hash`、`freeze_draft` 同一入口）
- 场景演示数据：`ai-platform/backend/scripts/seed_t51_scenarios.py`（`--dry-run`/`--apply`；3 场景 × 18 字段 → 54 条业务口径 + 54 条技术血缘，正文只进 `ai_generated_content`，`confidence_level=low`，确认状态 `draft`）
- 结构检查契约：`ai-platform/backend/app/services/requirement_survey_structure_check.py`（v10 起 `pair_by_position=true`，业务口径组与溯源组按位置成对）
- 后端用例：`ai-platform/backend/tests/test_requirement_survey_export_scenarios.py`（6 passed）
- 回归：survey 相关 43 passed；内容管线相关（scope/snapshot/delivery/formal-delivery/immutability/pins）60 passed

## 104. round 74 稳定性、复核清单与浏览器证据

- 稳定性（改渲染器 v9→v10 后重跑）：`GET /projects/9/export-stability?limit=50` → artifacts 49 / identical 10 / historical 38 / unsupported 1 / drift 0，`verdict=stable`；`ai-platform/backend/scripts/out/probe/p1_stability_all.json`
- 单产物：`GET /projects/9/export-stability?requirement_id=30&limit=50` → artifacts 1 / identical 1，artifact 68 的 `replay_sha256 == stored_sha256`；`ai-platform/backend/scripts/out/probe/p1_stability_req30.json`
- 复核清单：`GET /projects/9/replay-manifest` → 49 = 可复核 10 + 仅旧渲染器 38 + 不支持重放 1，`matched=49`；`ai-platform/backend/scripts/out/probe/p1_replay_manifest.json`
- T_8_1 回归：`POST /projects/9/requirements/10/exports`（draft_snapshot 25）→ artifact 69 / 12375 B / 35 行 × 56 列，分组标题与 8 个数据行编码与 v9 一致；`ai-platform/backend/scripts/out/probe/p1_t81_regression.json`
- 真实浏览器：`ai-platform/frontend/scripts/browser_verify_mainline_t51.mjs` → `ai-platform/frontend/scripts/out/browser/ui-mainline-t51.json`、`ui-t51-workspace.png`、`ui-t51-export-preflight.png`、`ui-t51-export-identity.png`；18 张字段卡编码逐个断言、场景下拉 4 项、下载 16650 B 且 sha 一致、`consoleErrors=[]`
- 页面横幅（非 console 错误）：`前后端发布标识不一致（app_commit:unknown；build_time:unknown），请联系运维核对本次发布。`；`failedRequests` 15 条全为 `net::ERR_ABORTED`（切表/换需求时前端主动取消旧请求）
"""

CHECKPOINT = """## 98. round 74 收尾：目标表 T_5_1 主线

- 做了什么：把 `T_5_1 产品业务基本信息` 从跑批脚本 `YBT_T_5_1.sql` 一路跑到冻结导出——脚本预览
  （4 语句/1 目标表/75 规则）、一键建需（rid 30、18/18 字段、16 条集市映射）、生成 36 项（33 完成/3 阻断）、
  批量采纳（content_version 2→3）、冻结草稿快照 44 + 产物 68（16650 B）。
- 关键改动：`document_content` 读时补 `scenario_groups`（与哈希入口同一处，保证冻结可重放）；
  导出渲染器升到 `survey-requirement-doc-v10`，场景优先分组（业务口径 6 列 + 溯源 9 列成对），
  无场景数据时回退来源系统分组；结构检查契约 v10 起按位置成对；三个基础表头去掉换行与示例逐字对齐。
- 真实结论：T_5_1 导出 47×56、3 个场景组（借记卡/信用卡/代销理财），与示例第 11 行前 11 列逐字一致，
  差异 13 条（表级取值 6、列组内重复 3、分组 1、列名/编码/非空率 3），每条在 `doc_compare.md` 里有为什么/下一步。
- 阻断如实记录：三级审批**没走通**——`review-readiness` 589 项阻断（scope 125 / candidate 344 / 每字段 120），
  项目 9 四条需求全部不可送审，`formal_delivered=0`。用假说明批量关缺口等于伪造审批，不做。
- 测试：survey 相关 43 passed；内容管线相关 60 passed；真实浏览器 `ok`、`consoleErrors=[]`；
  `export-stability` 该产物 identical，`replay-manifest` 49 = 10+38+1。

## 99. round 74 之后：从哪里接着做

- 优先补"未核验上游元数据"（91 条）与"缺少来源到集市字段的加工映射"（16 条）：它们来自脚本血缘证据链，
  是 589 项里最可能自动化补齐的部分；字段级"缺少业务定义"（如 981/983）只能靠人工口径。
- 缺口清到 0 后再走送审 + 三岗审批 + finalize，用真实账号。注意 `validate_review_decision` 的
  "内容维护人不能审自己"与角色无关：单一管理员即便清空缺口也过不了 business/technical 两步。
- 逐列对齐还差：目标表元数据（theme/filing_note/reporting_domain_*）、表号/主题编号、场景数从 3 补到示例的 10、
  采集范围/报送范围/EAST差异按场景拆分、人工确认人/截图列的真实来源。
- 未做：正式交付（审批不可达）、按条线拆多组与 comstar 8 列窄组、表级 3 行按场景重复写。
- 交接：改动仍在 `dsh/handoff-20261025-round73` 工作区，新增脚本 `_probe_*` / `_patch_*` 为一次性工具，可删。
"""

PLAN = """### 7.76 目标表 T_5_1 端到端（round 74）

**动机**：主线只在别的表上验证过，`T_5_1` 连需求都没有；"脚本能跑通"与"真实表能交付"是两件事。

**做法**：脚本预览（`YBT_T_5_1.sql` v32 → 4 语句/1 目标表/75 规则）→ 一键建需（rid 30、18/18 字段）→
生成 36 项（18 字段 × business/lineage）→ 逐个核对后一次批量采纳（v2→v3）→ 冻结草稿快照 44 + 导出产物 68。

**验收**：`t51_survey_v10.xlsx` 47 行 × 56 列、3 个场景组（借记卡/信用卡/代销理财，每组 6+9 列）；
sha `958e91c8…`；导出身份面板写"快照 #44（内容未变，复用已有快照）· 产物 #68"；
稳定性核对该产物 `identical`，复核清单 49 = 10+38+1。

**边界**：生成有 3 条阻断（2 条引用范围外物理字段、1 条主张与固定事实冲突），不采纳、不重试掩盖；
三级审批被 589 项数据治理缺口挡在门外，本轮交付是草稿快照，不是正式交付（详见
`real-run-20261024.md` §81）。

### 7.77 与客户示例逐列比对（round 74）

**动机**：客户示例是 328 列的成品文档，"看起来像"不等于逐列对得上；差异必须能逐条解释。

**做法**：新增只读比对脚本 `backend/scripts/requirement_doc_compare.py`，比表级 6 行、第 10 行组名、
第 11 行列名、数据行编码、每列非空率，输出 `doc_compare.json` + `doc_compare.md`（逐条为什么/下一步）。

**验收**：前 11 个基础列名逐字一致；场景交集 3（借记卡/信用卡/代销理财）；13 条差异分四类且全部有解释
（表级取值 6、列组内重复 3、分组 1、列名/编码/非空率 3）。

**下一步**：补目标表元数据与表号编号、场景从 3 补到 10、采集范围/报送范围/EAST差异按场景拆分。
"""

MATRIX = """### 8.58 场景优先分组的导出

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 按场景分列（业务口径 6 列 + 溯源 9 列成对） | 已实现、真实导出验证 | `requirement_survey_export.py` v10；T_5_1 导出 3 组、56 列 |
| 场景数据进冻结内容、可重放 | 已实现、哈希入口统一 | `requirement_scope.py` 的 `document_content` 补 `scenario_groups`；快照 44 内含 3 组 × 18 字段 |
| 无场景数据回退来源系统分组 | 已实现、回归验证 | T_8_1 v10 与 v9 结构一致（35 行 × 56 列、8 个组标题、8 个数据行） |
| 同一字段多场景并列 | 已实现 | 每场景一列组，18 字段 × 3 组 |
| AI 草稿必须可见标记 | 已实现、用例锁定 | 前缀"（AI 生成草稿，待业务确认）/（AI 生成草稿，待技术确认）" |
| 同场景按部门/条线再拆多组 | 未做 | `doc_compare.md` 的 `group_titles` 差异 |
| comstar 类 8 列窄组 | 未做 | `doc_compare.md` 的 `group_titles` 差异 |
| 表级采集范围/报送范围/EAST差异按场景重复写 | 未做 | `table_row_extra.*` 三条差异 |

### 8.59 审批阻断下能交付什么

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| 冻结草稿快照（不依赖审批） | 已实现、真实验证 | 快照 44、产物 68；`freeze-and-export` 200 |
| 正式交付（三级审批 + finalize） | 本环境不可达 | `review-readiness` 589 项；`formal_delivered=0` |
| 审阅级校验无豁免通道 | 已实现 | `review_readiness` 任一条 reason 即 `eligible=false` |
| 内容维护人不能自审 | 已实现 | `validate_review_decision` 命中即 409 |
| 缺口只能补内容、不能用说明关字段类缺口 | 已实现 | `resolve_gap`（字段类缺口禁止说明关闭） |
| 送审哈希与冻结哈希区分 | 已实现 | 送审用 revision 哈希、冻结用 `current_content_hash`；用错即 409 |
"""

APPENDS = [
    ("real-run-20261024.md", "## 79. round 74", REAL_RUN),
    ("evidence-index.md", "## 102. round 74", EVIDENCE),
    ("checkpoint.md", "## 98. round 74", CHECKPOINT),
    ("plan.md", "### 7.76", PLAN),
    ("capability-matrix.md", "### 8.58", MATRIX),
]


def main() -> int:
    for name, anchor, text in APPENDS:
        path = BASE / name
        raw = path.read_bytes().decode("utf-8")
        if anchor in raw:
            print(f"skip {name}: anchor already present")
            continue
        if not raw.endswith("\n"):
            raw += "\r\n" if raw.endswith("\r") else "\n"
        block = text.strip("\n")
        block_crlf = block.replace("\r\n", "\n").replace("\n", "\r\n")
        # 保持文件原有 CRLF 行尾，避免整文件行尾改写
        path.write_bytes((raw + "\r\n" + block_crlf + "\r\n").encode("utf-8"))
        print(f"appended {name}: +{len(block.splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
