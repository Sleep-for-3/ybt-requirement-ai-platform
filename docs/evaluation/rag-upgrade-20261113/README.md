# RAG 渐进升级交付与验收

## 当前停止状态（2026-11-18，Round65）

用户要求本轮后停止长期开发，**无自动下一动作**。Round65 使用生产构建和隔离真实 API、合成三态任务进行页面验收：attempt8 通过 12 项后在失败详情键盘顺序遇到未识别焦点，原因待复核，整体未通过；实际重跑和其余详情场景未完成。未调用外部模型或修改产品 UI。P0-A 缺独立新来源，P0-B/C、UX 和远程部署验收未完成，P1/P2 未完成。用户已授权代理按原文逐题审核。详见 [Round65](../../development/long-run/rounds/ROUND-20261118-65.md) 与 [当前检查点](../../development/long-run/CURRENT-CHECKPOINT.md)。

## 当前长期执行补充（2026-11-18，round64）

Round63引用治理409契约已在独立Uvicorn API与身份一致的Next生产构建上完成真实浏览器验收47/47：隔离PostgreSQL资料在生成/judge窗口撤回或禁用时返回409固定提示，不展示旧答案/引用；恢复后正常问答200，普通输入错误400。登录、桌面/390px布局与错误恢复通过。生成、规划、裁判为受控Mock，provider增量0/0；合成fixture非gold/holdout，无公网写入。这补齐了冲突HTTP页面链路的技术子项，不代表真实模型/业务、P0整体或公网通过。P0-A仍缺新来源，P0-B/C及UX总目标保持进行中，P1/P2与公网切流锁定。详见[Round64](../../development/long-run/rounds/ROUND-20261118-64.md)及[机器证据](../../development/long-run/evidence/ROUND-20261118-64.json)。

## 当前长期执行补充（2026-11-18，round63）

知识问答对回答期间资料变化返回409和固定重试提示，普通ValueError保持400。后端130项、前端7项、隔离PostgreSQL/ASGI 11项及合成API开发浏览器4项通过；生成/judge期间撤回或禁用均未返回旧答案，恢复后正常引用。外部模型增量0/0。旧冻结数据、向量索引、既有服务和公网保留；当前独立部署入口、生产浏览器及真实模型验收仍开放，P0-B/C和UX保持进行中，P0-A缺新来源，P1/P2门禁不变。详见[Round63](../../development/long-run/rounds/ROUND-20261118-63.md)。

## 当前长期执行补充（2026-11-18，round62）

身份一致的独立生产构建连接真实隔离API，只读浏览器12/12通过：登录、既有任务详情、读取失败重试、只读权限提示、桌面/390px、证据抽屉Escape和焦点归还。现有样本仅已完成任务；权限和网络故障为浏览器注入，完整键盘顺序及其他状态仍待验。没有业务写请求或模型调用。P0-A仍缺新来源，P0-B/C和UX未关闭，P1/P2及公网切流保持锁定。详见[Round62](../../development/long-run/rounds/ROUND-20261118-62.md)。

## 当前长期执行补充（2026-11-18，round61）

任务台 UX 继续独立于 P0-A 来源阻塞推进：状态徽标已增加语义图标并移除页头流程说明文案，55 项任务台视图测试、TypeScript、最终源码独立生产构建及合成 API 浏览器 3/3 通过。真实 API、详情状态、错误恢复、键盘顺序和身份一致的视觉验收尚未完成，UX 目标保持 `in_progress`。P0-A 仍 `blocked_external`，P0-B/C 未关闭，P1/P2 默认及公网切流保持锁定。详见[Round61](../../development/long-run/rounds/ROUND-20261118-61.md)。

## 最新进度（2026-11-17，round52）

