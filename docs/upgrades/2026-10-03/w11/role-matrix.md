# W11 角色矩阵（2026-10-05 填写：隔离环境合成工程）

本表由**实际执行记录**填写，不是模板。环境：隔离库 `ybt_iso_phase4_synthetic` + 隔离后端 `127.0.0.1:8010`。
**这些是合成验收账号，不是银行真实人员。**

## 1. 四个角色职责账号（同一人不得兼写与审核）

| 角色 | 所需权限（平台） | 姓名 | 账号（合成） | 完成时间 | 签署/审核 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 业务分析 | `project.view` + 业务/字段编辑 | 合成-业务分析 | `p4_business_analyst` | 2026-10-05 | 需求范围与字段口径编写 | 业务口径填写与人工编辑 |
| 技术分析 | 同上＋技术口径 | 合成-技术分析 | `p4_technical_analyst` | 2026-10-05 | 脚本依据、路径确认、制度对照 | 数据来源与映射 |
| 审核（业务/技术/终审） | `review.*`（不得与编写人相同） | 合成-业务审核 / 合成-技术审核 / 合成-终审 | `p4_business_reviewer` / `p4_technical_reviewer` / `p4_final_reviewer` | 2026-10-05 | 三级审核**各自独立通过** | 与编写人不同 |
| 审计 | `audit.read`（＋只读巡查） | 合成-审计 | `p4_auditor` | 2026-10-05 | 只读巡查 | 只读，不参与写入 |

> 另有平台运维账号 `p4_platform_admin`（`institution_admin` @ `platform_operator` 机构），
> 用于系统管理页（机构/用户/角色/平台健康），不参与业务口径编写。

## 2. UAT 签署角色（`POST /api/uat-runs/{run_id}/signoff`）

| 签署角色 | 所需项目角色 | 姓名 | 时间 | 证据（`evidence_hash`） |
| --- | --- | --- | --- | --- |
| `business_owner` | business_reviewer / project_manager | 合成-业务审核（user 3） | 2026-10-05 | `193f0e7afe228150…`（**已批准**） |
| `technical_owner` | technical_reviewer / project_manager | 合成-技术审核（user 7） | 2026-10-05 | `193f0e7afe228150…`（**已批准**） |
| `project_manager` | project_manager | 合成-项目经理（user 6） | 2026-10-05 | `193f0e7afe228150…`（**已批准**） |
| `final_acceptance` | final_reviewer / project_manager | 合成-终审（user 4） | 2026-10-05 | `193f0e7afe228150…`（**已批准**） |

**两个角色签署绑定同一 `evidence_hash`**，与轮次 `manifest_json` 冻结的发布身份一致 —— 这正是 N05
（签署与冻结证据一致性）要保证的：签署不是对“当时的页面”负责，而是对某个确定证据快照负责。

### ⚠ 未达成（不得当作通过）

- **四个签署角色已全部批准**（`business_owner`/`technical_owner`/`project_manager`/`final_acceptance`），
  且均绑定同一 `evidence_hash`。
- 银行侧尚**未指定**签署人；本表账号为合成验收账号。

## 3. 每个 UAT 轮次绑定（缺失任一项视为无效）

轮次 1（`合成工程验收轮次`，suite 1，`isolated-synthetic`）：

| 项 | 取值 |
| --- | --- |
| 执行环境 `environment_name` | `isolated-synthetic` |
| 应用 commit（`GET /api/version`） | `9b5d00cada0b640aaa139aa5d234f064d9e11f25` |
| 构建时间 | `2026-10-04T13:29:05Z` |
| 迁移 head（`schema_head`） | `null`（隔离库无 `alembic_version`；`application_version = schema:None`） |
| 发布摘要（manifest） | 已冻结（`manifest_version`/`frozen_at`/`request_id`/`run`/`release_identity`/`requirement`/`model_profiles`） |
| Skill / 模型版本 | `f02_synthetic_skill` v1（草稿）+ `synthetic-verification-model`（`mock/mock-model`） |
| 需求 `content_version` / `content_hash` | `22` / `933c2b4d0d1c2699b6ef7e0923ff7ea0c2507bb2cacabe26783fea47014092b1` |
| 知识文档版本 / 脚本版本 | `synthetic-regulation.txt` v1（active）；脚本 `synthetic/synthetic_loan.sql` v1（依据）→ v2（变更复核触发） |

**注意**：`git_commit_sha` 记录的是**当时运行的后端进程**所报版本（`9b5d00c`），
而交付代码 HEAD 为 `7656ed5`。两者的差异被前端发布横幅**主动检出并报告**，属 P1–P4 预期行为。
