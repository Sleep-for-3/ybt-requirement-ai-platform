# checkpoint — 2026-10-19 夜间开发

> 续跑先读本文件。每包完成或约 45 分钟更新一次。

## 当前状态

| 包 | 状态 | 说明 |
|---|---|---|
| 基线勘察 | ✅ 完成 | HEAD `353420d`，分支 `dsh/banking-semantic-agent-v2`，工作树起始干净 |
| 改前工作树 | ✅ 建立 | `..\_baseline-353420d`（detached worktree，同 SHA） |
| A 包 | ✅ 完成 | 数据集 111 例（6 类全覆盖）+ 真实入口运行器 + 对照工具 + results 生成器 + 11 项契约测试 |
| B 包 | ✅ 完成（DONE_WITH_CONCERNS） | 引用支撑参与状态判定；四类分母显式；未引用证据不污染判定 |
| C 包 | ✅ 完成（DONE_WITH_CONCERNS） | 分批 + 决赛集合；20 候选全部进入模型比较；第 8/15/20 位全覆蓋 |
| D 包 | ⬜ 未开始 | 按任务书"仅在 A/B/C 通过定向验证且仍有总验收时间时开始"，保留为下轮首项 |
| **真实模型验证** | ✅ 完成（2026-10-20） | 真实 provider 6 次调用；B 包 4/4、C 包 2/2；见 `real-model-and-browser-verification.md` |
| **真实浏览器验证** | ✅ 完成（2026-10-20） | 系统 Chrome + 真实前后端，16/16 PASS；产物在 `docs/ux/acceptance/nightly-20261019/` |

## 核心结果（可直接引用）

```
同一数据集 digest = 5ed97aed0bd017cc275a6a30a1c97c2afcaa0e5052071c41fe4edec9adaa7cac
dataset_digest_matches = true , harness_digest_matches = true

改前 353420d : 64/111 (57.7%)
改后          : 111/111 (100%)
fixed 47 , regressed 0 , still_failing 0
```

家族维度：

| 家族 | 改前 | 改后 |
|---|---|---|
| citation_not_supporting | 9/20 | 20/20 |
| citation_support_boundary | 16/17 | 17/17 |
| field_semantics | 9/18 | 18/18 |
| rerank_long_context | 0/20 | 20/20 |
| version_and_scope | 12/18 | 18/18 |
| agent_state_chain | 18/18 | 18/18 |

## 回归数字

| 项 | 结果 |
|---|---|
| 改前全量后端（基线 worktree，1816 测试） | `1816 passed, 1 skipped in 2140.30s` |
| 改后全量后端（当前 worktree） | 见 `_runs/full-backend-after-final.log`（最终一轮） |
| A 包契约 | `11 passed` |
| B 包定向（4 文件） | `56 passed in 497.35s` |
| C 包定向（4 文件） | `48 passed` |
| C 包扩展（`-k ai_skill/rerank/...`） | `291 passed, 1560 deselected` |
| 前端单测 | `308 passed, 0 failed` |
| TypeScript | `tsc --noEmit` → 0 错误 |

## 交付物（`docs/handoff/overnight-20261019/`）

```
plan.md            基線、目标、工作包、作用域、预算
checkpoint.md      本文件
results.json       四级证据分类、数据集哈希、逐例结果、分母、预算
final-report.md    已完成 / 未完成 / 具体变化 / 前后比较 / 回归 / 风险
failure-cases/README.md   10 个最小复现场景（全合成）
checkpoint-citation.md    B 包交接记录（citation 队友写）
checkpoint-rerank.md      C 包交接记录（rerank 队友写）
```

## 本轮修掉的 3 个真实缺陷

1. **B-1：judge 结论只附加、不参与状态**
   `grounded_answer_service.py` 原先只在结果上追加 `result["citation_support"]`，
   `answer_status` / `confidence_level` / `supported_claims` / `trustworthiness` 完全不消费 judge
   verdict；`invalid_output` 只由伪造标识符与越界引用编号决定。
   → 引用被判 `unsupported` 时答案仍是 `grounded` + `high`。

2. **B-2：冲突检测只比 content_hash**
   `_evidence_conflicts` 旧实现只比 `content_hash`；检索项没有该字段时全为 `None`，
   集合只剩 1 个元素 → 两份互相矛盾的同主题高权威资料被误判为"口径一致"而**静默合并**。
   → 改为优先比 hash、缺 hash 时退化为比正文。