P0-A 本机来源谱系/历史曝光/样本覆盖盘点工作包已完成，结论为 `blocked_external`，不是“尚未审题”：用户已授权代理逐题按原文审核，既有104工作簿题、20归档SQL题、12多源题均已观察并永久只作回归。另盘点到84份集市ETL SQL，其中56份内容SHA在项目9/11/12/14本地文件存储命中；整批来源包缺少足以证明未观测的谱系，不能转作holdout。现仍缺来源所有者授权用途、历史使用说明和按文档家族隔离的充分新材料。最小输入、逐来源处置和恢复步骤见[round52来源盘点](../../development/long-run/rounds/ROUND-20261117-52.md)。不需要用户逐题审核；来源包到位后由代理执行复核。P0-B/C继续推进，P1/P2保持锁定；round52无模型调用或数据/索引/远程写入。

更新：2026-11-16。起始代码：`dsh/handoff-20261025-round73@206d4313a5805613f5bf7e0b5db41390ab92d31f`。
变更保存在工作区，未提交、未推送。`isolated-environment.json` 另存实际源码文件哈希，不能只用未变化的 Git HEAD 代表本次实现。

## 实施状态

最新有效进度（round28，2026-11-16）：104工作簿+20SQL全题委托批准完成，保留旧gold，human_business_approved=false；SQL金标准改绑定真实正文18027/18030。124题真实生成/裁判/汇总完成：Hit@5=0.7130、MRR=0.6617、nDCG@5=0.6386、完整79/122、支撑264/373、误拒23/34、泄漏0；但tuning=124、holdout=0，因为全题均已观察，不能作为独立留出门禁。SQL 20题Hit@5=0/20且全部待确认，正文召回/装配仍是首要缺陷；裁判失败2、支撑降级16。candidate28生产构建、真实DeepSeek task15、四组治理异常页面/390px/焦点、28→26→28回退均通过；原公网未切换。累计额度800次/800万token，实时见共享BUDGET。P0未关闭、P1/P2未放行。详见[第28轮](../../development/long-run/rounds/ROUND-20261116-28.md)和[当前检查点](../../development/long-run/CURRENT-CHECKPOINT.md)。下方状态均按历史轮次解读。

最新有效进度（round19至23，2026-11-16）：十五道生成前委托批准的可答题已完成真实回归，Hit@5=15/15、引用支持27/27、完整13/15、角色入上下文16/17/实际引用15/17，泄漏0/15；6道待确认逐题分析，不能将其全部解释为误拒。规则编号误抽及其他字段冲突误降级已复现，round23新增反例修后相关88项/6子测试通过、边界补验77项/6子测试通过（有重叠，不相加），新身份真实复测待补。round19断连/裁判503/恢复三条真实浏览器路径通过；任务台六组交互通过，生产build待补。公网指定入口认证失败，尚无远端写入。累计96次provider/650097token，实时共享账本为准。P0仍未关闭，P1/P2未放行。详见[第21轮](../../development/long-run/rounds/ROUND-20261116-21.md)、[第23轮](../../development/long-run/rounds/ROUND-20261116-23.md)、[目标台账](../../development/long-run/GOALS.json)。下方为原轮次历史记录。

最新有效进度（round16至18，2026-11-16）：当前真实模型任务→V2激活→跨项目查看回答时V1原文、下载字节哈希及390px/Escape焦点归还已通过，使用独立合成项目，不能称业务金标准。真实业务三题完整2/3、实际引用支撑10/10，仍缺14170角色；另发现完整性评测遗漏合法实际引用，正在保留原答案补审。历史网络失败五题重试均real_model/HTTP200、项目版本泄漏0；四题待确认，一题grounded，未据此判业务通过。累计预算40次/246778token（实时以共享账本为准）。P0仍未全部关闭、P1/P2未放行。详见[第16轮](../../development/long-run/rounds/ROUND-20261116-16.md)、[第17轮](../../development/long-run/rounds/ROUND-20261116-17.md)及[当前检查点](../../development/long-run/CURRENT-CHECKPOINT.md)。以下较旧进度按原轮次保留，不覆盖最新结论。

