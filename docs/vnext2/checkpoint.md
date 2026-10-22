# VNext 2 检查点（docs/vnext2/checkpoint.md）

> 会话中断、上下文压缩或环境重启后，先读本文件 + `git status` / `git log`，不要依赖聊天记忆。

## 当前状态（2026-10-23 Round 6）

- 分支：`dsh/vnext-business-accuracy-20261021`
- 起始 HEAD：`6b75384e4bacd94dfae70c58900f09282c7fcde5`
- 当前 HEAD：`ff45f9f`（P2 文档），本轮 Round 6 改动待提交
- 已提交：`08f8e9b`(P0-A) `b5e5ae8`(P0-B) `525190d`(P0-C 后端) `7d37cc7`(P0-C 浏览器 + P1-B 首批)
  `182d479`(P1-B 次批) `2475d46`(P1-A) `a5249f3`(P1-C) `81ab717`(P2-A/P2-B + 报告) `ff45f9f`(P2 文档收尾)
- 当前工作包：**Round 6 = P0-B 后续缺口收口（`pinned_versions` 产品接线）+ 确定性版本比较缺陷修复**

## Round 6 未提交改动

- 新增 `backend/app/services/requirement_pins.py`：从冻结 `RequirementRevision.content_json` 推导
  `{来源标题: 监管版本}`（复用 `load_revision` 的哈希校验；空/占位版本不参与；同标题多版本标记 `_conflicting:`）
- `backend/app/services/rag/grounded_answer_service.py`：`pinned_versions` 交给引用裁判，成功时回显
- `backend/app/api/knowledge_rag.py`：`AskRequest` 增 `requirement_id` / `requirement_content_version`；
  只给其一 400；该版本无可用钉扎 422（保守拒绝）；成功回显 `version_pin`
- `backend/app/services/rag/citation_trust.py`：修复 `normalize_version` 丢失年份后修订号
  （`2026-v1` 与 `2026-v2` 曾相等 → 需求固定 v1 时 v2 引用被静默接受）
- 新增 `backend/tests/test_vnext2_pinned_versions.py`（10 例）
- 文档：`docs/vnext2/p0b-citation-trust.md` 第 5 节缺口 2 关闭、`docs/vnext2/plan.md` P0-B 下一步改写

## 测试结果（Round 6）

| 命令 | 结果 |
| --- | --- |
| `pytest tests/test_vnext2_pinned_versions.py -q` | 10 passed |
| 同上 + `tests/test_vnext2_citation_trust.py` | 28 passed / 147s |
| `pytest tests -k "citation or rag or knowledge or grounded or ask or pin"` | 见 `docs/audit/` 日志（本轮执行） |

## 环境事实（重要）

- 全量回归需显式 `AUTH_MODE=optional`；不需真实队列时 `TASK_QUEUE_PROVIDER=inline`。
- 真实模型：`deepseek-v4.1-flash`（`deepseek-v4-flash` 已下线）；`backend/.env` 有 `LLM_MAX_OUTPUT_TOKENS=8192`。
- WSL 空闲会停机 → 容器停止；真实组件测试前先起保活
  `wsl -e sh -lc "sleep 5400"`（工具级后台 job），再 `Test-NetConnection 127.0.0.1 -Port 5432`。
- 演示数据重置：`scripts/vnext2_p0c_reset.sql`（单事务、外键逆序、`psql -v ON_ERROR_STOP=1`）。
- `User` 模型列是 `status`（无 `is_active`/`institution_id`）；`ProjectMembership` 用 `project_role` + `status`；
  `Requirement` 无 `created_by`，`RequirementRevision` 有。

## 当前阻断项

1. 检索规模性能（小/中/规划容量）`UNVERIFIED`：缺容量基线语料。
2. Worker/Beat 进程自动重启属部署层，仓库无 supervisor，`UNVERIFIED`。
3. 工作台“AI 候选阶段标识”：字段重排已有 `rank_source`（retrieval/model_screened/unevaluated），
   需求候选只有 `SkillRunProvenance`（执行方式/模型/哈希），无“分批比较/最终比较”阶段标签——仍未实现。
4. 需求问答的前端入口尚未暴露 `requirement_id` 版本钉扎（API 已可用）。

## 下一步准确动作

①把版本钉扎接进需求工作台问答入口（前端传 requirement_id + content_version）；
②真实案例独立标注；③容量分档检索测评；④部署韧性与长任务租约；⑤工作台 AI 候选阶段标识与跨页待办。
