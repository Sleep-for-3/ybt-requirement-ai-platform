# P1-C 黄金集：从“填个名字就算标注”到可证明的标注与真实执行边界

- 日期：2026-10-23
- 分支：`dsh/vnext-business-accuracy-20261021`
- 代码：`backend/app/services/evaluation/regulatory_golden.py`、`backend/tests/test_vnext2_golden_annotation.py`
- 证据：`docs/audit/VNEXT2_GOLDEN_REPORT-20261023.json`（脚本 `scripts/vnext2_golden_report.py`）
- 结论级别：**框架 `REAL_COMPONENT`；业务准确率 `UNVERIFIED`（无独立银行专家标注）**

## 1. 原来的问题

`dataset_summary()` 用“`reviewer_id` 非空”统计 `independent_labeled`。这等于承认：任何人（包括开发 Agent 自己）
在 JSON 里写一个字符串，就能把 60 例合成案例变成“已独立标注”。任务书 8.2 明确禁止这种做法，并要求区分
案例作者 / 预期答案作者 / 独立标注人 / 审核时间 / 标注依据 / 标注状态 / 争议处理 / 数据集版本。

## 2. 本轮实现的结构化标注

`GoldenAnnotation`（新增，向后兼容）：

| 字段 | 作用 | 校验 |
| --- | --- | --- |
| `case_author` | 写场景的人 | `accepted` 必须存在 |
| `expected_author` | 写预期答案的人 | `accepted` 必须存在 |
| `reviewer_id` | 独立标注人 | `accepted` 时必须不同于上面两人 |
| `reviewer_role` | 标注人角色（如监管数据专家） | 可选 |
| `reviewed_at` | 标注日期 | 必须 `YYYY-MM-DD` |
| `basis` | 标注依据（制度条款/字典/业务确认） | `accepted` 必须非空 |
| `status` | `draft / in_review / accepted / disputed / rejected` | 枚举校验 |
| `dispute_note` | 争议说明 | `disputed` 必须填写 |

判定规则：

- `verified = status == accepted 且独立性可证 且 reviewed_at 与 basis 非空`；
- 历史数据里只有一个顶层 `reviewer_id`（当前 60 例全为 `null`）时按 `draft` 处理，**不再**计入已标注；
- `accepted` 但作者=标注人、或缺依据/日期 → 加载即 `GoldenSetError`（不允许“先标上再说”）；
- `disputed` 必须写争议说明，且不计入 `verified`。

数据集级元数据写在 `vnext_golden_set_v1.json` 的 `annotation` 段：`dataset_version`（带 `+annotation-2026-10-23` 后缀）、
`defaults`（合成作者 `vnext2-synthetic-design-v1`）、`annotation_policy`。**只新增元数据，60 例的 `expected` 一字未改**
（`git diff --numstat` = 12 行插入 0 删除）。

## 3. 指标与真实性级别

- `evaluate_golden_set()` 现在额外返回：
  - `coverage`：按 kind 给出 `cases / scored / not_run / truth_level`；
  - 每个 metric 带 `truth_level`（`UNVERIFIED / PARTIALLY_VERIFIED / VERIFIED`）；
  - `dataset.annotation_status_counts`、`accepted_without_provable_independence`、`disputed_cases`、`case_authors`。
- `not_run` 的指标 `scored_cases=0`、`ratio=None`，不会被当成 0 分或 100 分。
- 当前报告（`VNEXT2_GOLDEN_REPORT-20261023.json`）：

  ```
  cases=60 label_status=UNVERIFIED independent_labeled=0
  field_retrieval cases=10 scored=0  not_run=10
  citation        cases=10 scored=0  not_run=10
  document        cases=10 scored=0  not_run=10
  agent_decision  cases=20 scored=0  not_run=20
  delivery        cases=10 scored=0  not_run=10
  ```

## 4. 真实执行覆盖：做到了什么、没做到什么

| 案例族 | 本轮状态 | 说明 |
| --- | --- | --- |
| C 引用证据 10 例 | 有过真实模型执行（P0-B，10/10 与合成期望一致），但**未**回灌本报告 | 该次运行是引用裁判专项（`docs/audit/VNEXT_CITATION_TRUST-20261022.json`），与黄金集 case id 未做一对一映射，不能直接算作黄金集分数 |
| A/B/D/E/F 50 例 | `not_run` | 案例只有期望状态/候选 id，没有可直接执行的 SQL、知识库或需求夹具；要真实执行需要为每例准备元数据与运行环境 |
| SQL 语义 | 真实执行在 P1-B 单独完成 | `docs/audit/VNEXT2_SQL_DIALECT_MATRIX-20261023.json`：15 解析 + 8 变化用例与期望 15/15、8/8 一致（合成期望，非专家真值） |
| 正式交付 | 真实执行在 P0-C 完成 | 后端真实链路 + 浏览器 66 步闭环；属“至少一例可复现”，不是黄金集 10 例全跑 |

因此本轮**不宣布**任何“监管准确率 ×%”。`label_status=UNVERIFIED` 是产品的真实状态。

## 5. 回归

```powershell
cd ai-platform\backend
$env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"
.\.venv\Scripts\python.exe -m pytest tests/test_vnext2_golden_annotation.py tests/test_vnext_regulatory_golden.py -q
# 19 passed
.\.venv\Scripts\python.exe ..\scripts\vnext2_golden_report.py
```

新增 8 例覆盖：旧 `reviewer_id` 不算标注、自我标注被拒、缺依据/日期被拒、独立 accepted 计为 `PARTIALLY_VERIFIED`、
`disputed` 需争议说明且不计数、未执行指标 `not_run` 且 `ratio=None`、只有执行的族才计分、60 例家族分布与合成作者不变。

## 6. 剩余缺口

1. 需要真实银行专家按 `annotation` 结构给出 `accepted` 标注，才能把 `truth_level` 从 `UNVERIFIED` 提升；
   这属于外部人工资源，不在本轮可伪造范围。
2. 要把 citation / field_retrieval 等族真实执行并回灌 `observations`，需要为每例准备数据库夹具与模型预算，
   建议下一轮按“每轮 1 个案例族”推进，而不是一次性全跑。
3. 指标公式的任何调整都必须在 `dataset_version` 与报告里留痕，旧结果不得直接对比宣传。
