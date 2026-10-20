# 2026-10-19 夜间开发计划（A/B/C/D 包）

## 1. 基线与范围

| 项 | 值 |
|---|---|
| 仓库 | Sleep-for-3/ybt-requirement-ai-platform |
| 工作区 | `C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform` |
| 分支 | `dsh/banking-semantic-agent-v2`（= origin/dsh/banking-semantic-agent-v2） |
| 起始 HEAD | `353420dc9f2bd6c8040e18769c4db9138aa13bdc`（2026-10-19 23:15:47 +0800） |
| 工作树状态 | 干净（`git status --porcelain` 无输出），未覆盖任何未提交修改 |
| 基线镜像 | `..\_baseline-353420d`（detached worktree，同 SHA，用于"改前"对照与原始缺陷复现） |
| 后端 Python | `backend\.venv\Scripts\python.exe`（3.12.14） |
| 前端 | `frontend\node_modules` 已就绪（Next 15.5.27） |

### 1.1 运行纪律（本任务硬约束）

- 不 reset --hard、不自动提交/推送/合并/发布、不删除业务数据、不改生产环境。
- 所有生成结果保持 draft/candidate；人工门未决 = `waiting_human`，不写成 `completed`。
- 不改变数据外发白名单，不把 confidential/restricted 伪装成 public；合成材料显式标记。
- 模型调用有上限；供应商不返回 usage 写 `unknown`，不填 0。
- 每包先写失败样本 → 修复 → 定向回归 → 自审 → 进入下一包。

### 1.2 本机测试环境事实（已核实）

- `backend/.env` 为空环境产物：`AUTH_MODE=required`、`TASK_QUEUE_PROVIDER=celery`。
  跑 pytest 必须先 `$env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'`。
- pytest 是 SQLite + Mock provider（`tests/conftest.py` 强制 `LLM_PROVIDER=mock` 等）。
  这不等于 PostgreSQL/Redis/Celery/Milvus 验证。
- 本机 PostgreSQL 5432 / Redis 6379 **监听中**；真实模型端点 `47.101.159.7:29988` 可达但
  返回 401（需要 `backend/.env` 里的 `LLM_API_KEY`，该 key 存在但未在本次计划中授权无上限付费评测）。
- `pytest-timeout` 未安装：不得使用 `--timeout` 参数。

## 2. 工作包与优先顺序

| 包 | 内容 | 优先级 | 负责人（写作用域） |
|---|---|---|---|
| A | 业务评测基线：版本化数据集 + 逐例运行器 + 改前/改后对照 | P0，贯穿全程 | Lead（`backend/tests/overnight_eval/`、`scripts/overnight_eval/`） |
| B | 引用支撑结果接入答案状态、可信度与界面 | P0，第一功能包 | teammate `citation`（rag/*、frontend ask、rag_evaluator、相关测试） |
| C | 重排预算优化，并验证排序质量 | P1，第二功能包 | teammate `rerank`（`ai_skills/field_rerank.py`、`runtime.py`、`field_candidates.py`、相关测试） |
| D | SQL 语义变化归因扩展 | P1 加做 | 仅 A/B/C 定向验证通过且仍有验收时间时开始；否则保留为下轮首项 |

### 2.1 写作用域（避免并行冲突）

- **Lead 独占**：`backend/app/core/settings.py`、`backend/app/schemas/*`、
  `docs/handoff/overnight-20261019/*`、`docs/upgrades/2026-10-19/*`。
- **citation（B）**：`backend/app/services/rag/grounded_answer_service.py`、
  `backend/app/services/rag/citation_support.py`、`backend/app/services/rag/citation_validator.py`、
  `backend/app/services/evaluation/rag_evaluator.py`、`backend/tests/test_rag_citation_support.py`、
  `backend/tests/test_evaluation_faithfulness.py`、`frontend/app/knowledge/ask/page.tsx`、
  `frontend/lib/knowledge-types.ts`、`frontend/lib/knowledge-contract.mjs`、`frontend/tests/*.mjs`。
- **rerank（C）**：`backend/app/services/ai_skills/field_rerank.py`、
  `backend/app/services/ai_skills/runtime.py`（只改预算接口）、
  `backend/app/services/ai_skills/field_candidates.py`、
  `backend/tests/test_ai_skill_rerank_*.py`、`backend/tests/test_ai_skill_field_rerank.py`。
- 两位队友之间**不得**修改对方作用域内的文件；需要跨域改动一律交回 Lead。

## 3. 验收标准

1. **A**：≥30 个高质量种子场景并扩展到约 120 例（6 类 × 约 20 例），每例记录
   `case_id / 来源类型 / 任务输入 / 可用证据 ID 与版本 / 预期行为 / 禁止行为 / 判分规则 / 样本组`；
   固定数据集内容哈希；开发集 80% / 保留集 20%；跑**真实入口**并保存逐例结果；
   分别统计检索、重排、引用支撑、拒答/澄清、任务成功率、人工门状态正确率、延迟与 token，
   明确分母与未运行数量。
2. **B**：引用 unsupported 的关键主张不再以 grounded/high 呈现；judge 超时/解析失败/漏判/覆盖不足
   明确 unknown/degraded 并输出覆盖率；重复 verdict、未知 ID、乱序不错配；超上限有界分批或显式未覆盖；
   前端用中文说明哪些结论有依据、哪些无法验证、为何降级；开关开/关两条路径均兼容。
3. **C**：正确候选在初排第 8/15/20 位时仍获得实际模型比较机会；白名单外 ID 为 0；
   未评估候选不冒充已评估；跨批比较不用未校准自报分数；总调用/token/墙钟有界；
   兼容既有返回结构。
4. **总验收**：定向回归 + 全量后端回归 + 前端 `node --test` + `tsc --noEmit`；审核最终 diff。

## 4. 交付物

`docs/handoff/overnight-20261019/`：
- `plan.md`（本文件）
- `checkpoint.md`（每包完成或约 45 分钟更新）
- `results.json`（代码 SHA、数据集哈希、逐例结果、退出码、指标分母、失败/跳过/阻塞、模型调用与 token）
- `final-report.md`
- `failure-cases/`（最小复现输入与期望；仅合成材料）

结果按四类分开：静态确认 / 确定性·Mock 已验证 / 真实组件已验证 / 真实模型效果已验证。

## 5. 预算

- 规划约 8 小时（含至少 1 小时验收与交接），以执行端实际限额为准。
- 真实模型调用：本轮**默认不发起**付费评测（未获新增预算授权）；仅复用既有授权 provider
  既有配置做 Mock/合成材料与本地组件验证，并在 results.json 标注"真实模型效果未验证"。
- 编码 harness 自身 token 与平台测试 token 分开统计（本文件不混算）。
