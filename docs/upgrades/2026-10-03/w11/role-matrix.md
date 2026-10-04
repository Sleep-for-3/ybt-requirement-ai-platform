# W11 角色矩阵（模板，UAT 执行时逐行填写）

规则：四个角色**不得共用账号**；同一人不得既填写又审核（职责分离）。平台按**业务 permission**（而非管理员身份）
判定权限，因此普通审核人不需要管理员角色。

| 角色 | 所需权限（平台） | 姓名 | 账号（脱敏） | 完成时间 | 签名/工号 | 备注 |
| --- | --- | --- | --- | --- | --- | --- |
| 业务分析 | `project.view` + 需求/字段编辑 |  |  |  |  | 业务口径填写与人工采用 |
| 技术分析 | 同上（技术口径） |  |  |  |  | 技术溯源与映射 |
| 审核（业务/技术/终审） | `review.*`（审核任务） |  |  |  |  | 与填写人不同 |
| 审计 | `audit.read`（+ 只读核查） |  |  |  |  | 只读、留痕 |

## UAT 签署角色（`POST /api/uat-runs/{run_id}/signoff`）

| 签署角色 | 允许的项目角色 | 姓名 | 时间 | 结论 |
| --- | --- | --- | --- | --- |
| `business_owner` | business_reviewer / project_manager |  |  |  |
| `technical_owner` | technical_reviewer / project_manager |  |  |  |
| `project_manager` | project_manager |  |  |  |
| `final_acceptance` | final_reviewer / project_manager |  |  |  |

## 每轮 UAT 必须绑定（缺任一项该轮无效）

| 项 | 取值 |
| --- | --- |
| 环境名 `environment_name` |  |
| 应用 commit（`GET /api/version`） |  |
| 构建时间 |  |
| 迁移 head（`schema_head`） |  |
| 配置摘要（脱敏） |  |
| Skill / 模型版本 |  |
| 需求 `content_version` / `content_hash` |  |
| 知识文档版本 / 脚本版本 |  |