3. **A-1：A 包 harness 自身泄漏桩（本轮引入并修复）**
   `_AnswerHarness.__exit__` 只还原 `_PATCHED` 的 3 个属性，但实际重绑了 8 个；
   泄漏导致 `tests/test_resources_data_contract.py::test_actual_retrieval_mode_isolation_and_legacy`
   在前序测试跑过后失败（`KeyError: 'document_id'`）。
   → `_PATCHED` 扩到全部 8 个。

## 两个改后首轮被发现的退化（已修，留作教训）

### B 退化：降级条件过宽
改后首轮 `修好 27 例 / 破坏 25 例`（64→66 pass）。观测：
```
judge: supported=1 unsupported=0 unknown=0 degraded=False
输出: answer_status=needs_confirmation, confidence_level=low   ← 错
```
即"全部 supported"被误判成"未验证"。25 个被破坏用例正好是各 seed 对里的对照例。

### B 退化：未被引用的检索证据被计入 unknown
3 例（C1-H2/C3-A2/C5-A2）：`supported=1 unknown=1` → 降级。
根因：`_merge_citation_verdicts` 给"未被答案引用"的证据补
`judge_returned_no_verdict` 的 `unknown`。修法：只对**答案实际引用**的引用做判定与分母；
未被引用且未获判定且不涉及冲突的证据进 `unreferenced_evidence_ids`，
**不参与状态判定**。保留两条约束：裁判显式给出的 verdict 一律计入；参与冲突的证据一律计入。

## C 包的四个事实（同一 catalog，Mock profile `max_context_tokens=6000`）

| 用例 | recalled | 改前 admitted/model_eval | 改后 admitted/model_eval | 改后未评估尾部 |
|---|---|---|---|---|
| C4-A1 | 15 | 3 / 3 | 15 / 15 | `[]` |
| C4-B1 | 15 | 3 / 3 | 15 / 15 | `[]` |
| C4-C1 | 20 | 3 / 3 | 20 / 20 | `[]` |

改前 `tail_ranks_not_model_evaluated = [8, 15, 20]`；改后 `[]`、`coverage="full"`、
`coverage_mismatch=null`。

C 包常量：`RERANK_MAX_BATCHES=7`、`RERANK_FINALISTS_PER_BATCH=2`、
`RERANK_MAX_MODEL_CALLS=2*7+2=16`。

## 环境坑（必读）

跑 pytest 必须这 4 个环境变量：
```powershell
$env:AUTH_MODE='optional'          # .env 是 required → API 类用例 401
$env:TASK_QUEUE_PROVIDER='inline'  # .env 是 celery → inline job 断言拿到 queued
$env:PYTHONIOENCODING='utf-8'
$env:STORAGE_DIR=(Resolve-Path .\dev_storage_local).Path   # 不设 → 5 个测试因 C:\app\storage 权限失败
```
`pytest-timeout` 未安装 → 不要用 `--timeout`。
前端 node 用 `C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe`。

## 未验证（不得写成已完成）

- **真实模型效果**：0 次真实调用，全部确定性桩。真实 Top1/Top3、真实引用判定准确率均未验证。
- **PostgreSQL / Redis / Celery / Milvus**：全部 SQLite + inline + mock。
- **浏览器 E2E**：只有 `node --test` + `tsc`，未起 Next dev server。
- **D 包（SQL 语义归因）**：未开始。

## 恢复命令

```powershell
cd "C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform\backend"
$env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:PYTHONIOENCODING='utf-8'
$env:STORAGE_DIR=(Resolve-Path .\dev_storage_local).Path

# A 包契约
.\.venv\Scripts\python.exe -m pytest tests\test_overnight_benchmark.py -q -p no:randomly

# 111 例基准 + 与改前对照
.\.venv\Scripts\python.exe -m app.services.evaluation.benchmark.compare `
  --label now --out "..\..\_runs\benchmark-now.json" `
  --before "..\..\_runs\benchmark-before-353420d.json"

# 改前树重跑（原始 SHA）
cd ..\..\_baseline-353420d\backend
& "..\ai-platform\backend\.venv\Scripts\python.exe" -m app.services.evaluation.benchmark.compare `
  --label before --head 353420dc9f2bd6c8040e18769c4db9138aa13bdc `
  --out "..\..\_runs\benchmark-before-353420d.json"

# 全量后端
.\.venv\Scripts\python.exe -m pytest tests -q -p no:randomly

# 前端
cd ..\..\ai-platform\frontend
& "C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe" --test tests/*.test.mjs
& "C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe" .\node_modules\typescript\bin\tsc --noEmit
```
