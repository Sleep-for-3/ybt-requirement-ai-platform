# VNext 2 检查点（docs/vnext2/checkpoint.md）

更新时间：2026-10-22 22:35（Asia/Shanghai）

## 当前状态

- 当前分支：`dsh/vnext-business-accuracy-20261021`
- 起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`
- 已提交：`08f8e9b`（P0-A）、`b5e5ae8`（P0-B）
- 当前工作包：**P0-C 真实监管需求生成与正式交付 E2E —— 后端链路已跑通（真实模型），待提交**
- 下一个工作包：P0-C 浏览器子项 → P1-A（Agent 五类决策）

## 当前未提交改动（P0-C）

1. `backend/app/api/requirements.py`
   - 修复 `POST .../revisions/{cv}/refresh-lineage` 的 `record_audit` 签名错误（原实现必抛 TypeError 500），改为关键字调用并写结构化 `after`。
   - 新增 `POST .../gaps/{gap_id}/resolve`（201，body `ResolveGapInput{expected_content_version>0, resolution_text 1..2000}`，需 business.edit/technical.edit），写审计 `resolve_requirement_gap`。
2. `backend/app/services/requirement_revisions.py`：新增 `resolve_gap(...)`（空白说明 422；缺口不存在 404；字段派生缺口 409 不可用说明关闭；通过后 status=resolved、resolution_basis、gap_history、重算 assessment、`append_revision` 生成新版本）。
3. `backend/app/services/requirement_candidate_contract.py`：`check_candidate_compliance` 新增正文守门——空正文 → 「候选未给出可交付的需求正文」；不含中文 → 「需求正文必须使用中文业务描述，当前候选未包含中文正文」。
4. `backend/app/services/requirement_generation_worker.py`：提示词按 section 要求中文正文与证据引用；证据在范围内却未被引用时追加待确认 gap。
5. `backend/app/services/llm/openai_compatible.py`：`content` 为空 → 明确报错「模型未返回结构化正文（finish_reason=…, reasoning_chars=…）」；`chat_structured` 在 invalid response 为空时**不再进入格式修复路径**（防止伪造占位候选）。
6. `backend/app/core/settings.py` + `backend/app/services/llm/factory.py`：新增 `LLM_MAX_OUTPUT_TOKENS`（默认 4096，范围 256–8192，含校验），替代硬编码 2048；开发 `.env` 设 8192（gitignore，不提交）。
7. `backend/app/services/ai_skills/runtime.py`：编译期空候选探针改为真正的负向控制（空正文必须被拒不 500）。
8. `backend/app/services/llm/mock.py`：AI Skill 需求分支 marker 判定由 `startswith` 改为 `in`。
9. `backend/tests/conftest.py`：新增 `VNEXT_ALLOW_REAL_RUNTIME=1` 开关，默认仍强制 mock/隔离；真实模型专项验收显式开启。
10. `backend/tests/test_requirement_candidate_contract.py`：新增空正文/中文守门回归。
11. 新增 `backend/tests/test_vnext2_p0c_real_delivery.py`（4 例：主链路、失败可见、派生缺口不可用说明关闭、冻结后新问题阻断新交付）。
12. 文档：`docs/vnext2/p0c-real-delivery.md`；`docs/vnext2/plan.md` P0-C 标 `IN_PROGRESS`（后端 DONE，浏览器 TODO）。

## 测试结果

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_vnext2_p0c_real_delivery.py -q`（真实模型 `deepseek-v4.1-flash` + `LLM_MAX_OUTPUT_TOKENS=8192`） | **4 passed / 159.94s** |
| 同上（mock/隔离运行时） | 4 passed |
| 相邻回归 10 文件（llm_runtime、ai_skill_requirement、candidate_contract、p0c、requirement_scope、formal_delivery、draft_snapshots、phase2_closed_loop、manual_question、review_freshness） | **102 passed / 54.38s** |

## 环境事实（重要）

- 开发验收网关：`http://47.101.159.7:29988/v1`，`deepseek-v4.1-flash`（推理型：先写 `reasoning_content`，`max_tokens` 不足时 `content` 为空且 `finish_reason=length`）。
- `deepseek-v4-flash` 已下线（422 model not found）。
- 真实组件（PG/Redis/Milvus）在 WSL docker；WSL 空闲会自动停机，需 `wsl -e sh -lc "sleep 7200"` 保活后再等端口。
- 后端定向测试统一 `AUTH_MODE=optional`；不需要真实队列时加 `TASK_QUEUE_PROVIDER=inline`。

## 恢复命令

```powershell
cd ai-platform/backend
$env:AUTH_MODE="optional"; $env:TASK_QUEUE_PROVIDER="inline"
.\.venv\Scripts\python.exe -m pytest tests/test_vnext2_p0c_real_delivery.py -q
# 真实模型（约 3 次生成，2.5 分钟）：
$env:VNEXT_ALLOW_REAL_RUNTIME="1"; $env:VNEXT2_P0C_REAL_MODEL="1"; $env:LLM_MAX_OUTPUT_TOKENS="8192"
.\.venv\Scripts\python.exe -m pytest tests/test_vnext2_p0c_real_delivery.py -q
```

## 当前阻断项

- 无硬阻断。已知缺口：
  1. P0-C 真实浏览器全操作闭环未完成（现有浏览器脚本只覆盖登录/页面/Tab）。
  2. 前端没有“缺口关闭（resolve_gap）”入口（API 已有）。
  3. `pinned_versions` 仍未接入产品生成路径。
  4. 冻结后新增人工问题不会自动生成 `RequirementRecheck`。

## 下一步准确动作

1. 提交 P0-C 当前改动（代码 + 测试 + docs/vnext2）。
2. 扩展真实浏览器闭环：优先打通“真实页面新建需求→生成→查看候选/证据→采用→编辑→送审→多角色审核→正式交付→下载 Word”。
3. 随后进入 P1-A（Agent 五类决策）。
