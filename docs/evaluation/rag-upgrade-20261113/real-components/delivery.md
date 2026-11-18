# P0-A 至 P0-C 补验交付

2026-11-17 round47补充：当前工作区生产前端连接round46隔离PostgreSQL/Redis/Celery/Milvus和本地BGE API，真实浏览器通过登录失败/恢复、项目任务列表与既有详情、表单校验、证据原文下载哈希、桌面/窄屏与Escape交互。此次只浏览合成项目，不创建新任务，LLM为Mock且provider调用0；不能作为业务黄金集、留出或真实模型质量验收。round46后续formal-index-attempt1已证明合成文档1/1索引和原文哈希；round46初始报告的“空库/无索引”描述已被后续状态覆盖，保留该报告作为启动时快照。完整报告、机器证据、失败attempt和截图见 `docs/development/long-run/rounds/ROUND-20261117-47.md` 与相邻 `evidence/ROUND-20261117-47.json`。

2026-11-15 后续：本报告保留原快照结果。漏解析及重复列已经修复，104 题完成代理源文件审核，并新增 20 道独立来源留出；最新真实生成与裁判结果见 [原文审核验收](source-review-acceptance-20261115.md)。代理复核不等于人工业务批准。

2026-11-17 round44 进度更新：已找到并按 SHA-256 核实原上传工作簿，在只读隔离 PostgreSQL 中完成当前解析与冻结入库版本的逐 sheet/行/单元格对账。当前 v3 解析为 9/9 sheet、5,958 单元且当前输出未见非空源值漏失；历史冻结 v1 仍为 5,922 单元、7/9 sheet，708 个源非空值未保存在旧单元文本中。旧语料和索引没有被原位修改。下一步需以新文档版本重解析、审核、建立独立索引并验证回退；P0-A 独立留出来源、真实模型/裁判和 P0-C 全链路仍未完成。详见 [round44 对账交付](../../../development/long-run/rounds/ROUND-20261117-44.md) 与 [round44 机器证据](../../../development/long-run/evidence/ROUND-20261117-44.json)。不得把已观察工作簿题目视为独立留出。

更新：2026-11-14，Asia/Shanghai。代码保存在当前未提交工作区，未提交、推送或修改生产数据。实验仍沿用既有架构，未默认启用重排、查询规划、阈值拒答或语义裁判。

## 1. 结论

WSL 组件环境、真实入库与索引、治理和浏览器链路已经补验。2026-11-14 又完成了 DeepSeek 真实模型的 104 题有界回放；详见 [真实模型验收](real-generation-acceptance-20261114.md)。业务质量门禁仍保持阻断：工作簿存在解析丢失，人工金标准及独立文档留出未完成，答案级人工支撑和裁判未完成。真实模型输出只能作为基线，不能替代黄金集审核。

| 检查 | 实测结果 | 证据 |
| --- | --- | --- |
| 统一后端回归 | 215 passed，1010.06 秒，SQLite/Mock | `correctness.junit.xml` |
| 最后受影响的完整专项 | 80 passed，31.00 秒，SQLite/Mock | `final-fixes.junit.xml`；与上一行重叠，不累加 |
| 前端问答/历史/登录契约 | 8 passed | 三个 Node 契约测试；命令见下 |
| TypeScript | `tsc --noEmit` 退出 0 | 已恢复 Next 开发服务生成的配置噪声 |
| PostgreSQL | 16.15；空库现有迁移到 `202611010014` | `component-inventory.json`、本机 `migrations.log` |
| Redis / Celery | Redis 7.4.11；真实 Celery 作业完成并持久化任务 ID | `component-inventory.json` |
| Milvus / Embedding | 历史冻结 v1 集合 5,922 行；当前 v3 解析输出 5,958 单元，尚未重导入或重建索引 | `component-inventory.json`、round44 只读对账 |
| 原文件 | 上传文件、存储字节与数据库哈希一致 | `component-inventory.json` |
| 服务就绪 | 200，数据库、存储、Redis、队列、向量、Embedding、索引均 healthy | `component-health.json` |
| 版本和权限治理 | 35/35 | `component-governance.json` |
| 浏览器 | Chromium 8/8，1440×1000 与 390×844 | `browser-results.json`、两张 `evidence-*.png` |
| 原题集真实混合检索回放 | 104/104 执行完成，失败 0；检索阶段 p95 2455.04 ms，样本 104 | `component-retrieval-results.json`；不含生成，无回答延迟 A/B 结论 |
| 真实生成/真实裁判 | DeepSeek 103 次真实生成、1 次网络降级；真实裁判未运行 | 104 题回放结果见 `real-generation-acceptance-20261114.md`；黄金集人工审核仍为 0/104 |

