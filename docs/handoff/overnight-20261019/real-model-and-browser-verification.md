# 真实模型效果验证与真实浏览器验证 — 2026-10-20

> 本文件补上 2026-10-19 夜间开发报告中明确标注为「未验证」的两项：
> **真实模型效果** 与 **真实浏览器前端**。
> 全部数字来自本次实跑；仍属未验证的部分单列在第 6 节。

---

## 1. 结论速览

| 项 | 结果 | 判定 |
|---|---|---|
| 真实模型连通性 | `HTTP 200`，`deepseek-v4-flash`，profile id=4 | **PASS** |
| B 包：真实模型裁判接入答案状态 | 4/4 用例走真实判定，状态正确降级 | **PASS** |
| C 包：真实模型重排 | 2/2 用例 `model_rerank`、`coverage=full`、15/15 候选 | **PASS** |
| 真实调用审计 | 产品自身 `ModelCallLog` 记录完整（6 次调用、真实 token） | **PASS** |
| 真实浏览器（系统 Chrome） | 16/16 检查通过，页面正常渲染，无相关 404 | **PASS** |
| 计数器语义一致性 | 修复 3 处真实缺陷（见第 4 节） | **PASS** |

---

## 2. 真实模型验证（provider 真实、数据库真实、检索真实）

### 2.1 环境与预算（硬上限，非推断）

```
provider : LLM_BASE_URL=http://47.101.159.7:29988/v1  model=deepseek-v4-flash
profile  : id=4「公司网关 DeepSeek-V4-Flash（真实模型）」provider_type=openai_compatible
database : PostgreSQL 127.0.0.1:5432 / ybt_dsh_handoff_v2（12 个项目、6108 个知识单元）
project  : 1（外发白名单 1,5,9,12 之一；5928 个启用知识单元）

上限：调用 ≤24 次、墙钟 ≤900s、token ≤220000；任一耗尽即停止并报告覆盖数
```

### 2.2 B 包：引用支撑（真实裁判）

| 观测 | 值 |
|---|---|
| 请求 / 执行 / 未运行 | 4 / 4 / 0 |
| 真实调用数（`ModelCallLog`） | 4 |
| 真实 token（`ModelCallLog` 合计） | 16157 |
| 墙钟 | 79.3 s |
| 单次延迟 | min 4.4 s / p50 ≈ 7.3 s / max 40.4 s |
| 使用真实裁判 | 4 / 4 |
| 降级（degraded） | 0 |

逐例：

| 用例 | `answer_status` | `verification` | 主张已判/总数 | 主张覆盖率 | 维度 | 引用覆盖率 | 引用 支持/不支持 |
|---|---|---|---|---|---|---|---|
| 客户证件类型填报要求 | needs_confirmation | partially_supported | 0/4 | 0.0 | citation_level | 1.0 | 3 / 2 |
| 大额风险暴露口径 | needs_confirmation | partially_supported | 0/7 | 0.0 | citation_level | 1.0 | 5 / 0 |
| 理财产品适当性 | needs_confirmation | partially_supported | 0/3 | 0.0 | citation_level | 1.0 | 5 / 0 |
| 流动性覆盖率 | needs_confirmation | **unsupported** | 0/1 | 0.0 | citation_level | 1.0 | 1 / **4** |

**关键验证点**：最后一行 4 条引用被判**不支持**，答案被正确判为 `unsupported` 并降级为
`needs_confirmation`。这正是 B 包要解决的问题——改前该场景会显示 `grounded` + `high`。

### 2.3 C 包：字段重排（真实模型）

| 观测 | 值 |
|---|---|
| 请求 / 执行 / 未运行 | 2 / 2 / 0 |
| 真实调用数（`ModelCallLog`） | 2 |
| 真实 token | 20797 |
| 墙钟 | 32.5 s |
| `ranking_mode` | `model_rerank`（2/2） |
| `coverage` | `full`（2/2） |
| 真实模型名 | `deepseek-v4-flash` |

逐例：

