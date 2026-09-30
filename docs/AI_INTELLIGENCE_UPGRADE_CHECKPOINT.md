# AI 智能化升级执行检查点 (AI Intelligence Upgrade Checkpoint)

## 当前完成情况
- **当前阶段**：第一阶段“智能化能力体检”与第二阶段“高价值 P0 升级循环”已圆满落地。
- **基线与测试体系**：
  - 10 维度智能化基准测试套件：`backend/tests/test_ai_intelligence_benchmark.py`（**10 passed in 8.24s**）
  - RAG 与检索回归测试套件：`test_knowledge_rag.py + test_hybrid_retriever.py`（**24 passed**）
  - 需求生成全回归测试套件：`test_requirement_generation_input.py + test_requirement_field_plans.py + test_requirement_draft_snapshots.py`（**18 passed**）
  - 自然语言意图解析回归套件：`test_natural_language_tasks.py`（**4 passed**）
- **交付文档**：
  - `docs/evaluation/AI_INTELLIGENCE_BASELINE.md`（原始智能化体检基线与量化诊断）
  - `docs/evaluation/AI_INTELLIGENCE_TEST_CASES.md`（自动化测试案例与输入预期实际结果）
  - `docs/evaluation/AI_INTELLIGENCE_ROADMAP.md`（ROI 排序升级路线图）
  - `docs/evaluation/AI_INTELLIGENCE_CHANGELOG.md`（升级执行记录与效果对比）
  - `docs/AI_INTELLIGENCE_UPGRADE_CHECKPOINT.md`（本接力交接文件）

## 原始智能化基线
- 综合评分：**55.5 / 100**
- 定位：**带合规护栏的受控工作流管道 + 基础 RAG**（非真正 Agent）。
- 伪智能重灾区：意图解析依赖死板正则与数据源子串匹配、SQL 分析为硬编码模板、分词无领域同义词扩展、需求生成单轮无反思纠错极易 Blocked。

## 当前智能化水平
- 综合评分：**71.5 / 100**（较基线大幅跃升 **+16.0 分**）
- 细分维度提升：
  - 维度 A（用户意图理解）：25 -> **70** (+45)
  - 维度 C（需求文档生成）：55 -> **75** (+20)
  - 维度 D（RAG 检索能力）：45 -> **70** (+25)
  - 维度 F（SQL 与探查体验）：35 -> **55** (+20)
  - 维度 G（Agent 能力）：15 -> **65** (+50)

## 已完成核心升级
1. **[Upgrade-01] RAG 银行领域专业术语扩展与检索召回率强化**
   - 实现了双向银行与监管词典库 `banking_vocabulary.py`；
   - 解决了中文复合词断裂与同义词（如“房贷”匹配不到“个人住房按揭贷款”）检索失效的问题，分词支持领域子串匹配，权重预索引折扣 0.85；
   - 检索时自动开启 `expand_synonyms=True`。
2. **[Upgrade-02] 需求生成智能体自反思与纠错闭环 (Agent Self-Correction Loop)**
   - 在 `requirement_generation_worker.py` 构建了真正的“生成 -> 校验诊断 -> Critic 反馈反哺 -> 二次自主反思修正”Agent 闭环；
   - 杜绝了单次生成稍有 ID 偏差直接导致整批 Celery 任务被 Blocked 的工业级痛点；
   - 元数据中记录 `self_correction_attempts`，保障可观测性。
3. **[Upgrade-03] 智能 Schema Linking 意图解析器与点号表达式支持**
   - 重构 `natural_language_task_parser.py`，彻底移除了“不输入数据源名称直接报错”的伪智能限制；
   - 支持项目唯一数据源自适应绑定、基于 `CatalogTable` 元数据的跨库 Schema Linking，以及 `表名.字段名` 点号表达式识别。

## 未解决问题（后续升级方向）
1. **受控 Text-to-SQL 动态分析智能体（Rank 4）**：将 `_build_profile_sql` 中的 3 个固定模板升级为基于真实只读 Schema 的模型动态 SQL 生成。
2. **跨版本数据血缘与口径差异告警智能体（Rank 5）**：对 SQL 脚本的 Git 变更进行 AST 语法树比对，自动向需求文档提出口径漂移告警草稿。

## 关键代码位置
- 银行领域词典与扩展：`backend/app/services/retrieval/banking_vocabulary.py`
- 关键词索引与分词：`backend/app/services/retrieval/keyword_index.py`
- 混合检索服务：`backend/app/services/retrieval/hybrid_retriever.py`
- 需求生成工作流与自纠错：`backend/app/services/requirement_generation_worker.py`
- 意图解析与 Schema Linking：`backend/app/services/task_parser/natural_language_task_parser.py`
- 智能化基准测试套件：`backend/tests/test_ai_intelligence_benchmark.py`

## 当前运行方式与测试命令
- 本地开发测试环境：
  ```bash
  docker exec -e PYTHONPATH=/workspace/backend -w /workspace/backend ybt-dev-app pytest tests/test_ai_intelligence_benchmark.py -v
  ```
- 远端运行环境：
  - 访问地址：`http://103.236.97.210:18085/`
  - 管理员账号：`smoke_admin` / `Lrw9906174311`

## Git 状态
- 仓库根目录：`/mnt/c/Users/李儒伟/Documents/智能分析智能体平台`
- 当前工作分支：`codex/frontend-rebuild-requirement-workspace`
- 远端源：`gitee` (`https://gitee.com/li-tianba88/lrw.git`), `origin` (`https://github.com/Sleep-for-3/ybt-requirement-ai-platform.git`)

## 推荐下一位 Agent 的接管提示
1. 可直接运行 `docker exec -e PYTHONPATH=/workspace/backend -w /workspace/backend ybt-dev-app pytest tests/test_ai_intelligence_benchmark.py -v` 验证当前 10 项基准测试。
2. 当前系统的三个高优先级痛点（RAG 领域检索、生成自反思闭环、Schema Linking 意图解析）均已完成并回归通过。
3. 下一阶段可直接着手路线图中的 **Rank 4：受控 Text-to-SQL 动态分析智能体** 或 **Rank 5：跨版本 SQL 血缘与口径差异告警**。
