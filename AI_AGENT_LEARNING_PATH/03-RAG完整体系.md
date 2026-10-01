# 03｜RAG 完整体系：银行知识库不是“向量库 + LLM”

## 一、RAG 是什么

RAG（Retrieval-Augmented Generation）是在生成前先从外部知识源检索证据，再让模型基于证据回答。它解决三类企业问题：

- 知识可以更新，不必重新训练模型。
- 答案可以追溯到文件、页码、Sheet、单元格和记录。
- 私有知识不必写入模型参数，可按权限动态过滤。

项目对应主链路：

```text
upload
→ knowledge_ingestion/parsers.py
→ normalizer.py
→ ingestion_service.py
→ KnowledgeUnit + KeywordIndex + VectorStore
→ HybridRetriever
→ grounded_answer
→ validate_citations
→ ModelCallLog / RetrievalLog / Evaluation
```

## 二、文档解析

### 目标

把 PDF、DOCX、XLSX、SQL、Markdown 等文件转换为保留结构和出处的统一知识单元。

### 银行项目的关键点

- Excel 不能只抽纯文本：Sheet、表头层级、合并单元格、行列坐标都是引用依据。
- PDF 要保留页码；扫描 PDF 还需 OCR 和版面检测。
- Word 要保留标题路径、表格和段落关系。
- SQL/Shell 不只做文本块，还要解析表、字段、脚本版本、行号和依赖。
- 每个文档需要文件哈希、版本、有效状态、机构/项目范围和敏感等级。

### 项目落点

- `knowledge_ingestion/parsers.py`：XLSX/DOCX/PDF 等解析。
- `template_parser/traceability_excel_parser.py`：一表通多层表头和场景结构解析。
- `KnowledgeUnit`：保留 file/sheet/cell/page 等定位信息。

### 失败测试

- 合并单元格展开后是否错位？
- 公式单元格取公式还是缓存值？
- 同一文件新版本是否正确去重和归档？
- PDF 页码是否与用户看到的页码一致？

## 三、Chunk

Chunk 是检索的最小知识片段。切太大，噪声多；切太小，语义和限定条件丢失。

### 不要只按固定字符切

一表通建议按结构切：

- 监管答疑：一问一答为一块。
- Excel：字段 + 场景 + 业务口径/技术溯源为一块，并保留表头上下文。
- 数据字典：表级摘要一块，字段级记录一块。
- SQL：CTE/SELECT/INSERT 逻辑块 + 行号 + 解析出的实体。
- 制度文档：标题路径 + 段落/表格，必要时相邻重叠。

### Chunk 元数据

`project_id`、`institution`、`knowledge_scope`、`knowledge_type`、`target_field_code`、`scenario_id`、`effective_date`、`version`、`confidentiality_level`、`source_locator`。

### 评测

用黄金问题检查：正确答案是否完整落在一个或少量 Chunk 中；引用是否能定位；相邻 Chunk 是否重复过多。

## 四、Embedding

Embedding 用于语义召回，解决“客户证件号码”和“身份识别号”等表达差异。

### 工程要求

- 明确模型名称、版本、维度、归一化和距离度量。
- 文档向量与查询向量必须兼容。
- 敏感等级决定能否调用外部 embedding；restricted/confidential 要本地化或不向量化外发。
- 模型升级使用双索引：新索引后台重建，验证后切读，保留回滚。

### 项目落点

- `services/embeddings/`：embedding 抽象与实现。
- `services/vector/`：Mock/Milvus 适配器。
- `prepare_model_input` 已处理生成侧外发；embedding 侧也必须同等实施分类控制。

## 五、Vector Database

向量数据库存向量、业务 ID 和可过滤元数据，提供近似最近邻搜索。

### 需要掌握到的程度

- collection/schema、索引类型、distance metric、Top-K、metadata filter。
- 写入幂等、删除/软删除同步、索引重建、备份恢复、容量和延迟。
- 向量库不是事实主库；事实和权限主记录仍在 PostgreSQL。

### 项目落点

- `VectorStore` 是深模块接口，业务层不依赖 Milvus SDK。
- `MilvusVectorStore` 是生产适配器，`MockVectorStore` 支撑稳定测试。
- 生产验收还应补容量、备份、权限和索引一致性。

## 六、BM25 与关键词检索

BM25 是稀疏检索算法，核心直觉是：

- 查询词在文档中出现越多，相关性越高，但收益逐渐饱和。
- 在整个语料中越稀有的词越重要。
- 对文档长度做归一化，避免长文档天然占优。

### 为什么银行项目离不开稀疏检索

- `CUST_NO`、`ECIF.CUSTOMER_ID`、监管字段代码必须精确匹配。
- 金额阈值、日期、产品代码、制度编号对语义向量可能不敏感。
- 中文术语短、缩写多、表字段多，字符/词级 tokenizer 需要定制。

项目当前 `KnowledgeKeywordIndex` 是加权 Token 倒排，不是完整 BM25。面试中要诚实表达：

> 当前 MVP 实现了结构化条件 + 加权关键词 + 向量 + 规则融合；生产升级会引入 PostgreSQL FTS/OpenSearch BM25，并以黄金集验证，不把现有实现包装成完整 BM25。

## 七、Hybrid Search

混合检索把多个互补信号组合：

1. 安全过滤：机构、项目、知识类型、场景、有效状态、敏感等级。
2. 稀疏召回：字段代码、表名、监管术语、版本号。
3. 稠密召回：同义表达和自然语言问题。
4. 融合：RRF 或归一化加权。
5. 业务加权：目标字段、场景、新版监管答疑优先。

