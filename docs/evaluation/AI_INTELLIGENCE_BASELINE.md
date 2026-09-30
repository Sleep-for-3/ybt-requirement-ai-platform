# 银行一表通智能分析平台 - 智能化能力体检基线报告 (AI Intelligence Baseline)

> **评估负责人**：AI 应用架构师 / 银行数据与监管报送系统专家 / RAG & Agent 工程专家  
> **评估时间**：2026-09-27  
> **代码基线 HEAD**：`3e94e54` (feat: harden AI trust and lineage workflows) + AI Skill Control Plane (20260927)  
> **测试环境**：Linux Docker Container (`ybt-dev-app`, Python 3.12.13, Pytest 8.4.2, PostgreSQL 16, Redis 7)

---

## 一、 核心结论：当前系统到底有多智能？

经过对后端架构、LLM 调用层、RAG 检索链路、数据库探查服务、血缘分析以及需求生成工作流的**源码审查与 9 项自动化基准测试（`test_ai_intelligence_benchmark.py`）**，系统定位结论如下：

> **定位结论**：
> 当前系统**本质上是一个“高度工程化、强确定性校验、带严苛合规护栏的受控工作流管道（Governed Workflow Pipeline）+ 基础 RAG”**。
> 
> **它处于“带知识库的问答系统（Level 2）与基础 RAG 系统（Level 3）之间”，完全尚未达到“能使用工具的 Agent（Level 4）”，更不是“具备规划、执行、反思纠错能力的专业智能体（Level 6/7）”。**

### 核心定性依据：
1. **完全没有 Agent 核心闭环**：代码中不存在 `tool_calls`、`function_call`、ReAct 循环、Plan-and-Solve 或 Critic/Reflection 机制。`OpenAICompatibleLLMService` 仅提供 `chat_json` 单次提示词调用，不存在工具绑定能力。
2. **存在显著的“伪智能”与硬编码套壳**：
   - 所谓的“自然语言任务（`NaturalLanguageTaskParser`）”并非大模型意图识别，而是**纯粹的正则表达式（`_extract_table_and_field`）与数据源名称完全子串匹配**。
   - 所谓的“SQL 探查能力（`_build_profile_sql`）”**完全由 Python 格式化字符串拼接生成**（固定的 null count / distinct count 模板），大模型根本不知道数据库真实 Schema，也未参与 SQL 编写。
3. **需求生成为单次无反馈生成（Single-turn Generation）**：
   - Celery Worker 从数据库取出冻结的上下文快照，拼接超长 JSON 提示词送给模型；
   - 一旦模型单次输出不合规（如物理字段 ID 不在范围内），系统直接抛出 HTTP 422 并将任务标记为 `blocked`，**没有任何模型自我审视（Self-Correction）、重试修正或追问机制**。
4. **工程安全护栏极强，但 AI 智能内核较弱**：
   - 项目在数据安全、租户隔离、审计追踪（SHA-256 签名、不可变快照、引用校验）方面具备工业级银行合规标准；
   - 但智能化层面的“Query 理解、语义检索、领域词表、多阶段推理、SQL 自动生成与血缘对齐”仍处于初级状态。

---

## 二、 十个维度的量化基线评估 (0 - 100)

| 评估维度 | 当前评分 (0-100) | 当前形态 | 核心瓶颈 / 缺陷 | 改进优先级 |
| :--- | :---: | :--- | :--- | :---: |
| **A. 用户意图理解** | **25** | 正则与关键词字面匹配 | 缺少数据源名称即报错，无法理解业务口语化与模糊需求 | **P0 (极高)** |
| **B. 银行业务理解** | **50** | 强依赖人工前置录入关系 | 业务概念（合同/借据/账户/客户）由数据库表结构限定，模型无领域本体网络 | **P1 (高)** |
| **C. 需求文档生成** | **55** | 结构化上下文一次性填充 Prompt | 单次直出，缺少大纲规划、段落自检与跨字段关联一致性推理 | **P0 (极高)** |
| **D. RAG 检索能力** | **45** | 正则分词 + 线性加权混合检索 | 无 Query Rewrite、无专业同义词库（房贷≠按揭）、无 Reranker | **P0 (极高)** |
| **E. 幻觉控制** | **85** | 确定性 Schema 与物理引用强拦截 | 后验校验硬拦截极佳（422），但模型前置理解弱，导致任务频繁 blocked | **P1 (高)** |
| **F. SQL 能力** | **35** | 模板拼接 + sqlglot 安全校验 | 仅支持固定模板，无真实 Text-to-SQL，无动态 Schema Linking | **P1 (高)** |
| **G. Agent 能力** | **15** | 零 Agent 循环，硬编码 DAG 管道 | 无工具感知、无动态规划、无执行后获取反馈、无自我反思纠错 | **P0 (极高)** |
| **H. 长任务能力** | **75** | Celery + 租约锁分片执行 | 任务队列与状态机健全，但属于异步任务调度，非 Agent 自主任务拆解 | **P2 (中)** |
| **I. 可追溯性** | **90** | SHA-256 哈希、上下文快照、Citation 强绑定 | 证据链完整，结论出处清晰，来源不可伪造 | **保持** |
| **J. 鲁棒性与稳定性** | **80** | Pydantic 严校验、降级响应机制 | 非法 JSON 拦截严密，但模型超时后仅退化为“证据摘要，结论待确认” | **P2 (中)** |