长期执行第14至16轮：正文主张覆盖、裁判送模前引用范围、通用异常字段、数字分号切句四组64passed；来源等级与裁判回归两批102个不同用例通过（首批唯一旧无引用夹具失败修正后补验）；Agent模型身份/数值用量13passed。均为隔离证据。新源码293ea8035190的18110/18099运行环境已启动，正在冻结业务三题和准备独立任务文档版本验收；不得把旧18109结果当作新代码通过。详见[第14轮](../../development/long-run/rounds/ROUND-20261116-14.md)、[第15轮](../../development/long-run/rounds/ROUND-20261116-15.md)、[第16轮](../../development/long-run/rounds/ROUND-20261116-16.md)。

长期执行第11至13轮：时间误抽取、列表引用绑定已补反例并修复，分别63passed/6subtests和70passed/6subtests；第13轮提示专项74passed。当前真实三题完整性仍0/3、支撑7/8（1条裁判格式降级），不能放行。新前端当前真实登录恢复、任务最终空态桌面/390px、真实模型提问三项通过，任务详情/跨项目/冻结原文仍待补。累计22次/130145token，800次/800万上限。详见[第13轮](../../development/long-run/rounds/ROUND-20261116-13.md)。用户已授权代理逐题作业务批准，批准记录必须保留身份与依据；不再将缺少自然人签字自动视为需用户操作。

长期执行第10轮：新源码/真实组件/模型/API复测3个已知失败题，3次生成+6次裁判共53596token；完整2/3，实际引用支撑9/9，仍有1/1可答题状态误拒，整体未通过。已定位时间误当码值、列表引用绑定及缺失一表通角色。用户授权代理业务审核，3题原文预期另存批准记录，未批准缺陷答案发布、不冒充人工签字。详见[第10轮](../../development/long-run/rounds/ROUND-20261116-10.md)。

长期执行第9轮：用户已明确授权新增累计800次provider请求、800万token。新增发送边界共享预算护栏，修复/重试逐次计数、未知usage保守占额；80项及4子测试通过（26.30秒、exit0）。本批当前真实调用0，下一步新运行环境小批复测P0，不等于业务验收通过。详见[第9轮](../../development/long-run/rounds/ROUND-20261116-09.md)。

长期执行第6轮：修复可信等级只取实际引用证据的边界；未被答案引用的高权威候选不再抬高本次答案等级。新增反例及正确性/状态回归45项通过（732.46秒，exit=0）。这仍是 L2 隔离证据，未做真实模型、浏览器或业务批准验收。详见 [第6轮](../../development/long-run/rounds/ROUND-20261116-06.md)。

长期执行第7轮：对 `authority_rank` 增加来源类别上限，防止机构答疑、业务材料和技术材料被异常数值升级；47项正确性/状态回归通过（723.17秒，exit=0）。仍属 L2，P0-D03整体未关闭。详见 [第7轮](../../development/long-run/rounds/ROUND-20261116-07.md)。

长期执行第5轮：复现并修复了空对象、无判定和非法标签被误报为已完成裁判的网关问题。修前新增7个格式反例7/7失败；修复已明确区分 citation `invalid_model_response`、合法 `unknown` 与 faithfulness 的既有 `invalid_judgement`，不自动重试。修后 citation/faithfulness/overnight/vnext2 回归64项通过（3697.08秒，exit=0）。另增加只读18目标一致性检查器，11项工具自测通过，当前台账18项均未关闭。真实模型调用0。详见 [第5轮](../../development/long-run/rounds/ROUND-20261115-05.md) 与 [恢复检查点](../../development/long-run/CURRENT-CHECKPOINT.md)。

