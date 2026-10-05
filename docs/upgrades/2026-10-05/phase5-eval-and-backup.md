# 第五阶段（第一批）：版本化评测数据集验收 + 完整备份恢复演练

本轮（2026-10-05）对应《DSH下一轮开发提示词-2026-10-05》第 5 条的前两项：**版本化数据集/标注复核/批量重跑/失败样本对比**，以及**完整备份恢复**。两项均在**隔离环境 + 合成数据**上以真实组件执行，并明确标注未达成的银行侧前置条件。

## 1. 版本化评测数据集：`phase5_evaluation_dataset.py`

隔离库 `ybt_iso_phase5_eval`（N13 守卫在 DDL 前校验；业务库被拒）。命令：

```
python docs/upgrades/2026-10-05/phase5_evaluation_dataset.py --allow-reset-existing --report <path>
```

**结果：`{"ok": true, "steps": 8}` / `EXIT=0`**

| 步骤 | 证据 | 证明什么 |
| --- | --- | --- |
| `dataset_created` | 6 个合成用例，`dataset_version=948577a8c5f8ed7e…` | 数据集有**确定性版本**（`_dataset_version` = 用例 id+查询哈希+期望集合的 SHA-256） |
| `dataset_version_tracks_content` | 修改一条 `query_text` → `302f2c73328d4a20…`（前值 `948577a8c5f8ed7e`） | 版本**随内容变化**，因此报告里的分数可绑定到确切输入，不能用旧版本号复用 |
| `annotation_review_excludes_disabled_cases` | 停用 1 条 → 版本变为 `07b7c7f38e30b866`，活跃用例 5 | **标注复核生效**：被复核剔除的样本不再影响指标 |
| `first_run` | run 1，`status=completed`，6 条用例结果 | 真实评测器可跑通并逐用例留痕 |
| `batch_rerun` | run 2，`status=completed`，6 条用例结果 | **批量重跑**可执行 |
| `rerun_uses_the_same_dataset_version` | 两次运行 `dataset_version` 相同 | 重跑绑定同一数据集版本，分数变化才能归因 |
| `failure_samples_compared` | 两次均 3 个失败样本，`newly_failing=[]`、`fixed=[]` | **失败样本按 case_id 对齐比较**，而不是只看总分 |

## 2. 完整备份恢复演练：`phase5_backup_restore.py`

现有 `w09_backup_plan.py` 只做备份且明确声明"本工具不执行恢复"，因此本轮补上**恢复验证**。
隔离库 `ybt_iso_phase5_backup` → 全新库 `ybt_iso_phase5_backup_restore`（两个库名都先过 N13 守卫）。

**结果：`{"ok": true, "steps": 7}` / `EXIT=0`**

| 步骤 | 证据 |
| --- | --- |
| `seeded_source` | 已知数据：institutions 1 / users 12 / memberships 12 / projects 1 / rag_evaluation_cases 20，内容摘要 `ab8f010ccc8b5025` |
| `backup_taken` | 真实 `pg_dump -Fc`：**946,522 字节**，SHA-256 `d9d3a5fc8aed2e21…`，耗时 **0.295s**；目录名为 `release-<db>-<UTC 时间戳>-<PID>`（不可覆盖） |
| `backup_artifact_unchanged` | 重新计算 SHA 与记录值一致（防静默损坏） |
| `restore_into_fresh_database` | `pg_restore` 到**新建空库**成功，耗时 **2.384s** |
| `row_counts_match` | 5 张表源/恢复行数**逐一相等**，`mismatched={}` |
| `content_digest_match` | 源与恢复库内容摘要相同（`ab8f010ccc8b5025`） |
| `measured_rto_seconds` | 实测 dump 0.295s / restore 2.384s（**实测值**，未与银行约定目标比对） |

## 3. 未达成 / 待验收条件（不得当作通过）

1. **真实银行评测真值、业务阈值、身份未接入** —— 本轮只用合成用例验证框架；指标的"准确性"结论不成立。
2. **embedding / LLM 走 mock**（`VECTOR_STORE_PROVIDER=mock`、`LLM_PROVIDER=mock`），指标不代表生产检索质量。
3. **未在生产规模数据上演练备份恢复**；RTO/RPO 目标值由银行给出后才能判定是否达标。
4. **备份恢复只覆盖数据库一致性点**：对象存储（附件/正式交付对象）、Milvus 向量索引、配置副本的恢复未包含在本脚本。
5. **未做真实多 worker 故障恢复与容量基线**（属第五阶段剩余项；本机约束见既有记录）。
6. 两个脚本均为**新增验收工具**，未修改产品代码；因此本轮不涉及产品行为变更。

## 4. 结论

第 5 条的"版本化数据集 + 标注复核 + 批量重跑 + 失败样本对比"与"完整备份恢复"两项已用**真实组件、真实 dump/restore、真实评测器**在隔离环境验证通过，并给出实测数值；银行侧前置条件（真值/阈值/身份/生产规模目标）如实列为待验收。