| 目标字段 | recalled | admitted | model_evaluated | coverage | 延迟 |
|---|---|---|---|---|---|
| CERT_TYPE | 15 | 15 | **15** | full | 16.8 s |
| CUSTOMER_ID | 15 | 15 | **15** | full | 15.7 s |

对比改前（Mock profile 受限窗口下）：`recalled=15 → admitted=3 → model_evaluated=3`，
第 8/15 位候选从未被模型看过。

### 2.4 审计链交叉验证

真实调用次数与 token 由**产品自身**的 `ModelCallLog` 读取，不依赖我的进程内计数器：

```
skill_key=regulatory_field_explanation  kind=real_model  status=success  model=deepseek-v4-flash
skill_key=field_semantic_matching       kind=real_model  status=success  model=deepseek-v4-flash
```

这比自建包装器更权威：`ai_skills.runtime` 在 import 时绑定了工厂名，进程内包装器漏记了
重排调用（曾观察到 `calls_made=0` 而实际发生 3 次调用），因此改为与 `ModelCallLog` 对账。

---

## 3. 真实浏览器验证（系统 Chrome + 真实前后端）

### 3.1 环境

```
浏览器   : 系统 Google Chrome（Playwright channel="chrome"，headless）
前端     : Next.js 15.5.27 dev server @ http://127.0.0.1:3000
后端     : FastAPI uvicorn @ http://127.0.0.1:8000
数据库   : PostgreSQL（真实数据）
认证     : 真实登录 API 获取 token，注入 sessionStorage（键名与 lib/api.ts 一致）
```

结果文件：`docs/ux/acceptance/nightly-20261019/results.json`
截图：`01-ask-page.png`、`02-workspace.png`

### 3.2 检查项（16/16 PASS）

| 检查 | 结果 |
|---|---|
| 工作台页面渲染（标题「一表通字段口径智能辅助平台」） | PASS |
| 问答页暴露提问框 | PASS |
| 真实提问返回答案（HTTP 200） | PASS |
| 答案契约与当前开关状态一致 | PASS（`switch=judge, verification=partially_supported`） |
| 裁判覆盖率分母自洽 | PASS（`total=5, judged=0, dim=citation_level`） |
| 主张覆盖率不超过 1.0 | PASS（`coverage=0`） |
| 真实提问返回可用答案 | PASS（`answer_status=needs_confirmation`） |
| 开关关闭时页面无「已通过语义验证」字样 | PASS |
| 真实调用后页面无 JS 崩溃 | PASS |
| 重排接口响应正常 | PASS（HTTP 200） |
| 每个返回候选都带 `rank_source` | PASS（15/15） |
| 经模型评估的候选标记为模型排序 | PASS（model=15） |
| 未评估候选绝不标为模型排序 | PASS（unevaluated=0） |
| 调用方可见 `coverage` | PASS（`full`，`unranked_ids=[]`） |
| 无意外控制台错误 | PASS |
| 被测页面/API 无 404 | PASS（0 条相关 404） |

### 3.3 页面实测观察

- 登录态生效：右上角显示「Smoke 管理员」，项目选择器显示
  「E2E 多源多集市一表通实战…」。
- 问答页中文文案完整（「监管知识问答」「查询历史口径（答案会明确标记历史资料）」等）。
- 顶部提示「前后端发布标识不一致（app_commit=unknown; build_time=unknown），请联
  系运维核对本次发布」——**这是 dev server 的已知提示，不是本次改动引入**，生产构建会写入
  真实标识。

---

## 4. 本次验证中发现并修掉的 3 个真实缺陷

真实数据与真实模型暴露了合成/Mock 验证看不见的问题。三处都已修复并有测试保护。

### 4.1 `claims_unknown` 超过 `claims_judged`

**现象**（真实数据）：`claims_total=7, claims_judged=5, claims_unknown=7` —— 判定的主张只有
5 条，unknown 却有 7 条，自相矛盾。

**根因**：`tally_verdicts(aligned_claims)` 把**未被裁判回答**的主张也计入 `unknown`，而它们是
`judged=False`。

**修复**：三个 verdict 计数只在 `judged_claims` 上统计；未判定的由 `claims_unjudged` 与覆盖率
表达。

