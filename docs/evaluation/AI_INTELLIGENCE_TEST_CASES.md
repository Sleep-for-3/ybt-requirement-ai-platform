# 智能分析智能体平台 - 自动化基准测试案例集 (AI Intelligence Test Cases)

> **对应自动化测试套件**：`backend/tests/test_ai_intelligence_benchmark.py`  
> **执行命令**：`docker exec -e PYTHONPATH=/workspace/backend -w /workspace/backend ybt-dev-app pytest tests/test_ai_intelligence_benchmark.py -v`  
> **基线测试结果**：**9 passed in 8.71s**

---

## 测试案例清单与执行记录

### TC-DIM-A01：用户意图理解 - 口语化提问缺少明确数据源名称
- **测试目标**：验证自然语言任务解析器能否容忍用户未输入刻板数据源名称。
- **输入数据**：
  - 数据源配置：`DataSource(name="core_db", db_type="postgresql")`
  - 用户自然语言：`"请帮我分析一下客户表 ecif_customer 中的证件类型 cert_type 的空值情况"`
- **预期业务结果**：系统通过已有数据源及其 Catalog 自动匹配到该表属于 `core_db`，解析成功。
- **实际系统表现**：返回 `status="need_clarification"`，错误提示 `"未识别到数据源名称，请在任务中使用已配置的数据源名称。"`
- **智能化判定**：**严重缺陷（伪智能）**。完全依赖字符字面子串匹配，缺少元数据关联智能。

---

### TC-DIM-A02：用户意图理解 - 格式化模板输入
- **测试目标**：验证满足系统硬编码约束时的提取准确率。
- **输入数据**：`"在 core_db 中查看 ecif_customer 表 cert_type 字段 的分布"`
- **预期业务结果**：识别出数据源 `core_db`，表 `ecif_customer`，字段 `cert_type`。
- **实际系统表现**：`status="parsed"`, `extracted_table_name="ecif_customer"`, `extracted_field_name="cert_type"`。
- **智能化判定**：**机械通过**。完全依赖正则表达式捕获。

---

### TC-DIM-A03：用户意图理解 - 业务口语化需求（无技术表名）
- **测试目标**：验证业务人员描述业务概念时系统能否推导物理对象。
- **输入数据**：`"在 core_db 统计有效正常客户的证件类型数量"`
- **预期业务结果**：利用 Schema Linking 定位到客户表与证件类型字段。
- **实际系统表现**：`status="need_clarification"`，因未带“表”、“字段”标识而无法提取目标。
- **智能化判定**：**缺失 Schema Linking**。

---

### TC-DIM-D01：RAG 检索能力 - 专业银行业务词分词与同义词覆盖
- **测试目标**：检验当前分词器对银行复杂业务复合词及同义词的检索能力。
- **输入文本**：`"个人住房按揭贷款逾期90天以上借据余额"`
- **测试对比查询**：`"房贷"`、`"住房公积金贷款"`
- **实际系统表现**：
  - 分词结果生成了二元字符切分：`['个人', '人存', '存款', ...]`；
  - 查询“房贷”时的 Token 与目标 Token 语义交集为 0；
- **智能化判定**：**基础级**。无银行专有词典，无 Query Rewrite 扩展同义词能力。

---

### TC-DIM-E01：幻觉控制 - 编造不存在物理字段拦截
- **测试目标**：检验后验护栏对模型编造物理表字段引用的拦截有效性。
- **输入数据**：
  - 合法上下文物理范围：`[("source", 101, 201), ("mart", 301, 401)]`
  - 模型生成输出：包含 `{"kind": "source", "table_id": 999, "field_id": 888}`
- **预期结果**：系统必须以安全异常阻断，不得写入需求草稿。
- **实际系统表现**：抛出 `HTTPException(422, "生成结果引用了范围外的物理字段")`。
- **智能化判定**：**强确定性合规防护（优秀）**。

---

### TC-DIM-F01：SQL 能力 - AST 语法树安全拦截
- **测试目标**：检验 SafeSqlExecutor 对破坏性 SQL 的拦截能力。
- **测试输入**：
  - `DROP TABLE test_table`
  - `DELETE FROM test_table WHERE id = 1`
  - `UPDATE test_table SET name = 'x'`
  - `INSERT INTO test_table VALUES (1)`
  - `ALTER TABLE test_table ADD COLUMN col int`
  - `TRUNCATE TABLE test_table`
- **预期结果**：全部被 `validate_and_prepare` 判定为非法并拒绝。
- **实际系统表现**：抛出 `ValueError("Only SELECT statements are allowed")` 或 `ValueError("DDL/DML statements are not allowed...")`。
- **智能化判定**：**只读安全隔离优秀**。

---

### TC-DIM-F02：SQL 能力 - SQL 生成逻辑审查
- **测试目标**：验证系统所谓“SQL 分析生成”到底是不是模型生成的。
- **实际源码定位**：`_build_profile_sql` 采用写死的 Python f-strings：
  - `select count({field}) + sum(case when {field} is null then 1 else 0 end) as total_count...`
- **实际系统表现**：完全不经过大模型，无论表有何业务背景，仅执行固定 3 段 SQL。
- **智能化判定**：**伪智能模板**。

---

### TC-DIM-G01：Agent 能力 - 工具绑定与循环判定
- **测试目标**：检验大模型服务层是否支持 Agent Tool Calling。
- **测试对象**：`OpenAICompatibleLLMService`
- **实际系统表现**：
  - 仅实现 `chat_json` 与 `chat_stream`；
  - `hasattr(service, "bind_tools")` 为 `False`；
  - 无工具注册、工具分发、执行结果回传、自我纠错逻辑。
- **智能化判定**：**非 Agent 架构**。

---

### TC-DIM-J01：鲁棒性 - 非法结构与字段注入防御
- **测试目标**：测试 Pydantic Schema 对畸形或恶意 Prompt 注入字段的防御。
- **测试输入**：`{"business_definition": 12345, "unexpected_field": "injected"}`
- **实际系统表现**：Pydantic 严格触发 `ValidationError`，拒绝畸形数据。
- **智能化判定**：**工程健壮性优秀**。