全量前端的 4 项既有静态契约失败沿用上层 `verification.md` 的记录，本次未扩大修改范围。没有远端 CI 或全量前端全绿结论。

## 2. 已修补的问题

1. 原实现将 `P0-V1` 与 `P0-V2` 都归一成数字前缀 `0`，冻结版本可能碰撞。现保留全部数字修订分量，已有年份版本测试一并回归。
2. “上一版”由检索器自动转入历史分支，但问答引用复核仍按非历史请求处理。现从原始用户请求推导一次历史资格，供检索及每次复核使用。历史答案或引用标志不能授予历史资格。
3. 归档资料和历史模式下的草稿可能通过向量候选重读。现共享可见性规则直接排除归档资料，并限制历史版本状态为 active/superseded；三种检索模式都有反例。
4. openpyxl 的 `max_column` 会扫描已用单元格，旧代码在逐行构建矩阵和正文时重复调用。现缓存边界及定位末列，保持原解析内容和定位；原文件修后离线解析 5,922 单元实测 22.52 秒。此性能修复不改变表头映射或重复列覆盖语义。
5. 验收恢复工具处理长作业、JWT 续期、文件名数字脱敏和原文件哈希，避免按展示文件名寻找旧任务。一次重复候选已撤回，记录及单元保留在隔离库中；原冻结 V1 仍为活动版本，不参与实际检索的撤回候选不会成为人工锚点。
6. 人工审核导入拒绝缺审核、缺证据、跨快照、未知/不可用单元，以及相关证据或角色证据跨调参/留出共享文档的情况。

此前已实现的中文码值、字段码、否定反例、独立确定性检查、judge 无权覆盖硬阻断、低置信度与可信等级约束、非有限重排分数等仍保留，具体见上层 README 和统一回归。

## 3. 真实环境与隔离范围

| 服务 | 本机入口 | 隔离方式 |
| --- | --- | --- |
| PostgreSQL | 127.0.0.1:15439 | 新容器 `rag-p0-20261113-pg`，数据库 `rag_accept` |
| Redis | 127.0.0.1:16389 | 新容器 `rag-p0-20261113-redis` |
| Milvus | 127.0.0.1:19530 | 复用已有 WSL 服务，只创建 `rag_p0_20261113_*` 集合 |
| BGE | 127.0.0.1:18097 | 本地缓存 ONNX 模型，512 维，CPU；未从外网下载新模型 |
| API | 127.0.0.1:18095 | 隔离数据库、存储目录、队列和强制登录 |
| 前端 | http://127.0.0.1:18096 | 独立 `.next-rag-components` 输出目录 |
| Celery | `rag-p0@local` | solo，concurrency=1；只消费隔离 Redis |

本机检查时，原 WSL PostgreSQL 的 5433 服务仍可读；未修改原数据库、卷或已有 Milvus 集合。Ollama 已启动，但现存模型只有 Embedding，没有生成模型。没有安装或调用新的生成模型。