### 4.2 `claim_coverage` 大于 1.0

**现象**（真实数据）：`claim_coverage` 出现 **1.25** 与 **2.5**。

**根因**：引用级回退模式下分子是「引用数」、分母是「主张数」，量纲不同。

**修复**：两者不可混除。引用级模式下 `claim_coverage=0.0`（确实没有主张级判定）、
分母为 0、维度标为 `citation_level`；引用覆盖率单列 `citation_coverage`。同时给出
`claim_coverage_numerator/denominator` 便于复核。

### 4.3 引用级判定被误判为 `verified`

**现象**：`claims_judged=0`、`claims_unjudged=5`，但 `verification=verified` —— 等于告诉用户
「每条结论都核实过了」，而实际一条主张都没被判。

**根因**：`_verification()` 只看 `claim_coverage`，而该值当时被错误地用引用覆盖率填充。

**修复**：`_verification()` 增加 `claim_judgement` 维度判断，并把它排在通用零覆盖率规则
**之前**——引用级判定最多只能到 `partially_supported`（有不支持引用时到 `unsupported`），
绝不可能是 `verified`。

判定矩阵（已实测）：

| 情形 | 结果 |
|---|---|
| `citation_level`，无 unsupported | `partially_supported` |
| `citation_level`，有 unsupported | `unsupported` / `partially_supported` |
| `claim_level`，全覆盖且全支持 | `verified` |
| `claim_level`，零覆盖 | `unknown` |
| 裁判失败 | `degraded` |

### 4.4 附带修复：评测 harness 的桩泄漏（上一轮）

`_AnswerHarness` 重绑 8 个模块属性却只还原 3 个，导致后续测试拿到合成的 citation 字典。
已扩到全部 8 个。

---

## 5. 回归（真实模型改动后）

| 项 | 结果 |
|---|---|
| `test_rag_citation_support.py` + `test_overnight_citation_status.py` | **23 passed** |
| 加上 `test_evaluation_faithfulness.py` | **31 passed** |
| 真实浏览器验收 | **16/16 PASS** |
| 真实模型 B 包 | **4/4 执行，0 降级** |
| 真实模型 C 包 | **2/2 执行，coverage=full** |

---

## 6. 仍未验证 / 保持开放

| 项 | 原因 |
|---|---|
| **真实模型的排序质量（Top1/Top3 准确率）** | 本轮只证明「模型真的被调用且候选被真实比较」，**没有**经过人工标注的正确答案集，因此无法给出真实 Top1/Top3 指标 |
| **真实引用蕴含量化的准确率/召回率** | 同上：判定确实由真实模型作出，但没有独立标注真值来算准确率 |
| PostgreSQL 之外的组件 | Redis/Celery/Milvus 未参与真实队列与向量检索验证 |
| 浏览器端到端覆盖率 | 只覆盖工作台与问答页的加载与关键接口；未覆盖全站所有页面 |
| judge 开启后的生产成本 | 单次真实调用约 2.5k–7k token；未做长期成本评估 |
| `CITATION_SUPPORT_CHECK` 生产取值 | 本轮为验证临时置 `judge`，**已恢复为出厂默认 `off`** |

---

## 7. 如何复现

```powershell
cd "C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform\backend"
$env:AUTH_MODE='optional'; $env:TASK_QUEUE_PROVIDER='inline'; $env:PYTHONIOENCODING='utf-8'

# 真实模型（B + C），带硬预算
..\backend\.venv\Scripts\python.exe ..\scripts\real_model_acceptance.py `
  --cases-citation 4 --cases-rerank 2 --out "..\..\_runs\real-model-verified.json"
```

```powershell
# 真实浏览器（需先启动 uvicorn :8000 与 next dev :3000）
cd ..\frontend
& "C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe" `
  scripts\real-browser-acceptance.mjs
```

开启真实裁判需在 `backend/.env` 加 `CITATION_SUPPORT_CHECK=judge` 并重启后端；
**验证后务必移除**，出厂默认是 `off`。
