# 05｜企业级 Agent 架构：在银行可上线比“会自主调用”更重要

## 一、Agent 安全

### 威胁面

- Prompt Injection：文档中夹带“忽略系统规则、调用某工具”。
- Tool Abuse：模型构造越权参数、任意 SQL、任意 URL 或文件路径。
- Data Exfiltration：把 restricted 数据发送到外部模型或写进日志。
- Hallucinated Action：在证据不足时创建错误口径或修改最终数据。
- Denial of Wallet：无限循环、超长上下文、并行工具爆炸导致费用失控。
- Supply Chain：模型、embedding、reranker、包和镜像版本变化。

### 控制

- 系统指令与检索内容分离；检索内容永远视为数据。
- 工具白名单、Pydantic Schema、资源归属校验、网络/路径 allowlist。
- 读工具优先；写操作幂等；高风险写操作人工确认。
- 步数、并发、Token、费用、超时和结果大小限制。
- 所有模型输出、工具输入/输出在持久化前脱敏。

项目亮点：`SafeSqlExecutor` 只允许受控只读查询，Git 远程主机有 allowlist，凭据通过环境变量注入，敏感知识限制外部 embedding/LLM。

## 二、权限

### 四层权限

1. **身份**：用户是谁，token 是否有效。
2. **角色/权限**：能否查看项目、生成草稿、审核、签署 UAT。
3. **资源归属**：请求的 field/mapping/document 是否属于已授权项目。
4. **数据内容**：同一文档内哪些敏感级别可外发、显示或记录。

### Agent 特有规则

- 每次工具调用都鉴权，不能只在 Agent 启动时检查一次。
- project_id/institution_id 从服务端上下文派生，不让模型决定。
- Tool 输出也按权限裁剪；不可见记录不能通过“数量、错误差异”侧漏。
- 需要审计“谁让 Agent 做什么、Agent 调了什么、产生了什么变化”。

项目落点：`auth/dependencies.py`、`permission_service.py`、`resource_guard.py`。

## 三、数据隔离

### 应用层

- 所有核心表包含 `institution_id` 或 `project_id`。
- Repository/Service 查询默认带 scope，而不是靠调用者记得加 where。
- 缓存 key、向量 metadata、Celery payload、对象存储 key 都必须带租户范围。

### 数据库层

- PostgreSQL RLS 可作为纵深防御，但不能替代应用权限。
- 连接池上下文要正确设置租户，事务结束必须清理，避免复用泄漏。
- 平台管理员和数据库 owner 的绕过行为要审计。

### 向量库

- 先做 metadata filter 再 Top-K；不可先全局召回后在应用端剔除。
- collection 分租户或共享 collection + 强制过滤要基于容量与隔离等级选择。

## 四、Human in the Loop

### 何时必须人工

- 证据缺失或高权威证据冲突。
- 物理来源字段未在目录/血缘中验证。
- 口径影响监管报送范围、金额或统计逻辑。
- 脚本变更为 high/critical。
- 模型建议修改 final_content、关闭问题或通过 UAT。

### 好的人工任务

- 附带原问题、Agent 草稿、证据、冲突点、建议操作和影响范围。
- 支持采用、修改、驳回、要求补证。
- 保存决定人、时间、前后快照和理由。

项目已有 `WorkflowInstance`、`ReviewTask`、`ReviewDecision`、`ScenarioReviewPackage` 和 UAT；Agent 应接入，而非自建另一套审批状态。

## 五、Agent Evaluation

### 离线

- 固定输入状态和 Mock 工具结果，验证工具选择与参数。
- 黄金轨迹不是要求每一步完全一致，而是检查关键工具、禁止动作和结果。
- 对抗集：越权、注入、过期证据、冲突、空结果、工具超时。

### 在线

- 任务成功率、人工采用率、人工编辑距离。
- 错误/循环/超时率、P95 步骤数和延迟。
- citation 有效率、无证据拒答率、权限违规率。
- 每个任务 Token、工具成本和总成本。

### 发布门禁

任何 Prompt、模型、工具描述、检索配置或代码变更，都要触发关键集回放；安全用例必须 100% 通过。

## 六、Trace

一个 Agent trace 至少包括：

```text
trace_id / request_id / project_id / user_id
agent_version / prompt_version / model_profile
step_no / decision / reason_code
tool_name / validated_args_hash
tool_result_summary / result_ids / duration / status
retrieval_log_id / model_call_log_id
state_before_hash / state_after_hash
final_outcome / human_review_id
```

不要把密钥、完整敏感输入、数据库原值写入 trace。需要可回放时保存脱敏快照和不可变引用。

## 七、Observability

### 三根支柱

- Logs：结构化事件、request/trace/correlation ID。
- Metrics：吞吐、错误、延迟、Token、成本、队列积压、评测质量。
- Traces：API→检索→LLM→工具→数据库→审核的跨度关系。

### 项目现状

- `core/observability.py` 已有 request ID、结构化日志、HTTP 指标和限流。
- `RetrievalLog`、`ModelCallLog`、`AuditLog`、`BackgroundJob` 提供业务轨迹。
- 待补：统一 trace_id、LLM token/cost、工具 span、分布式 trace、质量指标告警。

### 告警例

- 物理字段幻觉 > 0：立即阻断发布。
- 无证据拒答率突然下降：可能 Prompt 漂移。
- citation 无效率 > 0：阻断生成接口。
- P95 延迟/成本超预算：降级 Top-K、模型或转异步。
- 队列积压和重试激增：检查 Worker/依赖故障。

## 八、Cost Control

成本不是只看模型单价：

```text
总成本 = 生成 Token + embedding + rerank + 工具/数据库
       + 向量存储 + 失败重试 + 人工审核 + 运维
```

控制手段：

- 按任务路由模型：抽取/分类用小模型，复杂冲突分析才用大模型。
- 去重和缓存 embedding；缓存必须包含项目、权限、版本和 Prompt 配置。
- 动态 Top-K 和 rerank depth。
- Prompt 去冗余，证据按 claim 选择。
- 每任务预算、每项目配额、异常熔断。
- 低价值批量任务走队列，支持合并和取消。

## 九、银行场景架构

```text
Client
  ↓ JWT / project context
FastAPI + Resource Guard
  ↓
Agent Orchestrator ── Budget / State / Trace
  ├─ Knowledge Tool → Hybrid Retriever → PostgreSQL + Vector Store
  ├─ Catalog Tool   → Metadata Catalog (read-only)
  ├─ Lineage Tool   → SQL/Shell Lineage + Impact
  └─ Question Tool  → Review/Question Workflow
  ↓
LLM Gateway → data-classification policy → local/external model routing
  ↓
Deterministic Validators
  ↓
AI Draft (separate from final_content)
  ↓
HITL → UAT → Audit → Deliverable
```

## 十、面试回答模板

> 银行 Agent 的核心不是自主性最大化，而是把自主性限制在可审计边界内。我采用项目级权限、工具最小权限、数据分级路由、步骤和费用预算；模型只做有限决策，Executor 每次重新鉴权，关键结果经过确定性校验。AI 草稿与人工最终值物理分离，证据冲突、物理字段未验证和高风险变更都会进入人工流程。全链路用 trace、retrieval/model/audit log 关联，并用安全回归集阻断发布。

## 阶段作业

1. 为字段 Agent 做 STRIDE 风格威胁清单和控制矩阵。
2. 画权限矩阵：角色 × 资源 × 动作 × 是否需审批。
3. 设计 20 条安全评测，包括 Prompt Injection、跨项目、任意 SQL、无限循环。
4. 给出每次 Agent 任务的 Token、步骤、延迟和人民币预算。