长期执行第4轮：生成证据改为白名单JSON，补publisher/工作表/行定位，明确建议、已同意反馈、不同体系与全零码值边界；3个失败反例后相关63项隔离回归通过。真实模型调用0，D01/D02仍需真实逐题复测；18106旧源码快照保留，不能用于本轮新候选身份。详见 [第4轮](../../development/long-run/rounds/ROUND-20261115-04.md)。

长期执行第3轮建立加载当前未提交源码的独立真实组件runtime：18106、Redis6/7，工具回归17项通过，API登录/ready及worker身份一致；766文件源码快照已保存在私密忽略目录。真实模型调用0，未重验完整问答/治理/浏览器，不替代P0-C。详见 [运行环境交付](../../development/long-run/rounds/ROUND-20261115-03.md)。

2026-11-15 长期执行第1轮补充：引用裁判超过20条主张时原实现重复claim ID并丢失后续批证据；新增反例先失败后修复。现在各批共用合规证据/版本钉扎、主张ID全局唯一、引用只汇总一次，后续超时保持未判定。两组隔离回归34项通过，未调用真实模型，不关闭P0-D03整体。当前后端readiness探针超时待诊断，不能认为真实组件/浏览器已通过。详见 [长期检查点](../../development/long-run/CURRENT-CHECKPOINT.md) 和 [本轮证据](../../development/long-run/rounds/ROUND-20261115-01.md)。

| 阶段 | 当前状态 | 已交付 | 尚未达到的条件 |
| --- | --- | --- | --- |
| P0-A | 工程基线已交付；业务未放行 | 原工作簿 9/9 sheet 已识别，5,958 条有效正文与 PostgreSQL 逐条一致；修复重复列覆盖；104 题完成代理源文件复核，另建 20 道独立来源首次留出；冻结及真实回放入口已交付 | 代理审核不等于人工业务批准；81 道旧题存在原文未定案或不完整；两份归档 SQL 来源有限；20 题现已观察，后续整改只能作为回归，发布须另冻结新留出 |
| P0-B | 核心修复已验证；业务缺陷整改中 | 中文码值/字段码、独立确定性校验、状态与可信度、检索及送模版本约束、请求期间复核、非有限分数；补修版本碰撞、历史意图及向量可见性；历史真实组件治理 35/35；本轮 124 题项目/版本违规及无效引用 ID 为 0 | 建议写成定案、跨体系结论、可答题误拒/状态、引用裁判适配及降级仍需整改；unknown 不等于造假，也不等于通过 |
| P0-C | 当前真实任务版本链路已通过；异常路径待补 | 真实 PG/Redis/Celery/Milvus/BGE及deepseek-v4.1-flash，round16页面任务、跨项目、V2激活后V1原文和字节哈希、桌面/390px/Escape焦点归还通过；round13真实登录恢复通过 | 当前生成网络失败、裁判失败、撤回/无权限的浏览器错误恢复仍需补验；合成资料链路不能代替业务金标准；P0-B依赖未关闭 |
| P1-A/B | 已有实验实现；未业务验收 | 默认关闭的 token 预算和查询规划；复用确定性分句；最多一次规划、三个子问题；页面内存最多六轮完整历史；原问题保留；历史答案不进入规划证据；原始分数和阶段诊断 | SQL 原文 20/20 未进前 20 候选；M10、V14 等真实业务对照、角色支撑与多轮质量尚未验收。当前仅建议开展 P1-A 定向实验，P1-B 新扩展暂缓 |
| P1-C | 影子诊断已实现；校准未完成 | 未标定分数仅供影子拒答诊断；配置指纹、质量差异和延迟门禁 | 阈值标定、人工/裁判一致性及同环境基线对照未完成；本轮真实离线裁判不等于在线灰度通过 |
| P2 | 未进入底座切换 | 本文列出受控实验顺序和进入条件 | P0 业务基线未通过，未切换分片、Embedding 或 Milvus 默认配置 |

首个里程碑的**工程交付**与**业务验收**必须分别判断。当前不能宣称 P0-A 至 P0-C 已全部业务验收，也不能宣称整个渐进计划已经完成。

