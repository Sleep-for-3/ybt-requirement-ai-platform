# A6 扩展参考实现与剩余门禁

更新：2026-09-29。A6 参考实现与定向验收已完成，当前主线程按用户新指令继续 B 阶段，不安排模型交接。真实模型、PostgreSQL 与完整产品验收仍单列未验证。

## 已实现：只读字段召回与重排验证

- Schema：`backend/app/schemas/ai_skill_ranking.py`。
- 实现：`backend/app/services/ai_skills/field_candidates.py`。
- API：`POST /ai-skills/field-candidates` 和 `POST /ai-skills/field-candidates/validate-ranking`。
- 测试：`backend/tests/test_ai_skill_field_candidates.py`，17 passed；日志/JUnit 位于 `docs/evaluation/ai-skill-a5-20260928/field-candidates-final.*`。

召回请求包括 project_id、target_field_id、可选 datasource_ids/query/top_k。返回 context_hash、候选的真实目录 ID、来源版本、确定性词面分数、扫描/返回数量和人工核验标记。最多扫描 2000 个已启用列、返回 50 项；超出扫描范围报 candidate_scope_too_large，要求缩小数据源范围。

要求真实用户、technical.edit、有效项目/机构；列、表、schema 和数据源必须全部同项目、全部启用且关联一致。目标字段必须属于该项目。不连接真实数据源、不返回主机/口令/连接参数，不创建推荐记录或正式映射。

重排请求提交相同 input、context_hash 和 ranking。每条包含 candidate_id、0～1 有限数值 score 和非空 rationale。必须是原候选集的完整排列，拒绝新增、重复、遗漏。服务端重新鉴权、重新召回、重新计算包含 actor/范围/目标/目录版本的哈希；任何漂移报 candidate_snapshot_changed。

这是重排 Provider 的安全接入边界，目前只验证提交的排序/固定回放，没有调用真实重排或 Embedding 模型，也不宣称其相关性效果已验证。ranking_mode=validated_proposal 表示校验通过的建议；execution_kind 仍为 deterministic，不伪装成模型调用。

## 已补强：RAG 目标范围

`HybridRetriever.search` 在 token 化或初始化 Embedding/向量服务前，核对 target_field_id 和 scenario_id 的项目归属。既有 API 的入口授权仍保留，内部检索调用也不能用其他项目的字段描述扩展查询。四个越界/不存在负例与知识/血缘组合 36 passed，证据见 retrieval-scope.*。

已有的制度效力过滤和结构化对照由 `knowledge_eligibility.py`、`ai_skills/lineage_adapter.py`、`SkillPolicyComparison` 与共享引用校验提供。Mapping Context 参考信息仍不自动升级为已核验制度条款；其原生适配会显式报告 missing_basis。

## 影响事件与复核事务（已验证）

`requirement_recheck.create_recheck` 先对需求当前版本做条件写锁，再重读影响、按 revision_id/change_hash 幂等创建复核和工作流。SQLite 不支持 FOR UPDATE，因此使用保留值和 updated_at 的条件 UPDATE；锁只持续到调用方提交/回滚。两个独立连接同时请求只生成一条复核和一个审核任务，历史内容与时间戳不变。旧 ORM 版本不能绕过当前版本检查。

`lineage/impact_analyzer.persist_change_impact` 校验脚本版本归属，锁脚本父记录，再按既有版本对复用事件。含 NULL 的新增/删除版本对也显式去重。重放内容与已有事件不同返回 409，不覆盖历史分析；节点与边查询限定项目。已有数据库版本对唯一约束保持不变，重复重命名到不同路径若复用同一版本对也明确冲突，不会当作相同事件吞掉。

`governance/workflow.start_workflow` 新增默认兼容的 commit 参数；以上两个组合事务显式传 False，API 或 ingestion/jobs 负责最终提交。失败测试曾发现内部提前提交，修复后事件、复核、任务一起回滚。既有其他工作流仍保留默认提交行为。

证据：recheck-final 11 passed；SQL 血缘现有 31 passed；impact 首次新增夹具缺 StoredFile FK 导致 5 errors，补齐真实 FK 后 a6-boundaries 的 5 项事件测试全部通过；治理/血缘修订回归 40 passed。没有声称 PostgreSQL 并发已验证。

## 路由与缓存可执行契约（已验证，未启用缓存存储）

`ai_skills/cache_contract.py` 提供 prepare_lineage_access、make_candidate、lookup_lineage_candidate。只接受服务端按真实身份重建的固定血缘、有效条款及辅助上下文；没有公开接受客户端 Envelope 的缓存 API。存储层与业务自动命中留 B5。

每次访问先重新鉴权、解析固定绑定、检查发布依赖、重建证据、执行密级和预算检查，再比缓存键/期限。键覆盖 actor、角色、机构/项目/调用点、绑定、Skill 版本/内容/依赖指纹、完整证据版本哈希、渲染输入、模型配置/实际模型和最高密级。知识及使用到的模板/源版本变化通过完整投影哈希失效。

候选必须与成功的 ModelCallLog 内容哈希、版本、范围和实际模型一致；测试运行、失败、未知实际模型、来源不匹配不能进入缓存。最多 300 秒；force_refresh 绕过命中。命中再次做结构/引用验证，返回新读到的事实和条款，provenance 标 deterministic/cache_hit 与 origin_run_id/origin_execution_kind，不能把它计为新的模型调用或重用旧 run_id 作为新运行。B5 仍须实现独立访问审计、存储加密/容量/清除策略和费用观测。

a6-boundaries 中缓存 16 项通过：跨租户/撤权/其他已授权 actor、角色/密级/模型漂移、条款过期/撤回/禁用、输出篡改、过期、强制刷新、无新增模型调用。使用请求级新事务；不能依赖跨请求长事务的旧快照。

## 固定样例与效果边界

`backend/tests/fixtures/ai_skill_a6_golden.json` 是版本 a6-synthetic-1 的纯合成样例，`test_ai_skill_a6_golden.py` 实际读取并验证。四个中英文目录查询走真实 API，八个答案/冲突/缺依据样例走共享 Schema 和引用校验，共 12 passed。样例证明可复现的基础召回与引用边界，不证明语义正确率、真实重排或法规结论；真实模型质量仍需领域评审。条款效力查询测试在 test_ai_skill_lineage_adapter.py 与缓存测试中，不以 JSON 标志代替数据库有效性检查。

## 后续产品化约束

1. B3 接入候选与复核待办页面，扩大相关性评测，不绕过现有幂等/白名单/独立审核。
2. B5 在上述契约下实现缓存存储；主备模型每个实际路由均须有独立评测/发布/密级证明，禁止自动回退到未评测模型。
3. PostgreSQL 迁移和并发、真实 Embedding/重排/生成效果未验证；生产启用前另行验收。
4. API、错误和状态基础约束继续以 A0/A5 设计及后端 Schema 为准；页面新增能力不能改变服务端权限和不可变历史。

B 阶段继续由当前线程执行；本参考实现通过不代表第二部分全部完成或生产验收通过。
