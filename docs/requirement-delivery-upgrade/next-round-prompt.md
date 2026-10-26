# 下一轮提示词（可直接粘贴）

> 用法：下一轮（或新会话）开新任务时，把下面「主提示词」整段粘贴。它自包含：环境、账号、路径、步骤、证据要求、红线。
> 如果中途上下文丢失或换人接手，改用文末「续跑提示词」。
> 配套计划见 `replan-20261025.md`，环境与踩坑见 `handoff-20261025.md`。

## 主提示词

```text
目标：在本机真实环境把「GBASE 跑批脚本 → 一表通报送字段标准模板」的端到端主线跑通，并与
C:\Users\李儒伟\Desktop\需求文档输出示例.xlsx 逐列对齐。不要先加新功能。

仓库：C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform
分支：dsh/handoff-20261025-round73（HEAD cf2007b，工作区干净）；真实 PG 迁移 202611010014。
先读：docs/requirement-delivery-upgrade/handoff-20261025.md（§1 环境、§2 基线数字、§4 坑、§6 主线），
再看 docs/requirement-delivery-upgrade/replan-20261025.md（本轮验收标准 S1–S6）。

一、起环境（缺一步就跑不动）
1) wsl -e bash -lc "sleep 86400"（WSL 空闲会关容器，必须常驻）
2) docker start ybt-dev-etcd-1 ybt-dev-milvus-minio-1 → ybt-dev-milvus-1
3) backend\.venv\Scripts\python.exe scripts\local_embedding_server.py --port 11434
4) 后端 8011（无 --reload，改码必须重启）：STORAGE_DIR=<backend>\dev_storage_local，
   先清掉 DATABASE_URL/AUTH_MODE/TASK_QUEUE_PROVIDER/PYTHONPATH，再
   .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011
5) .venv\Scripts\python.exe -m celery -A app.workers.celery_app worker --pool=solo -l info
   （不启 worker，生成任务永远 queued）
6) 前端：npx next dev -p 3010，必须带 NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8011/api
   （该变量在 dev server 启动时内联；不带就全打到 8000）
7) GET http://127.0.0.1:8011/health/ready 要 10 项 healthy；
   账号 ybt-lead / Ybt#20261024lead；登录体是 {"username","password"}（不是 email）；项目 project_id=9。

二、Phase 0 基线核对（不改码，先对账）
记录并写进 real-run：delivery-audit（47 产物 / 已检查 38）、replay-manifest（可复核 11 / 仅旧渲染器 35 /
不支持重放 1，三数相加=47）、export-stability 的 verdict、requirements-worklist（233 字段）。
与 handoff §2 不一致时先查环境，不要直接改代码。

三、Phase 1 主线（目标表 T_5_1：target_table_id=59、18 字段、16 条集市映射、脚本 YBT_T_5_1.sql、当前无需求）
1) POST /projects/9/requirements/script-preview（选 YBT_T_5_1.sql）
2) POST /projects/9/requirements/author-from-scripts（一键建需，只绑同名可匹配字段）
3) POST /requirements/{rid}/generation-inputs → POST /generation-runs → 轮询到全部 completed
   （有 blocked 就看 item 的阻断原因；不要靠重试"把结果试出来"）
4) POST /generation-items/{id}/adopt，逐条采纳，不批量绕过
5) 三级审批：POST /review-submissions 再 POST /review-submissions/{id}/finalize ×3；
   real-run 里写明"演示环境同一管理员代签，非真实三岗"
6) POST /requirements/{rid}/freeze-and-export：
   expected_version = delivery-status 里的 requirement_version（不是 content_version）；
   expected_hash = current_content_hash（错一个就 409）
7) POST /exports 取 layout=survey 的 xlsx；下载后 openpyxl 读行列数留证。
8) 对 T_8_1（target_table_id=101，现有需求 10 或 25）同流程复跑一次，只验"没变坏"。

四、Phase 2 与示例逐列对齐
1) 写 backend/scripts/requirement_doc_compare.py（只读）：比表级 6 行、第 10 行分组名集合、
   第 11 行列名序列、数据行编码集合、每列非空率；输出 backend/scripts/out/doc_compare.json + 人读摘要。
2) 已知差异（别重复发现）：示例 Sheet1 是 206 行 × 328 列、19 个数据行 / 18 个唯一编码，按"场景"分组
   （业务口径-借记卡 / 溯源-借记卡系统 / 业务口径-信用卡 / 代销保险…）；我们的 T_8_1 导出是 19 行 × 56 列，
   按"来源系统"分组（监管集市 / 跑批脚本 / 未登记来源）。两边每组列结构一致：业务口径 6 列 + 溯源 9 列。
3) 改 backend/app/services/requirement_survey_export.py：场景优先分组（读 ScenarioBusinessMapping /
   ScenarioTechnicalLineage，键 target_field_id + scenario_id；无数据回退 _SYSTEM_GROUPS），同字段多场景并列。
4) 为 T_5_1 编造 3–4 个场景的业务口径与溯源（由脚本血缘 + 集市映射推导），写库标 ai_generated_content /
   confidence_level，文档写明"演示数据、可被人工覆盖"，不得写成已确认。
5) 表级 6 行接 TargetTable.theme / filing_note / reporting_domain_code / reporting_domain_name，
   空值仍写"待业务补充"，但要在差异报告里列出原因。

五、证据与验收
- 每步留接口数字 + 真实浏览器证据（Playwright 截图 + json，consoleErrors 必须为空）；
- 断言要同时锁定数量与内容，禁止 includes 弱断言（历史教训：T_8_10 被 T_8_1 的筛选带进来过）；
- 通过标准：T_5_1 端到端跑通；导出含 ≥3 个场景组；差异清单每条有解释；
  export-stability 该产物 identical；replay-manifest 三数相加=总数；docs_check 0 问题；
- 文档续写：real-run §79–§81、evidence-index §102–104、checkpoint §98–§99、plan §7.76–7.77、matrix §8.58–8.59，
  然后跑 python scripts/requirement_docs_check.py。

六、红线
- 不伪造审批、不伪造浏览器证据、不把编造场景写成已确认；历史交付不覆盖；
- 不为了"看起来完成"跳过 409/422 的根因；
- S1–S4 没达标之前不加新功能（不做覆盖度/派工/稳定性这类新面板）。
```

## 续跑提示词（上下文丢失或换人时用）

```text
接手 ai-platform 仓库（C:\Users\李儒伟\Desktop\ai-platform-dsh-20260930-150943 (2)\ai-platform，
分支 dsh/handoff-20261025-round73，HEAD cf2007b）。先读这两份文件再动手：
docs/requirement-delivery-upgrade/handoff-20261025.md 和 docs/requirement-delivery-upgrade/replan-20261025.md。

当前进度：环境与基线已核对（47 产物 / 已检查 38 / 可复核 11·35·1 / 派工 233 字段）；
主线目标表 T_5_1（target_table_id=59，18 字段，16 条映射，脚本 YBT_T_5_1.sql，尚无需）正在跑
「建需 → 生成 → 采纳 → 三级审批 → 冻结 → 导出 survey xlsx」。
请从日志里最近一次成功的步骤继续，已完成步骤不要重跑；每步把数字补进 real-run 的 §79 表格。

接下来按 replan §3 的 Phase 1 第 3 步往下做；Phase 2 的差异脚本与场景分组规则同样在该文件 §3。
证据要求：接口数字 + 真实浏览器截图/json（consoleErrors 为空）+ 断言锁定数量与内容。
红线：不伪造审批与证据、不把编造场景写成已确认、S1–S4 未达标不加新功能。
```