账号密码、数据库连接串和进程记录只在 `.local-run/rag-p0-components-20261113/{state,environment,processes}.json`，不进入交付目录。目录中存放管理员和只读审核夹具账号。请勿将整个目录作为公开附件。

## 4. 治理与页面证据

真实治理覆盖：当前版排除过时 V1；冻结 V1；缺失钉扎版本；历史时点；禁用单元；撤回版本；归档文档；项目适用范围变化；未来生效；过期；请求期间正文变化；历史来源撤回；越项目原文；无项目权限的用户问答和检索；回答时 V1 原文件；真实需求快照钉扎；无合规证据时待确认且低置信度。

当前正式索引只包含已启用现行单元。V2 索引建好后，纯向量模式无法召回没有向量的 V1；探针明确记录 `retrieved=0/outcome=no_eligible_evidence`。这验证的是阻断错误版本，不代表历史向量召回已实现。关键词和混合模式实际取到 V1，未为通过测试补造旧版向量。

浏览器真实顺序为：错误密码 401 → 正确表单登录 200 → 提问 → 追问完整历史 → 清空和切项目 → 顶部选干扰项目打开已有任务 → 原文请求仍使用任务所属项目与 V1 → 下载链接的 Blob 字节 SHA-256 匹配 V1。此时文档现行版已是 V2。移动端无横向溢出，截图已人工查看。

源登录配置的只读诊断见 `login-configuration-probe.json`：前端指向 8011，但该 API 未监听；后端 `.env` 指向未监听的 PostgreSQL 5432；相同连接信息仅改端口至 5433 可查询到当前迁移。此证据证明当前配置问题，无法回溯确认历史登录失败是否由同一原因引起。未覆盖源 `.env`、未重置原账号。

## 5. 原始语料与人工审核

原文件是归档目录中的 `【知识库共享】一表通答疑汇总_20251103171632.xlsx`，1,666,351 字节，SHA-256：

`51228a75d5f22ed9a058c9a7c29834989ab56da95e35435164084c537b9ec311`

解析识别 7/9 张 sheet，输出 5,922 单元，跳过 200 空行。2 张非空表未识别表头：`记录校验问答`、`穿透层问答`。`一致性校验问答` 等存在重复列名覆盖，原始结构和警告完整保留。`parse_blocked=true`，没有将“任务完成/已激活”当作内容完整。

104 题的完整逐题原文审核包位于本机 `.local-run/rag-p0-components-20261113/human-review.json`。18 题有可核对的锚点建议，86 题仍有旧证据无法解析，人工批准 0。每题包含问题、原标注与来源、旧证据的 sheet/cell 锚点建议、当前召回前五项、原文和定位；`reviewer`、`relevant_ids`、`roles`、`must_refuse` 均待人工填写。旧 ID 不会自动变成本库金标准。历史候选拆分为 84/20，不等于已经证明文档独立；当前摘要的 `document_overlap=[]` 只覆盖已解析建议，不能外推到未解析部分。

审核导入必须使用与本次 `corpus_hash` 一致的快照。来自同一个工作簿的证据不能仅因 sheet、问题家族或旧 ID 不同就冒充独立文档留出。金标准、独立留出和语料修正后都要产生新题集/语料版本，保留旧快照重新测量。

完整语料快照和审核正文在被忽略目录；交付目录的 `component-environment-summary.json` 保存代码、Prompt、配置、索引和源文件摘要，`component-retrieval-results.json` 保存逐题检索结果。`component-baseline.json` 和 `business-gate.json` 明确保留未完成阻断。检索回放中的 `context_ids` 是既有 12 条窗口的投影，不是实际生成模型使用记录；`cited_ids=[]`，不据此计算引用支撑或答案完整率。

104 题均使用真实混合检索，执行失败 0，项目/版本可见性违规测量为 0；前后语料与代码哈希一致。Hit@5、MRR、nDCG、引用支撑率和答案完整性均为 null、样本数 0。`refusal_samples=0`，误拒/漏拒计数 0 不代表误拒/漏拒率为零。自身对比也被发布门禁拒绝，不能把工程执行完成转成业务质量通过。

