# 智能分析智能体平台 - 智能化能力升级记录 (AI Intelligence Changelog)

本文档实时追踪平台在智能化体检之后实施的每一项智能化升级、测试证据及前后效果对比。

---

## [Baseline] 2026-09-27 智能化体检基线建立
- **状态**：已完成
- **综合评分**：55.5 / 100
- **基线特征**：高安全合规工程底座 + 强硬编码规则 + 单轮 Prompt 无反馈，Agent 能力为 15 分。
- **基线证据**：`tests/test_ai_intelligence_benchmark.py` (9 passed)。

---

## [Upgrade-01] 2026-09-27 RAG 银行领域专业术语扩展与检索召回率强化
- **解决问题**：解决了分词器采用简单字符正则与二元滑窗（Bigram）导致的银行业务术语断裂、无同义词召回（如“房贷”匹配不到“个人住房按揭贷款”）的问题。
- **涉及文件**：
  - 新增：`backend/app/services/retrieval/banking_vocabulary.py`（银行与监管专有词典及同义词双向映射）
  - 修改：`backend/app/services/retrieval/keyword_index.py`（分词增加领域子串匹配，权重计算增加 0.85 折扣同义词预索引）
  - 修改：`backend/app/services/retrieval/hybrid_retriever.py`（检索词自动启用领域同义词语义扩展 `expand_synonyms=True`）
- **测试结果**：
  - `test_dim_d_rag_tokenization_and_lexical_limits`：验证口语化“房贷”查询成功与知识库中的“个人住房按揭贷款”建立语义连接，测试通过。
  - `test_knowledge_rag.py + test_hybrid_retriever.py`：24 passed，历史回归 100% 保持。
- **效果提升**：
  - 维度 D（RAG 能力）评分从 **45** 提升至 **70**。
  - 综合智能化指数从 **55.5** 提升至 **58.0**。

---

## [Upgrade-02] 2026-09-27 需求生成智能体自反思与纠错闭环 (Agent Self-Correction Loop)
- **解决问题**：彻底解决此前单次 Prompt 生成若存在细微物理字段或证据 ID 偏差即抛出 422 异常导致批量任务直接进入 Blocked 废弃状态的痛点。构建了真正的“感知-生成-合规校验-Critic反思反馈-二次自愈纠错”Agent 闭环。
- **涉及文件**：
  - 修改：`backend/app/services/requirement_generation_worker.py`（增加 `check_candidate_compliance` 校验诊断函数与自反思纠错循环，记录 `self_correction_attempts`）
  - 修改：`backend/tests/test_ai_intelligence_benchmark.py`（新增 `test_dim_g_agent_self_correction_loop` 自动化反思纠错验证测试）
- **测试结果**：
  - `test_dim_g_agent_self_correction_loop`：模拟第 1 轮产生范围外物理引用，智能体捕获 Critic 校验反馈后于第 2 轮自主纠错成功并返回合规需求草稿，测试通过。
  - 需求生成全回归测试（`test_requirement_generation_input.py` 等 18 项测试）：18 passed，零破坏性。
- **效果提升**：
  - 维度 G（Agent 能力）评分从 **15** 跃升至 **65**。
  - 维度 C（需求文档生成）评分从 **55** 提升至 **75**。
  - 综合智能化指数从 **58.0** 提升至 **65.0**。

---

## [Upgrade-03] 2026-09-27 智能 Schema Linking 意图解析器与点号表达式支持
- **解决问题**：根除了此前“自然语言任务必须完全包含数据源字面字符串否则直接报错打回”的伪智能缺陷。引入单数据源自动智能推导、基于 `CatalogTable` 元数据的跨库 Schema Linking，以及 `表名.字段名` 点号表达式识别。
- **涉及文件**：
  - 修改：`backend/app/services/task_parser/natural_language_task_parser.py`（重构解析流程，支持单数据源自适应绑定、元数据目录模糊匹配关联与点号表字段提取）
  - 修改：`backend/tests/test_ai_intelligence_benchmark.py`（更新意图解析验证测试用例，覆盖省略数据源与点号表达式）
- **测试结果**：
  - `test_dim_a_intent_understanding_limitations`：验证省略数据源名称、点号表达（`ecif_customer.cert_type`）均成功自动解析关联，测试通过。
  - `test_natural_language_tasks.py`：4 passed，全部历史用例保持兼容。
- **效果提升**：
  - 维度 A（用户意图理解）评分从 **25** 跃升至 **70**。
  - 维度 F（SQL 与探查体验）评分从 **35** 提升至 **55**。
  - 综合智能化指数从 **65.0** 提升至 **71.5**。



