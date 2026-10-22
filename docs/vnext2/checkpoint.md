# VNext 2 检查点（docs/vnext2/checkpoint.md）

更新时间：2026-10-22 21:40（Asia/Shanghai）

## 当前状态

- 当前分支：`dsh/vnext-business-accuracy-20261021`
- 起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`
- 已提交：`08f8e9b fix(vnext2-p0a): 冻结快照后新增待确认问题继续阻断送审与正式交付`（P0-A）
- 当前工作包：**P0-B RAG 引用裁判（C08/C09/C10）—— 已完成修复、定向回归与真实模型复跑**
- 下一个工作包：**P0-C 真实监管需求生成与正式交付 E2E**

## 已完成改动（P0-B，未提交）

1. 新增 `backend/app/services/rag/citation_trust.py`（纯确定性，无模型调用）
   - `normalize_version` / `base_source_title` / `citation_version` / `find_pinned_version`
   - `version_violations(citations, pinned_versions)`：引用版本与快照固定版本不一致 → 违规记录
   - `normalize_conflict_type` / `normalize_conflicts` / `downgrade_conflicting_verdicts`
2. `backend/app/services/rag/citation_support.py`
   - `CITATION_SUPPORT_SYSTEM_PROMPT` 升级为 `[AI_SKILL_CITATION_SUPPORT_V2]`：同时输出 verdicts（含 `supported_claim_ids`）+ claims + conflicts
   - `parse_judge_verdicts` 支持多容器列表与 `dimension`（citation/claim/pair），避免 claim-only 判定按位置错配
   - 新增 `parse_judge_conflicts`、`run_judge_with_conflicts`（`run_judge` 签名保持不变）
   - `split_claims_all` 支持复合监管结论拆原子主张（条件/口径/包括/包含/分别为 + 顿号逗号枚举）
3. `backend/app/services/rag/citation_validator.py`
   - `check_citation_support(..., pinned_versions=None)`（向后兼容）
   - 版本违规确定性判 unsupported；冲突降级 unknown；`resolved_conflicts` 表示版本冲突已被快照固定版本裁决（只淘汰落后版本）
   - `trust_blockers` 禁止整体 verified；版本违规覆盖全部引用时判 unsupported
4. 测试与脚本
   - 新增 `backend/tests/test_vnext2_citation_trust.py`（18 例，MOCK）
   - 重写 `scripts/vnext_real_model_golden_eval.py`：按黄金集忠实转写 C01–C10，输出 `verdict_reasons` / `resolved_conflicts` / `claim_*` / `trust_blockers`，标签 `UNVERIFIED`
5. 文档
   - `docs/vnext2/p0b-citation-trust.md`（改前/改后、逐案结果、未解决问题）
   - `docs/audit/VNEXT_CITATION_TRUST-20261022.json`（真实模型证据）
   - `docs/vnext2/plan.md`（P0-B 标 DONE）

## 测试结果

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_vnext2_citation_trust.py -q` | 18 passed |
| `pytest tests/test_rag_citation_support.py tests/test_overnight_citation_status.py -q` | 27 passed |
| `python ../scripts/vnext_real_model_golden_eval.py`（真实网关） | 10/10 一致，0 degraded，9/10 主张级，冲突暴露 2，avg 4338.6ms |
| `pytest tests/test_vnext2_review_freshness.py -q`（P0-A） | 9 passed |
| `VNEXT_PG_URL=... pytest tests/test_vnext2_review_freshness_pg.py -q` | 3 passed（真实 PG） |

## 环境事实（重要）

- **网关已下线 `deepseek-v4-flash`**：`POST /chat/completions` 返回 422 `model not found`；`/models` 只剩 `deepseek-v4.1-flash`、`deepseek-flash`、`deepseek-v4-pro`、`cc/*`、`qwen3.8-flash`、`glm-5.3-flash`。开发验收模型改为 `deepseek-v4.1-flash`（`backend/.env`，gitignore，不进提交）。
- 模型名错误时系统全部 `degraded=true / provider_error`，verdict 即使碰巧正确也不计通过——这是期望的保守行为。
- WSL 空闲会自动停机：真实组件测试前先 `wsl -e sh -lc "sleep 7200"`（后台）再等 5432/6379。
- 后端定向测试统一 `AUTH_MODE=optional`，不需要真实队列时加 `TASK_QUEUE_PROVIDER=inline`。

## 恢复命令

```powershell
cd ai-platform/backend
$env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"
.\.venv\Scripts\python.exe -m pytest tests/test_vnext2_citation_trust.py -q
.\.venv\Scripts\python.exe ..\scripts\vnext_real_model_golden_eval.py --output ..\docs\audit\VNEXT_CITATION_TRUST-20261022.json
wsl -e sh -lc "sleep 7200"   # 需要真实 PG 时后台保活
```

## 当前阻断项

- 无硬阻断。已知缺口：
  1. `pinned_versions` 尚未接入产品主链路（`grounded_answer_service.py:166` 不传），C10 的确定性规则在产品内不会自动生效 → 放进 P0-C。
  2. C08 的 `unknown` vs `unsupported` 存在运行间波动，未用文本启发式硬拗。
  3. 冻结后新增人工问题仍不会自动生成 `RequirementRecheck`（P0-A 已记录）。

## 下一步准确动作

1. 提交 P0-B（代码 + 测试 + 脚本 + docs/vnext2 + 证据 JSON）。
2. 进入 P0-C：先读 `backend/tests/test_vnext2_phase2_closed_loop.py`、生成链路（generation-run / adopt API）与文档导出实现，设计“借据→合同→产品→期限方案→客户→集市→一表通”的合成场景，跑通真实模型生成 → 候选 → 采用 → 修订 → 三级审核 → 正式交付 → Word/Excel 导出，并在生成路径接入 `pinned_versions`。