## 6. 复现与恢复

以下命令从 `backend` 目录运行，使用当前已建环境。`run` 从忽略配置读取连接信息，防止本机 `.env` 选错数据库；没有外部生成调用。

```powershell
.\.venv\Scripts\python.exe scripts/rag_component_environment.py run --workspace ../.local-run/rag-p0-components-20261113 -- scripts/rag_component_acceptance.py inventory --workspace ../.local-run/rag-p0-components-20261113 --output ../docs/evaluation/rag-upgrade-20261113/real-components
.\.venv\Scripts\python.exe scripts/rag_component_environment.py run --workspace ../.local-run/rag-p0-components-20261113 -- scripts/rag_component_acceptance.py governance --workspace ../.local-run/rag-p0-components-20261113 --output ../docs/evaluation/rag-upgrade-20261113/real-components
.\.venv\Scripts\python.exe scripts/rag_component_environment.py run --workspace ../.local-run/rag-p0-components-20261113 -- scripts/rag_component_acceptance.py replay --workspace ../.local-run/rag-p0-components-20261113 --dataset ../docs/evaluation/rag-upgrade-20261113/dataset.json --output ../.local-run/rag-p0-components-20261113/replay-final
.\.venv\Scripts\python.exe scripts/rag_component_delivery.py --workspace ../.local-run/rag-p0-components-20261113 --dataset ../docs/evaluation/rag-upgrade-20261113/dataset.json --legacy-sqlite ../../_assessment_work/dev_e2e/dev_agent_ux.db --output ../docs/evaluation/rag-upgrade-20261113/real-components
.\.venv\Scripts\python.exe scripts/rag_regression.py compare --baseline ../docs/evaluation/rag-upgrade-20261113/real-components/component-baseline.json --candidate ../docs/evaluation/rag-upgrade-20261113/real-components/component-baseline.json
```

最后一条应退出 1，不能把自比较当作业务放行。回放期间不得改代码或语料；104 题完成后重新核验二者哈希。需要重测时先另存旧结果，避免覆盖已发布测量。完整回归：

```powershell
.\.venv\Scripts\python.exe scripts/rag_regression.py correctness --junitxml=../.local-run/p0-recheck.xml
```

从 `frontend` 目录运行：

```powershell
$env:RAG_ACCEPT_FRONTEND='http://127.0.0.1:18096'
node tests/rag-upgrade.browser.acceptance.mjs ../.local-run/rag-p0-components-20261113/state.json ../.local-run/rag-browser-recheck
node --test tests/knowledge-history.test.mjs tests/login-contract.test.mjs tests/knowledge-contract.test.mjs
npx --no-install tsc --noEmit
```

Windows 重启后，先检查已有服务和 `processes.json`，仅启动缺失服务，不能向仍在运行的队列再开同名 worker。WSL 容器可按原名启动，不删除或重建：

```powershell
wsl.exe --exec docker start ybt-dev-etcd-1 ybt-dev-milvus-minio-1 ybt-dev-milvus-1 rag-p0-20261113-pg rag-p0-20261113-redis
```

以下分别在独立终端执行，只用于对应本机服务确认已退出时，均从 `backend` 运行。启动前检查 18095/18097 端口及 worker 进程；凭据保留在本地配置中。

```powershell
.\.venv\Scripts\python.exe scripts/rag_component_environment.py run --workspace ../.local-run/rag-p0-components-20261113 -- -m uvicorn app.local_embedding_server:app --host 127.0.0.1 --port 18097
.\.venv\Scripts\python.exe scripts/rag_component_environment.py run --workspace ../.local-run/rag-p0-components-20261113 -- -m celery -A app.workers.celery_app worker --pool=solo --concurrency=1 --hostname=rag-p0@local --loglevel=INFO
.\.venv\Scripts\python.exe scripts/rag_component_environment.py run --workspace ../.local-run/rag-p0-components-20261113 -- -m uvicorn app.main:app --host 127.0.0.1 --port 18095
```