### 本轮 P0 技术整改更新

2026-11-15 已完成来源角色边界的首个工程闭环：生成提示和引用裁判都携带受限的来源类别、知识类型、发布者、版本、生命周期和权威等级；机构建议、处理中意见和技术资料明确只能作为参考。引用文本蕴含与来源权威分开评估，未知、未覆盖、格式错误和降级不计作支持通过。P0 定向回归 56 项、知识问答/上传/索引专项 22 项分别通过；测试夹具固定隔离认证和进程内任务队列，避免开发机 .env 污染，不代表生产链路通过。

这只是隔离工程验证，不是业务放行。真实模型逐题来源边界、可答题误拒与状态一致性、裁判降级、网络降级和当前浏览器链路仍需补验；人工业务批准、同快照人工黄金基线和新的未观察留出也未完成。继续收口 P0 技术整改，保持默认策略不变。

**下一步决定：先收口 P0 技术缺陷；允许与失败直接相关、默认关闭的 P1-A 隔离对照实验，不等于正式越过 P0 门禁。P1-B 新功能扩展、P2 与默认策略发布继续等待。** 详细进度、`P0-D01` 至 `P0-D05`、外部补证 `P0-E01`、检索阻断 `P1-A-D01` 及关闭标准见 [最新交付的进度与整改清单](real-components/source-review-acceptance-20261115.md#当前进度与下一阶段决定)。81 道缺资料题可保持待确认，不要求用户重新标注全部题目，也不能靠模型补造批准口径。

2026-11-14 的真实组件结果、命令、失败反例和后续进入条件见 [P0 补验交付](real-components/delivery.md)。历史验收页面地址为 `http://127.0.0.1:18096`，使用前须复核服务就绪，本次文档更新未确认端口仍运行；隔离凭据位于 `.local-run/rag-p0-components-20261113/state.json`。语料正文及完整人工审核包保留在本机被忽略目录；交付目录只保留摘要、哈希、定位与测量结果。

2026-11-15 的漏解析修复、逐题源文件审核、独立留出及真实生成/引用裁判结果见 [最新原文审核验收](real-components/source-review-acceptance-20261115.md)。这轮使用项目 4 与独立索引；旧报告的 5,922 条、84/20 拆分和未运行裁判描述只适用于其历史快照，不代表最新结果。

最新结果：124 个问答请求返回，119 次真实生成、5 次网络降级；383 次离线裁判请求。最终完整性旧题 63/104、独立 SQL 留出 0/20；留出 Hit@5 为 0/20。124 题项目/版本可见性违规 0，引用支撑仅 40/409，另有 17 题引用裁判降级。解析和逐题测试工作完成，业务放行不通过。最终指标以 `real-components/source-review-results-corrected-v3-20261115.json` 为准，使用纠正后的 SQL 原文 ID；未将模型复核登记为人工业务签字。

## 主要行为

- 未运行语义裁判时显式返回 `verification_status=not_run`，可信等级上限为 C；待确认回答置信度为低，不能得到 A/B。
- 明确缺口、错误标识、错引串引、资料冲突和缺失证据角色优先于裁判的 `verified`。保留既有答案状态接口。
- 版本钉扎在候选过滤与送模前独立生效。找不到匹配证据时待确认；未登记在钉扎范围中的资料也不进入上下文。
- 送模前和生成后重读资料，检查正文、文档版本、启用状态、有效期、项目/机构适用范围和密级。回答期间变化要求重新提问。
- 历史引用资格来自本轮请求，不能由引用对象自带的 `historical` 标志授予。撤回资料仍不可使用。
- 原始 BM25、向量分、重排 logit 分开记录；现有展示分继续兼容。已核实HEAD与当前默认均为authority boost，strict权威优先是独立可选策略；A/B按实际快照对照。
- 查询规划、token 装配、相关性优先排序保持实验开关；未自动开启重排或统一阈值拒答。
- 历史仅在当前页面内存保存。清空、切换项目、问答模式或冻结版本会重置；每轮重新授权、重新检索。

## 产物

| 文件 | 含义 |
| --- | --- |
| `dataset.json` | 104 题、原始来源和未审核标注；`dataset_version` 是规范化 JSON 的 SHA-256 |
| `isolated-environment.json` | 本次代码、语料、索引、模型、Prompt 和配置快照；仅有一份合成资料 |
| `isolated-retrieval-results.json` | 104 题在合成语料上的逐题关键词回放、上下文和阶段诊断 |
| `isolated-baseline.json` | 显式阻断的隔离报告；业务指标为空、分母为零，未测的安全项为 null |
| `verification.md` | 最终测试结果、失败项与证据层级 |

`isolated-*` 验证的是工具可复现性，不是银行业务质量。该库只有夹具原文，104 道业务题并未配齐对应语料。其延迟不代表真实模型或正式 Milvus 的 p95。运行没有外部模型调用。

原始题集位于本地工作区父目录：

- `_assessment_work/rag-night-20261107/challenge/cases.json`
- `_assessment_work/rag-e2e-20261107/case-manifest.json`
- `_assessment_work/rag-e2e-20261107/v3-case-manifest.json`
- `_assessment_work/rag-e2e-20261107/v4-case-manifest.json`
- `_assessment_work/rag-e2e-r5-20261108/c-case-manifest.json`

规范化后的快照自包含问题和已有标注，不把原工程标签自动升级为审核通过的业务金标准。

## 复现命令

在 `backend` 目录执行：

```powershell
python scripts/rag_regression.py check ../docs/evaluation/rag-upgrade-20261113/dataset.json
python scripts/rag_regression.py correctness --junitxml=../.local-run/rag-upgrade-tests-final.xml
```

`correctness` 使用 SQLite/Mock 测试，显式隔离本机 `.env` 的强制登录和真实运行时开关；不会关闭实际服务的登录要求。

生成新的浏览器隔离环境。每次必须使用不存在数据库的新工作目录，脚本拒绝覆盖已有数据库：

```powershell
python scripts/rag_acceptance_server.py --workspace ../.local-run/rag-upgrade-new --port 18093
```

另开终端，在 `frontend` 目录运行：

```powershell
$env:NEXT_PUBLIC_API_BASE_URL='http://127.0.0.1:18093/api'
node node_modules/next/dist/bin/next dev --hostname 127.0.0.1 --port 18094
node tests/rag-upgrade.browser.acceptance.mjs ../.local-run/rag-upgrade-new/state.json ../.local-run/rag-browser-new
```

随机测试账号只写入被忽略的本地 `state.json`；不在交付文档中存放密码。若端口被占用，使用独立端口并同步设置夹具 CORS、前端 API 地址及 `RAG_ACCEPT_FRONTEND`。

对明确指定的本地 SQLite 库生成只读环境快照与隔离回放：

```powershell
python scripts/rag_regression.py freeze --database-file ../.local-run/rag-upgrade-new/acceptance.db --project-id 1 --dataset ../docs/evaluation/rag-upgrade-20261113/dataset.json --output ../.local-run/rag-environment.json
python scripts/rag_regression.py retrieve --database-file ../.local-run/rag-upgrade-new/acceptance.db --project-id 1 --dataset ../docs/evaluation/rag-upgrade-20261113/dataset.json --output ../.local-run/rag-results.json
python scripts/rag_regression.py evaluate --dataset ../docs/evaluation/rag-upgrade-20261113/dataset.json --manifest ../.local-run/rag-environment.json --results ../.local-run/rag-results.json --output ../.local-run/rag-baseline.json
python scripts/rag_regression.py compare --baseline ../.local-run/rag-baseline.json --candidate ../.local-run/rag-baseline.json
```

最后一条应退出 1：SQLite 关键词回放和未审核标签不能通过发布门禁。`retrieve` 使用源库的内存副本，只写内存中的检索日志，不改源库，也不生成模型答案。`evaluate` 只评分给定结果，不调用模型。

## 标注与质量门禁

2026-11-15 已交付 104 题代理源文件复核及具体业务补证工作包，详见最新报告。下列为登记真正人工批准的格式，不能由模型审核自动填充审核人。业务人员批准后，给出与冻结语料哈希匹配的 `gold`：

```json
{
  "review_status": "approved",
  "gold": {
    "reviewer": "实际审核人",
    "corpus_hash": "冻结语料哈希",
    "relevant_ids": [123],
    "roles": {"定义": [123], "适用条件": [456]},
    "must_refuse": false
  }
}
```

审核后重新生成 `dataset_version` 并保留旧快照。不要直接删除阻断标志来制造通过；只有已完成的审核、原文解析和独立留出条件才能解除对应阻断。

逐题结果需带 `case_id`、`dataset_version`、`corpus_hash`、证据层级、执行状态、实际候选/上下文/引用 ID、延迟及三项安全测量。回答人工复核记录放入 `assessment`：`reviewer`、`supported_citations`、`total_citations`、`complete`。

门禁要求相同题集、语料和测量环境；真实组件或真实模型证据；无未完成/未审核项；安全项均为零；留出集 Hit@5、MRR、引用支撑率不降，且分母非零；p95 增幅不超过 20%。超时、预算耗尽和缺失结果必须进入阻断项。当前命令不会启动有费用的评测；真实模型实验须另行明确模型、调用数、token、时长和成本预算。

## 实验与回退

| 配置 | 默认 | 用途 |
| --- | --- | --- |
| `RAG_QUERY_PLANNING_ENABLED` | false | 开启轻量规划；简单题不增加规划调用 |
| `RAG_QUERY_PLANNER_TIMEOUT_SECONDS` | 10 | 规划超时回退原问题 |
| `RAG_TOKEN_CONTEXT_ENABLED` | false | 用完整知识单元进行 token 预算装配，角色配额放在重排之后 |
| `RAG_RECALL_K` | 50 | 实验候选召回上限，范围 1-50 |
| `RAG_CONTEXT_TOKEN_BUDGET` | 6000 | 证据 token 估算预算，非模型窗口精确计数 |
| `RERANKER_ORDER` | authority | 实验时可设 relevance；不会自动开启重排模型 |
| `RAG_ABSTENTION_SHADOW_THRESHOLD` | null | 只记录 would_abstain，不改变答案或拒答 |
| `CITATION_SUPPORT_CHECK` | off | 沿用有界批次；未运行的语义校验在页面和接口可见 |

实验回退只需关闭规划/token 实验、排序改回 authority、清空影子阈值并恢复原裁判策略。正确性与治理修复不设置旁路。未新增 schema 迁移，正式数据库未迁移；本次只对新增隔离 PostgreSQL 从空库执行现有迁移至 `202611010014`。若需整体回退，使用经过审核的原发布包或独立基线检出，保留当前工作区和证据，不能对混合工作区执行强制重置。

P0 业务基线完成后，正式推进原排序/相关性排序、角色配额和长条款的独立 A/B，再验证多轮与拒答校准。此前仅建议对当前失败做默认关闭的 P1-A 定向实验；已观察的 124 题用于回归，不能重新命名为盲测。发布前需另冻结未观察的独立留出并建立同环境可比较基线，不以失败基线的 0% 非回退单独宣称质量达标。P2 每次只改变分片、Embedding 或 Milvus 索引中的一项，分别建立独立索引版本，记录构建参数、语料哈希、质量、延迟、成本和回退索引。门禁未通过前保持现有默认配置；缓存、HyDE、LTR 和自反馈补检索继续后置。
