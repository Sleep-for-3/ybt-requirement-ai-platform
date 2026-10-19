# C06 / C07 / C08 修复交付复核

日期：2026-10-06；代码：`3db4db6516a2c2cd495fe4109701a5a6451cb393`。

## 证据边界

只读产品源码。自写复核脚本使用内存 SQLite，在导入 app 前固定所有 provider 为 mock；实际执行 `run_evaluation → grounded_answer → get_prompt_runtime` 链路，仅检索和模型调用边界使用 spy，引用授权校验使用受控替身。没有真实模型、网络、银行数据库或业务服务操作。

- [独立复核脚本](repro_evaluation_followup.py)；执行退出码 0。
- [独立实际输出](evaluation-followup-result.json)。
- 原有专项测试 `test_rag_evaluation_fidelity.py` 与 `test_rag_evaluation_semantic.py` 隔离运行：**18 passed in 56.86s，exit 0**；不代表完整后端 1507 条的独立重跑。

## 已确认修复

C06 显式选择 B 时，实际 runtime 两次均为 B/id2，run 配置记录 B。C07 timeout 路径不再把该样本记成生成成功，逐条结果具有 `answer_status=degraded`。C08 当前 hash 纳入新字段，按样本 id 排序。不得将这些已成立的改动重新描述为完全未修。

## 仍需补交

### 1. C06 默认模型的运行摘要仍与实际执行不一致（P2）

位置：`backend/app/services/evaluation/rag_evaluator.py:35`、`:47`、`:50`、`:51`；`backend/app/services/llm/prompt_runtime.py:139`。

触发：未显式指定 `model_profile_id`，数据库已有启用的 A。前端创建评测正是此默认模式（`frontend/app/evaluations/page.tsx:66`）。

实际输出：run `chat_model=null`、`chat_profile_id=null`，实际 runtime 为 `model-A/id1`；逐条执行元数据已正确记录 A，因此可以定位差异。若环境默认另有名称，run 摘要还会记录与 A 不同的环境名称。

要求：评测开始时解析实际采用的 profile，并固定本次执行配置；摘要、逐条结果、模型日志一致。测试默认解析与显式选择都应覆盖实际问答链路，不能只测 `get_prompt_runtime` 单函数。

### 2. C07 引文命中仍能替代回答命中，错误/无关回答仍获 100% 代理分（P1）

位置：`backend/app/services/evaluation/rag_evaluator.py:90`、`:98`、`:111`。

触发：生成回答为“请确认其他业务”，不含预期关键词“余额”，只有引用内容含“余额”。

实际输出：`keyword_coverage=1`、`answer_correctness=1`、`successful_query_count=2`。说明当前修复只阻断了降级状态，正常状态下仍将检索到的证据文本与生成回答合并评分。原任务书已要求“匹配证据中的关键词不能证明生成答案正确”。

要求：回答代理质量的关键词检查基于生成回答，检索/引文命中另列指标；保留兼容字段解释，不能将关键词代理分命名或宣传为专家业务正确率。补一条“引文包含真值关键词、回答不包含”的真实链路回归。

### 3. C07 部分降级时结果页仍展示无分母的 100%（P1，原任务未闭合）

位置：`backend/app/services/evaluation/rag_evaluator.py:212`、`:217`；`frontend/app/evaluations/[runId]/page.tsx:17`、`:21`、`:37`、`:138`。

触发：2 条样本中 1 条正常、1 条 timeout。

实际输出：`status=completed`、`successful_query_count=1`、`degraded_query_count=1`、`answer_coverage_denominator=2`、`answer_correctness_denominator=1`、`groundedness=1`、`answer_correctness=1`。仅对成功生成求均值并保留显式分母本身可以接受，但必须同时展示覆盖率与统计范围。现页面未消费新增状态、分母或模型字段，只显示绿色 completed、Groundedness 100%，逐条状态只可从原始 JSON 展开查到。DSH 已承认未接前端，不能把原任务要求另行排期后仍宣布全部闭合。

要求：结果页醒目显示正常/降级/异常/待确认计数、生成覆盖率、条件均值分母和实际模型；逐条显示状态及降级原因，明确代理指标含义；无生成样本时显示“不适用”，不能拿 0% 与专家评价混为一谈。可保留执行完成状态，但配套区分“全部正常”“部分异常”“全部不可生成”的可用性提示。

### 4. C07 非 LLMRuntimeError 分支的降级原因被 null 覆盖（P2）

位置：`backend/app/services/rag/grounded_answer_service.py:103`–`:113`；`backend/app/services/evaluation/rag_evaluator.py:145`–`:148`。

触发：数据分类策略/输入准备等产生普通 `ValueError`，问答在 execution metadata 中正确构造 `degraded_reason=ValueError`，但没有顶层 `degraded_reason`。

实际输出：评测合并元数据后又以 `answer.get("degraded_reason")` 覆盖，最终持久化原因 `null`、状态 degraded。

要求：保留 metadata 内原因，顶层非空值才覆盖；补策略拒绝/一般 runtime 异常路径，确保保存受控原因，不泄漏原始敏感错误。

### 5. C08 只保存 hash，没有冻结完整用例快照，运行证据仍可能混用真值（P1/P2，原任务未闭合）

位置：`backend/app/services/evaluation/rag_evaluator.py:24`、`:37`、`:55`、`:61`、`:67`、`:79`、`:97`、`:133`、`:189`；`backend/app/models/entities.py:591`、`:595`。

触发：运行开始算出初始数据集 hash；第 1 条执行期间，另一个受控 SQLite Session 修改第 2 条 query 和预期关键词；因为运行仍持有 ORM 用例并反复 commit/expire，第二条读取到新值。

实际输出：执行的查询为“初始问题-1”“并发修改后的第二个问题”，run 仍报告初始 hash `8be3d7…`，实际修改后 hash 为 `75d0dd…`。run 仅存 hash/config，结果只有可修改用例 FK，没有完整快照。旧测试 `test_c08_an_edited_annotation_does_not_change_already_recorded_evidence` 只断言旧 hash 字符串未变；这不能证明旧输入与真值仍可读取或运行只使用冻结样本。

要求：开始执行前将实际用例输入、完整真值与 hash schema 规范化成独立不可变快照并持久化，后续查询与评分只用快照；结果页/API 能回看运行当时的输入与真值。优先使用现有 JSON 容量完成最小修补；如需迁移，仅隔离验证。补运行中编辑、运行后编辑、排序等价与从快照重新计算 hash 的回归。

## 必要验证与非缺陷边界

真实模型的 profile 切换、真实向量检索和银行专家正确率依旧未测，不能因 mock 通过就声称已经完成，也不应把其缺失当作上述源码修补延期的原因。C07/C08 前述缺口均在原任务书范围内，不属于新架构升级。