前端若已退出，从 `frontend` 启动；`NEXT_PUBLIC_APP_COMMIT` 和 `NEXT_PUBLIC_BUILD_TIME` 应从隔离 `environment.json` 的同名后端值设置，以免发布标识显示 unknown。

```powershell
$env:NEXT_PUBLIC_API_BASE_URL='http://127.0.0.1:18095/api'
$env:NEXT_DIST_DIR='.next-rag-components'
node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 18096
```

新建环境使用 `rag_component_environment.py prepare`，它拒绝覆盖已有环境或占用的固定端口。Docker 的 PG/Redis 创建需从 PowerShell 调用 WSL，不能在本机 Python 子进程中调用 WSL：本机已复现后者 `Wsl/E_ACCESSDENIED`。现有环境无需再次 prepare 或 migration。

## 7. 失败记录与回退

| 现象 | 原因与处理 | 是否仍阻断 |
| --- | --- | --- |
| 20 分钟等待器超时，索引仍 running | 本地完整索引约 28 分钟；等待上限改为 60 分钟，续期登录并恢复原任务 | 否，原 job 5 已完成 |
| 浏览器 SHA 为“空内容”的哈希 | Chromium response 监听体为空；实际页面下载 Blob 和直接 API 字节正确；改为对下载链接 Blob 严格验哈希 | 否，8/8 复验 |
| 冻结 API 测试仍得到 V2 | 验收请求误传服务内部字段；改用真实、哈希有效的 RequirementRevision | 否，首次失败记录保留在 `component-governance-first-attempt.json` |
| 第二轮发现归档文档进入向量候选 | 真实产品问题，已补共享过滤和三模式反例 | 否，最终 35/35 |
| 恢复时多出同字节候选 | 作业文件名数字被脱敏；已修复恢复查找并校验哈希，候选撤回且保留审计数据 | 否，原冻结活动版本和索引未切换 |
| 原表跳过 sheet/重复列覆盖 | 解析契约不能保证完整性；未静默更改别名、拼接重复列或伪造缺失业务语义 | 是，语料质量门禁保留 |

实验回退仍为关闭规划/token/重排实验、排序 authority、清空影子阈值；正确性修复不设旁路。新增环境与正式资源隔离，停止时按 `processes.json` 核对 PID/命令，再停止本任务拥有的进程和新增 PG/Redis 容器；共享 Milvus/etcd/MinIO 不随实验停止。保留数据库、原文、集合和报告，不执行删除、强制 Git 重置或源环境写入。

## 8. 达到业务交付条件的后续步骤

1. 修复或业务确认原始工作簿的未识别表头及重复列含义，以新语料版本导入；保留本次阻断快照。未知含义不能由工程脚本猜测。
2. 指定业务审核人，逐题审核本机 `human-review.json` 的证据、角色与拒答；补充独立来源文档，重新建立无文档和问题家族泄漏的调参/留出集，通过 `rag_gold_review.py import` 生成新快照。
3. 显式提供真实生成与裁判模型、最大调用数、token、最长时长和费用预算。预算缺省为零，当前工具不会自动调用源 `.env` 的外部模型。
4. 在同一冻结环境对基线/候选分别进行真实生成，审核实际引用支撑、答案完整性、误拒/漏拒；单独统计超时和预算耗尽。留出 Hit@5、MRR、引用支撑率不降且分母非零，p95 回答延迟增幅不超过 20%，安全违规为零，方可解除门禁。

只有上述条件完成，才能宣称 P0 业务验收通过，并开始 P1 的重排、多轮和拒答校准 A/B。当前保持默认实验关闭。
