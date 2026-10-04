# W11 代表性银行需求 UAT 执行包（模板 + 操作步骤）

状态：**待执行**（需运行实例 + 银行角色 + 真实样本）。本文件提供可直接照做的执行包模板与步骤，
使 W11 在环境就绪后一次性完成，不依赖我方的进一步设计。
依据：`DSH升级任务书-2026-10-03.md` W11；平台既有 UAT 能力（见下方端点）。

## 1. 样本要求（验收起点，不是容量承诺）

至少 **8 个字段**、**2 个来源表**、**1 个集市表**、**1 个监管目标表**，覆盖：

| 覆盖点 | 说明 |
| --- | --- |
| 关联 | 多表 JOIN（含关联键与粒度一致性） |
| 聚合 | SUM/COUNT 等聚合口径 |
| 过滤日期 | 带业务日期过滤（含边界） |
| 码值 | 码值转换/映射 |
| 空值 | NULL 处理规则 |
| 多来源优先级 | 同一字段多来源的优先级与合并规则 |
| 手工补录 | 无自动来源时的人工补录分支 |

## 2. 角色矩阵（必须在 UAT 中分别完成并留痕）

| 角色 | 职责 | 平台入口 |
| --- | --- | --- |
| 业务分析 | 业务口径填写与人工采用 | 需求工作台 / 字段工作台 |
| 技术分析 | 技术溯源与映射 | 同上（技术口径） |
| 审核 | 独立审核（业务/技术/终审） | `/work`（审核与我的工作）→ 审核任务 |
| 审计 | 只读核查与留痕 | `/audit`、语义目录审计区（按业务权限呈现） |

> 权限口径：UAT 与审计按**业务 permission**（`uat.view`/`uat.manage`/`uat.execute`/`uat.signoff`、
> `audit.read`）呈现，**不要求普通审核人员成为管理员**（W06/B16 已实现）。

## 3. 执行步骤（对应 W11 七步）

1. **固定输入版本**：导入目标模板、目录、制度、源脚本；记录输入 manifest（见 §5）。
2. **生成候选与需求草稿**：展示依据与不确定性（缺口/冲突会以 gap 形式出现）。
3. **人工差异采用**：设置"缺证据、冲突、过期依据、人工修改"四类反例，确认被正确阻断
   （后端已强制：跨版本/过期候选 → 409；人工内容需显式替换；见 `test_requirement_candidate_adoption.py`）。
4. **四角色分别作业**，保持独立审批（职责分离；同一人不得既填又审）。
5. **冻结正式版本**：导出 Word/Excel；**回读正文与 hash**，人工核查版式。
6. **执行 UAT**：登记 Finding → 修复 → 重跑 → 完成所需角色签署。
7. **变更复核**：修改一个制度/脚本版本，核对受影响需求/审核/交付；**旧文件不变，新版本必须复核**。

对应平台端点（现有能力，勿另造）：

```
GET  /api/projects/{id}/uat-suites                  # 列出套件（8 类系统套件：端到端正式交付/知识与 Citation/元数据与来源字段/治理工作流/SQL 血缘与变更影响/Excel 忠实度/权限与安全/部署准备度）
POST /api/projects/{id}/uat-suites                  # 生成需求规则测试项（从确认规则）
POST /api/uat-suites/{suite_id}/runs                # 创建执行轮次（绑定 run_name/environment_name）
POST /api/uat-runs/{run_id}/execute | retry-failed | cancel
POST /api/uat-case-results/{id}/complete-manual     # 人工用例结果（含 expected/actual/conclusion）
POST /api/uat-case-results/{id}/attach-evidence
POST /api/uat-runs/{run_id}/findings                # 登记 Finding
PATCH /api/uat-findings/{id} ; POST /api/uat-findings/{id}/resolve | verify
POST /api/uat-runs/{run_id}/signoff                 # 角色签署（business_owner/technical_owner/project_manager/final_acceptance）
GET  /api/uat-runs/{run_id}/report                  # UAT 报告（xlsx）
GET  /api/uat-runs/{run_id}/evidence-package        # 证据包（zip）
POST /api/projects/{id}/uat-packs/upload | /validate # 银行侧 UAT 包导入与校验
```

## 4. 每轮 UAT 必须绑定的字段（禁止只填 "uat" 而留空应用版本）

| 项 | 来源 |
| --- | --- |
| 环境名 | `run.environment_name`（如 `uat-bank-01`） |
| 应用 commit | `GET /api/version` → `app_commit`（与前端/worker/beat 必须一致） |
| 构建时间 | `GET /api/version` → `build_time` |
| 配置摘要 | 部署时导出的配置指纹（脱敏，不含密钥） |
| 迁移 head | `GET /api/version` → `schema_head`（应等于 `202610030001` 或发布时的真实 head） |
| Skill / 模型版本 | 相关 Skill 定义与版本号、ModelProfile 名称与 `max_output_tokens` 等 |
| 需求 hash | 该轮绑定的需求内容 `content_hash` 与 `content_version` |
| 资料/脚本版本 | 知识文档版本与脚本版本（`script_version_id`） |

## 5. 交付物清单（缺任一项不得视为通过）

**可直接填写的模板**（本目录 `w11/`）：

- `w11/input-manifest.md` —— 输入 manifest（10 类输入，要求文件名 + 版本/日期 + SHA-256；含覆盖自检）
- `w11/role-matrix.md` —— 四角色矩阵 + UAT 四类签署角色 + 每轮必须绑定的 8 项
- `w11/evidence-checklist.md` —— 平台侧 / 业务侧 / 专家评价 / “不得发生”四段证据清单

- [ ] **输入 manifest**（模板/目录/制度/脚本的文件名 + hash + 版本）
- [ ] **角色矩阵**（§2，含实际操作人与时间）
- [ ] **操作证据**（关键页面/接口调用留痕；UAT 证据包 zip）
- [ ] **失败/阻断/复测记录**（Finding 列表：`new → resolved → verified` 全链路）
- [ ] **冻结的正式文件**（Word/Excel；含 `content_hash`，回读一致）
- [ ] **UAT 报告 + Finding + 各角色签署**（`/report` 与 `/signoffs` 导出）
- [ ] **业务专家评价**（准确率/证据有效性/无依据率/人工修订率，含分母与失败样本）

## 6. 硬性红线（违反即不通过）

1. **Agent `completed` 不能替代正式交付与 UAT 签署**；正式文件与签署缺一不可。
2. 不得为了让模型调用成功而**降低数据分级或扩大外发白名单**（项目 11 保持不在白名单）。
3. 不得使用**真实业务库**做破坏性/清库操作；UAT 数据须为受控样本或脱敏数据。
4. 不得删除/跳过/弱化既有测试，不得关闭 lint/安全扫描/权限/审核校验。
5. 业务准确率阈值须**试点前由银行专家明确**，不得事后用成功率替换。
6. 变更复核（第 7 步）必须证明**旧正式文件不变**、新版本走完复核。

## 7. 环境前置（执行前确认）

- 运行实例已发布（见 `RELEASE-RUNBOOK.md`）；`GET /api/version` 各组件一致；
- 前端实例健康（当前因 `.next` 缺 `BUILD_ID` 未运行，需先按 runbook §2 恢复/发布）；
- 已导入 ≥1 个代表性样本项目（§1）；
- 已准备四类角色的**独立**账号（不得共用）。