### 项目当前实现

`HybridRetriever`：

- 先构造 project/global/institution 可见性。
- KeywordIndex 召回并计算 `_keyword_score`。
- VectorStore 按 scope 搜索。
- 用 `.55*keyword + .35*vector + .1*rules` 计算“rerank_score”。
- 写入 `RetrievalLog`。

### 需要改进

- 当前 score 融合依赖不同分数可比，容易漂移；可改 RRF。
- 当前所谓 rerank 是规则打分，不是 cross-encoder reranker。
- query expansion、版本/生效日期和冲突证据处理不足。
- 需要单独记录各阶段候选、排名和淘汰原因。

## 八、Rerank

Rerank 是对初召回候选做更精细的 query-document 相关性排序。

### 两阶段设计

- 第一阶段：BM25 + 向量，高召回，取 30～100。
- 第二阶段：cross-encoder 或 LLM reranker，高精度，取 5～10 给生成模型。

### 银行场景注意

- 相关性不等于权威性：新版监管答疑应高于旧项目草稿。
- 需要把来源级别、有效日期、机构适用性和人工确认状态纳入最终排序。
- reranker 也要本地化/脱敏，并评测延迟与成本。

## 九、Citation

Citation 不是回答末尾随便列文件名，而是“结论—证据”的可验证关系。

### 最低字段

- `knowledge_unit_id`
- 文件名和版本
- Sheet/Cell 或 Page
- 引用片段
- 支持的 claim

### 校验层次

1. ID 存在且启用。
2. 对当前机构/项目可见。
3. 引用片段确实属于该知识单元。
4. 引用内容真的支持该结论，而非仅主题相近。
5. 版本和生效日期可用。

`citation_validator.py` 已实现前两层；第 3～5 层是后续重点。

## 十、Evaluation

RAG 不能只看“答案像不像”。按层评测：

### 1. 解析/索引

- 文档解析成功率、元数据完整率、引用定位准确率。
- 重复 Chunk 比例、索引一致性、软删除传播时间。

### 2. 检索

- Recall@K：应找到的证据有多少进入 Top-K。
- MRR：第一个正确证据排得有多靠前。
- Precision@K、nDCG：相关证据的精度和排序质量。
- 分场景切片：字段代码类、自然语言类、版本冲突类、无答案类。

### 3. 生成

- Answer correctness、groundedness/faithfulness。
- Citation precision/coverage。
- 无证据正确拒答率、待确认问题准确率。
- 物理字段幻觉率，目标必须为 0。

### 4. 系统

- P50/P95 延迟、错误率、Token、成本。
- 按项目/任务类型统计。
- 权限泄漏测试和 Prompt Injection 测试。

### 项目当前指标

`rag_evaluator.py` 已计算 Recall@5/10、MRR、source/table/field hit、citation coverage、groundedness、关键词覆盖、待确认问题、延迟。要注意当前 groundedness 判定较粗：有 citation 且无 unsupported_claims 就得 1，后续需要 claim-level 评审或可信 judge + 人工抽样。

## 十一、为什么银行项目不能简单向量搜索

1. **精确标识符**：字段代码、表名、制度号和码值要词法精确。
2. **权限隔离**：相似文档可能属于另一机构或项目，必须先过滤再检索。
3. **版本时效**：旧口径语义很相似，但已失效；需时间和状态过滤。
4. **场景差异**：贷款、信用卡、存款对同字段口径不同。
5. **权威等级**：监管答疑、正式制度、人工确认、AI 草稿不能同权。
6. **否定与边界**：“包含”与“不包含”、大于与大于等于可能向量接近。
7. **结构证据**：SQL 血缘和数据目录是图/表结构，不应全部压成文本。
8. **可审计引用**：必须回到 sheet/cell/page/line，不是只返回相似段落。
9. **安全外发**：敏感知识可能不允许调用外部 embedding。
10. **无答案识别**：必须能拒答并创建问题，而不是永远返回最相似结果。

## 十二、面试核心题

### 什么是 RAG？

> RAG 是生成前从外部知识源检索证据，并把证据注入模型上下文的架构。企业价值不仅是降低幻觉，还包括知识可更新、权限可过滤、答案可引用。在一表通平台中，我把解析、索引、混合检索、rerank、受控生成、citation 校验和离线评测拆成独立层，各层都可替换和测量。

### 为什么 RAG 比微调更适合企业知识库？

> 企业知识频繁变化且要求来源追踪，RAG 可以更新索引、按用户权限动态取证并返回 citation；微调更适合改变行为、风格或固定任务能力，不适合作为精确、可撤销的事实数据库。二者可组合：用微调改善领域表达或分类，用 RAG提供最新事实。

### 如何评价 RAG 效果？

> 我分层评测。解析层看出处和元数据；检索层看 Recall@K、MRR、nDCG；生成层看正确性、groundedness、citation precision/coverage 和无答案拒答；系统层看延迟、成本、错误率和权限泄漏。必须按字段代码、自然语言、版本冲突、无答案等类型切片，不能只报一个平均分。

## 阶段项目作业

1. 建立至少 50 条黄金问题：30 有答案、10 冲突、10 无答案。
2. 比较关键词、向量、当前混合、RRF 混合四组指标。
3. 增加 claim→citation 对齐字段，抽样人工评审 20 条。
4. 输出一份失败案例报告：检索失败、排序失败、生成失败、权限失败分别归因。