**综合智能化指数基线**：**55.5 / 100**

---

## 三、 实测证据与代码缺陷深入剖析

### 1. 维度 A：意图理解的“伪智能”实测
- **代码位置**：`backend/app/services/task_parser/natural_language_task_parser.py`
- **实测证据**（来自 `test_dim_a_intent_understanding_limitations`）：
  - 输入：`"请帮我分析一下客户表 ecif_customer 中的证件类型 cert_type 的空值情况"`
  - 预期：识别出要分析客户表字段空值率。
  - 实际结果：返回 `status="need_clarification"`，报错 `"未识别到数据源名称，请在任务中使用已配置的数据源名称。"`
  - 原因：`matched = [datasource for datasource in datasources if datasource.name in raw_text]`，如果用户在提问时没有生硬地敲入数据源标识（如 `core_db`），系统完全丧失解析能力。
  - 此外，提取表名与字段依靠 `([a-zA-Z][a-zA-Z0-9_]+)\s*表` 正则，业务人员一旦说“看一下对公活期账户余额”，正则直接返回空。

### 2. 维度 D：RAG 检索能力断层
- **代码位置**：`backend/app/services/retrieval/keyword_index.py`、`hybrid_retriever.py`
- **实测证据**（来自 `test_dim_d_rag_tokenization_and_lexical_limits`）：
  - 中文分词采用简单的字符正则与二元滑窗（Bigram）：`re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}", text)`。
  - 缺少银行领域分词与同义词扩展。例如知识库录入“个人住房按揭贷款逾期借据”，用户搜索“房贷逾期”或“公积金贷款”，关键词交集为 0。
  - 缺少 **Query Rewrite**（查询重写），用户口语化查询无法规范化为监管术语（如“二套房贷利率” -> “个人住房贷款 利率定价浮动区间”）。
  - 缺少 **Cross-Encoder Reranker**（重排序），仅将关键词评分与向量评分做简单归一化相加（`0.5 * kw + 0.5 * vec`），极易被字面高频词误导。

### 3. 维度 F：SQL 分析“看起来会分析数据库，实际全靠写死模板”
- **代码位置**：`backend/app/services/natural_language_task_service.py` L94-L120
- **源码实测**：
  ```python
  def _build_profile_sql(raw_text: str, table: str, field: str) -> list[dict[str, str]]:
      sql_items = [
          {"name": "null_profile", "sql": f"select count({field}) + sum(case when {field} is null then 1 else 0 end) as total_count, ... from {table}"},
          {"name": "distinct_profile", "sql": f"select count(distinct {field}) as distinct_count from {table}"},
          {"name": "enum_profile", "sql": f"select {field} as enum_value, count(*) as cnt from {table} group by {field} ... limit 10"}
      ]
  ```
  - 这证明平台**完全没有 Text-to-SQL 智能**。无论是自然语言探查还是字段统计，全是一套固定的 SQL 字符串模板。
  - 遇到需要跨表关联（如 `ecif_customer` 关联 `loan_account`）、多系统拉链表生效判断（`start_date <= current_date and end_date > current_date`）时，该功能完全失效。

### 4. 维度 G：Agent 决策与反思机制完全缺失
- **代码位置**：`backend/app/services/requirement_generation_worker.py`
- **实测证据**：
  - 生成过程直接调用 `execute_runtime_chat(..., RequirementCandidate)`。
  - 如果大模型生成的 JSON 中包含了未经授权的字段 ID，`validate_physical_references(context, candidate["physical_references"])` 直接引发 422 异常：
    ```python
    except HTTPException as exc:
        status, reason, candidate = "blocked", blocked_reason_code(exc), None
    ```
  - 任务直接进入 `blocked` 终态。
  - **真正的智能体行为应当是**：感知到校验器（Validator）拦截报错 -> 将错误信息反馈给模型（Reflection） -> 提示模型“你引用的表字段 X 不在允许范围内，请从候选清单 Y 中重新选择或记录为业务缺口” -> 模型自动修正（Self-Correction） -> 校验通过完成产出。

---

## 四、 伪智能与设计短板汇总清单

1. **意图解析伪智能**：正则与硬编码数据源子串匹配，一旦用户没有按刻板格式输入，直接打回。
2. **SQL 生成伪智能**：写死的 3 个单表 SELECT 模板，没有任何真实 LLM SQL 生成或 Schema Linking。
3. **Skill 系统初级**：当前正在进行的 AI Skill 配置中心只完成了数据模型与静态契约（A0/A1），尚未接入动态 Tool Calling 与业务运行时编排。
4. **单次直出导致任务易损**：缺少 Agent Feedback Loop，导致任何细微幻觉都会导致批量任务中断。
5. **RAG 缺乏领域语义**：无银行术语词表、无同义词映射、无查询重写、无重排，检索召回率受限。
