# 当前恢复检查点

## 四处前台体验已发布（2026-11-18，当前有效）

用户已单独授权提交 GitHub、推送并部署公网测试环境。本次发布完成；下方“不推送部署”是发布授权前的历史状态，不再代表当前部署状态。开发范围不扩展，P0/P1/P2 不自动续跑。

- GitHub 分支 `dsh/handoff-20261025-round73`；已部署应用提交 `413a77f9543e5fb386a297a9c709094686edceb1`，前序提交 `15826d39c6601c11d302531ba6a038d0c2f7d307`。后续发布记录提交仅更新文档，不改变运行应用身份。
- 公网入口 `http://103.236.92.193:18085`；四个应用容器使用 `413a77f-ux` 镜像且健康；API/前端构建身份一致，schema `202611010014`。worker、beat 探针退出0，readiness 各项健康。
- 本轮复跑后端24 passed / 32 deselected、前端64 passed，Linux生产构建通过。公网浏览器1440/390登录页、键盘焦点、无横向溢出、匿名接口401与版本检查通过；线上登录后业务链路未重测，业务验收沿用下方本地隔离组件报告。外部模型新增调用0；无数据库迁移。
- 升级前后项目33、知识文档43、版本43、智能体任务13、后台任务210、文件86、需求12，数量一致；已有数据卷与基础组件保留。数据库、原始存储与旧配置已备份至服务器 `/home/ybt-release-413a77f/private/`。
- 发布源码位于 `/home/ybt-release-413a77f/source`；`/opt/ybt/source` 保留既有编排及原源码，只调整发布环境变量，不将其 Git HEAD 视为运行版本。回退：`python3 /home/ybt-release-413a77f/publish.py rollback`；旧镜像 `15826d3-r2` 已保留，回退命令未实际演练。
- 服务器根分区剩余约890MB（97%使用），`/home`约4.7GB可用；历史域名接口404，不作为本次入口。报告 `rounds/UX-FOUR-PUBLISH-20261118.md`；脱敏清单 `evidence/UX-FOUR-PUBLISH-20261118.json`。
- 唯一下一步：停止，保留线上服务与回退材料，等待新指令。

## 四处前台体验交付（2026-11-18，当前有效）

**演示主链路已就绪。四项体验改造已落地，当前范围停止；下方 Round65 及 P0/P1/P2 状态仅为历史记录，不构成本轮续跑指令。**

- 基线 `dsh/handoff-20261025-round73@15826d39c6601c11d302531ba6a038d0c2f7d307`；本轮为未提交工作区变更。未提交、推送、部署或修改公网数据；外部模型调用 0。
- 第一批：首屏创建、默认需跟进列表、紧凑行、列表筛选/位置/焦点恢复、按任务项目取证；后台详情展示实际 worker 持久化调用与重试批次。最终复验任务28成功；任务27失败后由job58手动重试至job59成功，旧失败记录保留。桌面1440与窄屏390通过。
- 第二批：需求原文/条目/依据与桌面核对布局、真实草稿状态、依据原文返回、保存后刷新持久化；当前项目资产搜索分组/高亮/最近访问/键盘/竞态处理，弹窗挂载页面根节点且标题、输入和边界通过两种视口断言。真实只读项目24空态及跨项目搜索/需求404、文档断网后刷新恢复通过。
- 验证：后端24 passed / 32 deselected；前端64 passed；生产构建（类型/编译检查）通过；浏览器主链路与边界脚本均退出0。最终生产目录 `.next-ux-four-delivery`，前端18143/API18142。模型为Mock，不能据此声明真实模型质量或P0黄金集通过。
- 文件、命令、现场演示、截图、失败样本与限制：`rounds/UX-FOUR-20261118.md`；机器清单：`evidence/UX-FOUR-20261118.json`；最终浏览器原始结果：`.local-run/rag-long-run/ux-four-20261118/browser-final/`、`browser-boundaries-final/`；失败恢复样本：`browser-delivery/`。
- 当前需求接口没有独立文件解析状态机；已验证文档读取/网络错误恢复，不将其表述为工作簿解析失败验收。改造前截图为Round65历史基线，不是本轮新拍。历史任务没有阶段记录时不补造时间线。
- 回退点为基线提交；无迁移，无须删除数据。保留合成项目19、只读项目23/24、实际阶段记录、原件和本地服务，故障worker已退出，普通worker恢复。唯一下一步：停止，等待用户新指令；不推进P1/P2，不推送部署。

## 停止状态（2026-11-18，Round65）

用户要求完成 Round65 后停止长期开发，**无自动下一动作**；下方“下一唯一动作”均为历史记录。Round65 未完整通过：attempt8 12 项通过后，失败详情键盘顺序出现一次未识别焦点；原因待复核，后续场景未覆盖。详见 `rounds/ROUND-20261118-65.md` 和 `evidence/ROUND-20261118-65.json`。未改产品 UI，未调用外部模型，隔离服务与合成数据保留。

P0-A `blocked_external`；P0-B/C、UX及远程部署验收 `in_progress`；P1/P2 `pending`。代理按原文审核的授权仍有效，独立来源和留出集尚缺。预算历史快照为 531/800 请求、3,608,925/8,000,000 tokens、reserved 0、unknown 3，本轮未实时复核。

## 当前有效状态（2026-11-18，round64独立API生产页面治理验收）

- Round63 HTTP 409契约现已在独立Uvicorn API及身份匹配Next生产前端上通过浏览器验收：登录、真实隔离PostgreSQL、生成/judge窗口撤回与禁用409、无答案/引用、恢复后200、普通校验错误400，共47/47；桌面及390px冲突页面无横向溢出。
- 当前代码身份`206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.3c31ce3f25b5`，源码SHA `3c31ce3f25b53b66ed59df6f6b6a553b104fb6d403a658f1ef9937d44e1da964`，schema `202611010014`。API `18140` PID1548就绪；生产构建`.next-round64-conflict-production`。本轮API及合成项目18/版本21/单元5978留作复核，不停止Round53旧服务。
- P0-A继续`blocked_external`；P0-B/C及UX保持`in_progress`；P1/P2和公网切流锁定。Mock生成/规划/judge，fixture非gold/非holdout，无真实模型业务或公网结论。
- 本轮provider增量0/0；既有预算账本余额没有重新核验，也未修改。前端构建临时类型路径已移除。失败attempt与截图保留；无远端写入。
- 报告/证据：`rounds/ROUND-20261118-64.md`、`evidence/ROUND-20261118-64.json`、`.local-run/rag-long-run/round-20261118-64/browser-attempt2/results.json`。
- 下一唯一动作：完成任务台未覆盖的运行中/失败/待处理详情状态、完整键盘顺序及错误恢复验收；桌面/390px检查继续使用身份匹配生产构建及隔离API，模型调用0。随后按证据处理P0未闭合项；不推进P1/P2默认、不切公网。

## 当前有效状态（2026-11-18，round63 HTTP治理冲突）

- 总目标18项不变。本轮完成问答资料变化409契约及固定提示；P0-A仍blocked_external，P0-B/C与UX仍in_progress，P1/P2及公网切流保持锁定。
- 产品改动仅`citation_validator.py`、`knowledge_rag.py`及`knowledge-contract.mjs`；源码身份`3c31ce3f25b53b66ed59df6f6b6a553b104fb6d403a658f1ef9937d44e1da964`，HEAD仍206d431。全部既有未提交差异保留。
- 后端130 passed/889.71秒、前端7 passed、隔离PostgreSQL/ASGI 11/11、合成API开发浏览器4/4、py_compile和diff检查通过。具体命令、文件hash、证据等级和限制见`rounds/ROUND-20261118-63.md`及`evidence/ROUND-20261118-63.json`。
- 组件attempt5新建项目17/版本20/单元5977，隔离PostgreSQL keyword_only检索，规划/generator/judge受控；生成与judge等待窗口独立会话提交撤回/禁用均409，无答案；恢复后200，普通ValueError400。所有attempt及其合成fixture保留。
- 浏览器最终attempt3退出0；当前Next开发页面、拦截式合成API，390px截图已抽查。临时18139及浏览器已结束，自动加入的Round63 tsconfig类型目录已移除。该证据不属于生产构建或真实模型。
- 既有18135/18137等API、worker、组件、旧数据/索引/原件和公网保留；旧服务未加载本轮代码，不复用其身份宣称409部署通过。
- 本轮provider增量0/0；可读预算仍531/800请求、3,608,925/8,000,000 tokens，reserved0、unknown3，未进行新付费生成或裁判。
- 最后完整round为63；所有本轮测试进程均已终结。下一唯一动作：在新独立API与身份匹配的生产构建上验证409错误恢复及普通200问答，保留旧服务/分库/索引；受控Mock，外部模型0调用。随后继续任务台未覆盖状态和完整键盘验收。

下方为历史检查点。

## 当前有效状态（2026-11-18，round62真实隔离API只读UX验收）

- 固定18项目标保留，P0-A仍blocked_external，P0-B/C与UX仍in_progress；P1/P2默认和公网切流锁定。
- Round62独立生产构建`.next-round62-ux-real`退出0，54路由；API18135/构建commit、build time、schema匹配。临时前端18136和浏览器已在脚本结束关闭；既有API/worker/组件保留。
- 浏览器12/12：真实隔离登录、任务列表及任务2详情、GET失败后重新加载、浏览器注入只读权限提示、桌面/390px、原文抽屉Escape关闭及焦点归还。截图已抽查。任务仅completed；完整Tab顺序、运行/失败/待处理尚未验。
- 未创建任务或执行问答，业务写请求0；模型增量0/0。预算最后记录531/800请求、3,608,925/8,000,000 tokens，reserved0、unknown3，未将旧账本快照描述成新provider测量。
- 仅新增只读浏览器脚本和交付文档；构建器新增tsconfig include已移除，原用户差异保留。所有成功/失败attempt、数据、索引、旧服务与构建保留，公网未写。
- 报告`rounds/ROUND-20261118-62.md`、摘要`evidence/ROUND-20261118-62.json`；成功结果`.local-run/rag-long-run/round-20261118-62/browser-attempt7/results.json`。
- 下一唯一动作：审查Round60请求期间治理变化在知识问答HTTP接口的异常映射，补受控Mock的接口级验证；先读接口和异常契约，再决定是否需要修复。不调用外部模型、不部署公网、不改旧冻结版本或共享索引。

## 当前有效状态（2026-11-18，round61任务台状态徽标改进）

- 固定18项目标不变。`G-P0-A=blocked_external`；`G-P0-B`、`G-P0-C`与UX目标仍`in_progress`；P1/P2及公网切流继续锁定。
- Round61复核任务台旧交互及实际桌面截图，补齐状态徽标图标并移除页头流程说明文案；55项视图回归、TypeScript、最终源码独立生产构建和合成 API 浏览器3/3通过。截图含构建身份未知提示，不能作为真实API身份一致的最终视觉验收。报告/证据：`rounds/ROUND-20261118-61.md`、`evidence/ROUND-20261118-61.json`；最终浏览器结果`.local-run/rag-long-run/round-20261118-61/browser-attempt6/`。
- 本轮修改限任务台共享状态徽标、页头文案和对应测试；模型额度增量0/0，真实组件、数据、索引、既有服务及公网未改。
- Round60当前源码身份复核通过；真实隔离PG/Milvus与本地Embedding、受控Mock generator/judge下4/4通过。正常资料未变化时引用保持；在generator或judge await期间撤回后，服务最终校验均拒绝返回旧答案。该轮直接调用service，没有验HTTP错误映射；无真实provider请求/token增量。
- 本轮新隔离项目12，版本14/15，目标引用单元5971；Round60报告/证据`rounds/ROUND-20261118-60.md`、`evidence/ROUND-20261118-60.json`；最终attempt `.local-run/rag-long-run/round-20261118-60-attempt3/results.json`。attempt1/2分别保留。
- 累计预算最后记录仍为531/800请求、3,608,925/8,000,000 tokens，reserved 0、unknown 3；本轮模型预算增量0。
- 本轮未修改业务逻辑；Round53/55/57/59服务、数据库、索引、Round57工作簿、生产构建及所有失败attempt继续保留，公网未切换。
- 下一唯一动作：继续任务台 UX 收口，在发布身份一致且连接真实隔离 API 的构建上验任务详情各状态、键盘顺序、错误恢复和证据抽屉；随后回到未关闭 P0 技术项。继续保护所有隔离服务、数据、索引、构建和失败 attempt，不调用真实模型、不部署公网。

## Round61 回顾
- `ToneBadge` 现同时用文本、颜色、图标表达状态，活动状态使用旋转图标；未知状态中性回退不变。
- 浏览器只使用合成 API 状态，检查处理中/已完成/处理失败标签各含一个语义图标、页头说明文案不再显示，以及1440px/390px无横向溢出。真实模型请求/token为0/0。
- 最终 build 与浏览器使用当前源码；身份匹配真实 API 的详情/错误/键盘验收仍待补。
- Browser screenshot 中出现发布身份不匹配提示，原因是独立构建未设置 `NEXT_PUBLIC_APP_COMMIT` / `NEXT_PUBLIC_BUILD_TIME`；生产视觉验收需身份匹配后重做。

## Round59 回顾
- Round59 API真实隔离组件9/9、浏览器真实隔离API 4/4通过。V2激活后默认检索仅返回V2；授权历史可命中旧版本；冻结需求revision在V2激活后仍仅引用V1；不匹配pin fail-closed。隔离索引指针10→11→10回退，未删除或修改Milvus向量。
- 浏览器真实登录、冻结V1问答、V1原文预览/下载SHA、390x844无横向溢出通过；请求用项目9、版本8，HTTP 200。LLM为Mock，资料为合成资料，不属于gold/holdout。provider请求/token增量0/0；累计账本最后记录531/800请求、3,608,925/8,000,000 tokens、reserved 0、unknown 3。
- API应用身份`206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.87d4cd5f1390`，source hash `87d4cd5f1390b0cd4079425435d8e0bcd0aef0071372d5ffe55f5b23e74af9f7`；schema head `202611010014`。未修改业务代码、Round57工作簿/active索引或公网环境。
- Round59报告/机器证据：`rounds/ROUND-20261117-59.md`、`evidence/ROUND-20261117-59.json`。最终浏览器结果及截图在`.local-run/rag-long-run/round-20261117-59-browser-attempt5/`；API结果在`.local-run/rag-long-run/round-20261117-59-attempt2/`。Browser attempt1–4失败样本均保留。
- 最近活动失败均为验收脚本问题：attempt1登录超时；attempt2响应监听等待30秒后超时但后端日志记录问答200；attempt3启动Next时未传`NEXT_DIST_DIR`；attempt4引用按钮文案假设错误。修正后attempt5完成全部断言，未发现产品行为缺陷。
- 下一唯一动作：审计问答在检索与装配后、生成或引用裁判进行期间资料被撤回/禁用时的时序；先检查现有事务边界和可控模型/裁判注入点，再以隔离组件受控阻塞测试验证，不调用真实provider。若未复现受支持用法可达的缺陷则只补证据，不改业务逻辑。

## 当前有效状态（2026-11-17，round58隔离治理与浏览器验收通过）

- 18项目标锁定不变。`G-P0-A=blocked_external`；`G-P0-B`、`G-P0-C`及UX目标仍`in_progress`；P1/P2和公网切流继续锁定。
- Round58复用Round53真实隔离PG/Redis/Celery/Milvus和本地BGE，在新合成项目7/文档6/版本6/任务5上完成API 9/9、浏览器5/5验收。活动版本先可检索并由任务引用；撤回后检索排除，授权原文保留且SHA/页面警告正确；跨项目preview/content双404；禁用单元在不重建Milvus索引时不再命中；8个检索请求均与撤回事务提交点重叠，提交后响应的撤回版本引用为0。
- 浏览器真实登录和撤回证据页面通过；预览/下载均用任务所属项目7、版本6；390x844无横向溢出。LLM为Mock；真实provider请求/token增量0/0。共享预算531/800请求、3,608,925/8,000,000 tokens，reserved 0、unknown 3。
- API身份仍为`206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.87d4cd5f1390`，source hash `87d4cd5f1390b0cd4079425435d8e0bcd0aef0071372d5ffe55f5b23e74af9f7`；未修改生产业务代码、Round57工作簿或索引，也未部署或写公网。
- 报告/脱敏证据：`rounds/ROUND-20261117-58.md`、`evidence/ROUND-20261117-58.json`；attempt原始结果在`.local-run/rag-long-run/round-20261117-58*`。API attempt3的ORM夹具错误、浏览器attempt1/2的验收脚本问题均保留，不覆盖。
- 并发范围仅为检索请求跨越撤回事务提交点，不代表模型生成或judge期间撤回已验证。该合成技术子项关闭，不代表业务黄金集、真实模型、P0整体或UX总目标关闭。
- 下一步Round59：用新的合成资料审计同一文档新版本激活、旧版本默认检索排除、显式冻结版本检索和索引切换/回退；保留Round53/55/57/58所有数据与服务，不复用Round57工作簿做问答、不调用真实模型。

## 当前有效状态（2026-11-17，round57 精确工作簿新版本重入库与索引通过）

- 总目标仍是`GOAL-LOCK.md`固定的18项；本轮只关闭P0-B中的精确工作簿新版本解析/入库/隔离索引技术子项。`G-P0-B`、`G-P0-C`、UX仍`in_progress`，`G-P0-A=blocked_external`；P1/P2和公网切流继续锁定。
- 运行身份：Round55修后源码`206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.87d4cd5f1390`；API `18137`；Round53隔离PG `15442`、Redis `16392`、Milvus `19533`、本地BGE `18131`；本轮专属Redis broker/result DB `6/7`。LLM=Mock，Embedding=`BAAI/bge-small-zh-v1.5` 512维。
- 精确原件SHA `51228a75d5f22ed9a058c9a7c29834989ab56da95e35435164084c537b9ec311`，大小1,666,351 bytes；导入Round53隔离新项目3、文档2、版本2。版本状态active。历史冻结数据库未连接写入，原件仅作已观察回归数据。
- 解析报告`xlsx-knowledge-config-v3`：9/9工作表识别/解析，无跳过、无blocking；5,958个有效单元，103,447个原件非空单元完整保留，解析与存储定位多重集一致，缺失/额外定位均0，locator覆盖5,958/5,958。
- 独立Milvus index version 3为active，job 7完成；5,958/5,958 chunks与active embedding records，0失败批次。Deterministic hybrid top-5返回5项并命中所测单元；这是检索smoke，不是gold指标或答案支撑验收。
- Attempt记录：首次索引job6在30/94批发生有界本地Embedding网络错误；保留失败。独立worker/API使用Redis DB6/7和180秒Embedding timeout后job7完成。首次接续轮询token到期时同一job仍running，没有重复提交；使用自动续登录接管并完成。无生产代码修改。
- 预算无变化：531/800 provider requests、3,608,925/8,000,000 tokens，reserved 0/0，unknown usage 3；本轮外部provider请求/token为0/0。
- 报告/证据：`rounds/ROUND-20261117-57.md`、`evidence/ROUND-20261117-57.json`；完整脱敏细节及attempt见`.local-run/rag-long-run/round-20261117-57/`。
- 下一动作：继续P0-B/C，不重复入库或索引job7。优先对新隔离资料验证撤回/禁用、版本变化和跨项目原文访问在真实组件/页面中的拒绝与降级状态；P0-A来源缺口未关闭前不做真实生成/judge或新holdout。保留Round53/55/57全部服务、数据库、索引和attempt，不清理旧状态。

## 当前有效状态（2026-11-17，round56 P0确定性矩阵复核）

- Round55修后源码身份`206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.87d4cd5f1390`；source hash `87d4cd5f1390b0cd4079425435d8e0bcd0aef0071372d5ffe55f5b23e74af9f7`。Round55修后浏览器API/worker仍在隔离端口18135及Redis DB4/5运行；Round53资源和数据保持不变。
- Round56在该工作树运行码值/字段边界、确定性缺口与judge、跨引证隔离、版本钉扎、请求期间撤回/禁用、非有限重排分数、authority边界及工作簿对账保护回归：64 passed、0 failed。未发现新生产代码反例，因此未改业务代码。
- 单测使用隔离fixture/Mock，不能替代原工作簿重入库/索引、真实模型或独立业务留出。原件问题继续按round44/52/56证据处理；未用近似副本替代。
- Round55已通过修后真实组件问答和浏览器原文SHA链路；预算仍531/800请求、3,608,925/8,000,000 tokens，reserved 0、unknown 3。本轮请求/token增量0/0。
- `G-P0-A=blocked_external`；`G-P0-B`、`G-P0-C`与UX整体目标`in_progress`；P1/P2和公网切流仍锁定。Round56报告与机器证据为`rounds/ROUND-20261117-56.md`及`evidence/ROUND-20261117-56.json`。
- 下一步核验原始工作簿取得状态；若无精确原件，继续剩余P0治理异常浏览器链路和不依赖该输入的反例，不能以64项通过关闭P0。

## 当前有效状态（2026-11-17，round55修后知识问答真实组件与浏览器链路通过）

- 总目标仍为`GOAL-LOCK.md`所列18项目标；本轮关闭Round54规划缺口的修后真实组件/浏览器复验子项，不改变P0和P1/P2门禁。
- 分支/HEAD：`dsh/handoff-20261025-round73@206d4313a5805613f5bf7e0b5db41390ab92d31f`；应用身份`+worktree.87d4cd5f1390`，source hash `87d4cd5f1390b0cd4079425435d8e0bcd0aef0071372d5ffe55f5b23e74af9f7`，源文件777个。
- Round55 browser API `18135`、worker使用隔离Redis DB `4/5`，复用Round53 PG `15442`、Redis `16392`、Milvus `19533`、本地Embedding `18131`；旧Round53 API/worker没有重启。Next production build位于`.next-round55-production`，浏览器临时server验收后关闭。
- 新建任务2完成；必需`answer_knowledge_question`步骤及工具调用均completed，步骤证据数2。答案artifact是`needs_confirmation`、1条引用；这是Mock语义路径的保守状态，不等于真实模型/引用裁判通过。
- 浏览器登录、CORS、当前API身份、任务详情、打开文档1版本1原文、切换其他项目保留上下文、桌面/390px无溢出通过。原文预览/内容均HTTP 200，字节SHA `863f2b4f...a2862938`与合成索引源完全一致。
- 共享预算无增量：531/800请求、3,608,925/8,000,000 tokens，reserved 0、unknown 3。LLM=Mock；无真实provider请求。
- 定向运行时启动器测试8 passed；浏览器验收2项通过；生产构建54 routes通过并有既有Hook依赖warning。生产源码身份以当前运行报告为准。
- P0-A仍`blocked_external`；P0-B/C及UX总目标仍`in_progress`；P1/P2和公网切流锁定。Round55机器证据为`evidence/ROUND-20261117-55.json`，报告为`rounds/ROUND-20261117-55.md`，浏览器原始结果及截图位于`.local-run/rag-long-run/round-20261117-55/browser-attempt4/`。
- 下一步只推进不依赖新holdout的P0技术矩阵；优先在原工作簿可取得后完成新版本解析/治理/独立索引核验，未取得则继续其他权限、版本、状态、引用反例。不得重复调用任务生成/真实模型，不得切公网或开始P1/P2。

## 当前有效状态（2026-11-17，round54知识问答规划缺口已修复）

- 总目标仍是`GOAL-LOCK.md`的18项目标；活动目标G-P0-B、G-P0-C。Round54 唯一代码目标已完成：阻止知识问答规划省略回答工具。
- 分支/HEAD：`dsh/handoff-20261025-round73@206d4313a5805613f5bf7e0b5db41390ab92d31f`；修后应用源身份为`+worktree.f3050e58fb33`，SHA-256 `f3050e58fb33c3c8bc512f59fe7cb25a5c25b4018418eef9fb5c795938092734`。
- 发现：round53只读任务详情显示`completed`、仅一步`s1`、无输出摘要/回答/引用。根因是知识问答规划校验没有要求必需`answer_knowledge_question`。
- 修改：`backend/app/services/agent/planner.py`要求知识问答计划包含必需回答工具；缺失/仅可选触发校验拒绝，规划器一次有界修复后仍无效则保留确定性问答计划。新增两项测试模块覆盖。
- 验证：修前反例2 failed/9 passed；修后`test_agent_optional_dependency_contract.py`、`test_agent_knowledge_question.py`、`test_agent_planner_validation.py`共40 passed。`py_compile`、`git diff --check`通过。
- Round53真实组件仍保留运行，但API身份`worktree.c7df8b72bd80`是修前代码；禁止把该进程结果说成修后验证，也不读取私有凭据、不重启/停止其父进程。下一轮需以修后身份启动单独API并做真实组件与浏览器回归。
- 模型预算无变化：531/800 requests、3,608,925/8,000,000 tokens，reserved 0，unknown 3；Round54外部模型请求/token `0/0`。P0-A继续`blocked_external`，P0-B/C及UX整体`in_progress`；P1/P2与公网切流不放行。
- Round53 attempt6/7保留为修前发现；Round54报告/证据为`rounds/ROUND-20261117-54.md`与`evidence/ROUND-20261117-54.json`。
- 下一步：为修后源码创建独立API运行身份，复用Round53 PG/Redis/Milvus隔离数据，验证Mock知识问答规划两次拒绝后回退到确定性问答链，并做新身份浏览器验收；不得触碰原公网服务。

## 当前有效状态（2026-11-17，round53隔离组件与降级页面验收完成）

- 总目标仍为`GOAL-LOCK.md`所列18项；活动目标为G-P0-B、G-P0-C及任务台UX验收。本轮唯一目标已完成：在独立当前源码运行时核验合成索引、问答和页面降级态。
- 代码身份：`dsh/handoff-20261025-round73@206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.c7df8b72bd80`。工作树此前已有大量未提交和未跟踪改动，均保留。
- round53隔离运行时：PG `15442`、Redis `16392`、API `18130`、formal API `18132`、本地Embedding `18131`、浏览器API `18134`、前端 `18133`；Milvus `19533` 使用独立容器/卷/namespace。API、worker、Embedding、前端保持运行，供下一轮复用。
- 真实组件结果：专属PG迁移、Redis/Celery、Milvus及本地BGE可用；合成资料1/1向量索引、样本命中1；直接问答为`needs_confirmation`/low，1条引用，版本原文SHA匹配。此为技术通路，不代表业务质量。
- 浏览器attempt6通过当前API身份/CORS、登录、任务详情、跨项目切换保持上下文、无结论提示、0证据及桌面/390px无溢出。其Agent任务状态`completed`但没有结论/引用，界面明确显示无结论；这表示流程终结，不据此单独改通用状态机。没有发生原文请求，所以不计原文抽屉通过。
- 模型：LLM为Mock；本轮真实provider请求/token 0/0。共享预算仍531/800请求、3,608,925/8,000,000 tokens，reserved 0、unknown 3。禁止在新授权来源和留出冻结条件满足前调用生成/judge。
- P0-A仍`blocked_external`；P0-B/C及UX整体仍`in_progress`；P1/P2和公网切换不放行。原始工作簿精确SHA未找到，不以其他副本替代。
- 报告/证据：`rounds/ROUND-20261117-53.md`、`evidence/ROUND-20261117-53.json`；页面原始结果和截图位于`.local-run/rag-long-run/round-20261117-53/browser-attempt6/`。
- 下一动作：复用round53真实组件，先推进不依赖外部gold/付费模型的P0-B/C缺口；优先核验工作簿原件取得路径及隔离新版本重入库状态、页面带引用原文和治理异常链路。新来源不到位时记录阻塞，不调用模型、不宣称P0完成。

## 当前有效状态（2026-11-17，round53 隔离运行时启动中）

- 活动目标：G-P0-B、G-P0-C；本轮唯一目标是在不碰既有资源的前提下建立当前源码的独立真实组件验收环境。
- 代码身份：`dsh/handoff-20261025-round73@206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.2327c37db339`；已修改文件清单和源码哈希见 `runtime-20261117-53/runtime-plan.json`。
- round53 专属 Milvus/etcd/MinIO 健康，Milvus容器ID `0e1dca3c60853a567c0e8247151f057a2c6f4d1ded20fa38d7cdac697abf4f03`，集合为空；共享YBT Milvus身份及启动时间与既有证据一致。
- round53 PG/Redis容器及命名卷已创建并通过Docker healthcheck；端口分别为PG `15442`、Redis `16392`、API `18130`，formal API `18132`、embedding `18131`；API/worker尚未启动，数据库迁移尚未执行。
- 新凭据仅写入忽略目录 `.local-run/rag-long-run/private-rag-p0-r53/`；不得读取或记录秘密值。runtime plan指定LLM/Embedding为Mock，外部provider请求为0。
- round46/round53启动器与独立Milvus守卫回归最终 `9 passed`，JUnit为 `.local-run/rag-long-run/round-20261117-53/runtime-guard-attempt2.junit.xml`。attempt1的1个失败归因为测试夹具未同步临时私有目录；attempt2仅修正夹具并通过，未放宽生产“禁止覆盖已有私有状态”守卫。
- 原工作簿精确SHA `51228a75d5f22ed9a058c9a7c29834989ab56da95e35435164084c537b9ec311` 在此前指定目录检索未找到；本轮不替换副本，不导入不同字节。P0-A仍`blocked_external`，不冻结holdout或调用模型。
- 本轮provider请求/token增量0/0；全局快照仍为531/800请求、3,608,925/8,000,000 tokens，reserved 0、unknown 3。尚未迁移、建collection、导入资料、写公网或切换路由。
- 下一步执行round53隔离API/worker启动与迁移，随后只使用合成资料验证当前代码的真实PG/Redis/Celery/Milvus链路；不把合成数据或旧题当业务留出。回退方式是停止本轮自有API/worker进程并保留容器、卷和全部证据；不清理数据、不触碰其他运行时。

## 当前有效状态（2026-11-17，round52 P0-A 来源盘点）

- 已完成本机可取得来源、谱系、历史使用路径和样本覆盖盘点；逐项结论见`rounds/ROUND-20261117-52.md`。
- 找到84份集市ETL SQL及配套DDL/报送脚本/参考工作簿；其中56份ETL SQL的内容SHA在本地平台项目9/11/12/14文件存储中命中。此为历史曝光证据，不把文件存储命中夸大为每份都发生过检索。其余候选也在同一评估/演示准备包中，无法证明未观测。
- 原104工作簿题、20 SQL题、12多源题均已观察，永久只作回归。用户授权的代理逐题审核已按原文完成到记录范围，不需要用户逐题操作；该授权不能证明来源所有者授权或历史未曝光。
- P0-A来源审计工作包完成，但新独立留出仍缺来源包级授权用途、未使用历史说明和足够独立文档家族，因此`G-P0-A=blocked_external`。本轮未冻结新holdout、未调用模型、未写DB/索引/远端。
- 恢复条件和最小来源包字段见round52；收到后仍由代理逐题复核。P0-B/C继续本地技术整改与真实链路验收；P1/P2继续锁定。

## 当前有效状态（2026-11-17，round51 外部Embedding共享预算）

- 修复OpenAI-compatible外部Embedding HTTP路径此前绕过共享provider预算的问题；非本地provider每个batch/重试均预留并结算，缺usage保守计费；budget-required缺账本时HTTP前失败。local_* / Mock不计入外部额度。
- 对应Embedding/provider/gateway/runtime定向回归67 passed；py_compile、diff check通过。attempt1的3个fixture失败及attempt2的66项中间通过均保留，attempt3为最终结果。
- 所有外部provider测试都使用MockTransport；真实provider请求0。总账仍531/800 requests、3,608,925/8,000,000 tokens，reserved 0、unknown 3。
- round46 Milvus只读盘点发现现存formal collection 1个、实体1条；未修改。round46 API身份为旧worktree源码，不能作为当前代码验证；round45/46服务均保留运行。
- 详见`rounds/ROUND-20261117-51.md`、`evidence/ROUND-20261117-51.json`及`.local-run/rag-long-run/round-20261117-51-budget-embedding-attempt*.junit.xml`。
- 仅关闭外部Embedding预算绕过代码路径子项；P0-B仍需新工作簿版本及完全独立索引链路。P0-A、P0-C、UX整体和远端当前版本验收仍开放，P1/P2锁定。

## 当前有效状态（2026-11-17，round50 当前源码治理页面合成浏览器验收）

- 当前源码独立 production build 成功，使用 `.next-round50-production`，lint/type检查及54路由完成；有既存React Hook依赖warnings。
- round50 attempt5 合成API全拦截浏览器5项通过：只读任务入口保留但提交禁用、跨项目任务安全404、撤回提示、原文不可用时解析证据保留、390px无横向溢出及Escape关闭对话框。provider/外部请求/数据变更均为0。
- attempt1–4失败结果均保留；attempt4暴露只读UI契约误设、404文案标点误差和旧round47构建身份。attempt5使用当前源码构建，验收后已停止18688服务。
- 此为当前源码的合成生产前端交互证据，不是真实API、真实账号/资料、模型、业务黄金集或公网验收；不提升目标状态。`GOALS.json`应保持consistent=true、complete=false。
- 详见`rounds/ROUND-20261117-50.md`、`evidence/ROUND-20261117-50.json`及`.local-run/rag-long-run/round-20261117-50/browser-attempt5/`。
- 下一步继续P0-B工作簿新版本重入库/独立索引，P0-A来源授权与新鲜度仍阻塞；先审计全部模型调用入口共享预算覆盖。P1/P2继续锁定。

## 当前有效状态（2026-11-17，round49 API治理反例）

- round49在Agent接口测试增加跨项目成员不能列出/读取另一项目任务的断言；知识原文存储失败返回脱敏404的用例通过。既有撤回版本的授权历史提示测试仍通过。
- 定向回归8 passed；首次1 failed/7 passed因测试预期403而权限服务实际按契约返回404，修正后通过，失败保留。该结果为隔离API/service测试，不是浏览器/真实组件验收。
- 未改应用逻辑、数据库、索引、服务、远端或公网；provider请求0，未读旧隔离凭据。
- 详见`rounds/ROUND-20261117-49.md`和`evidence/ROUND-20261117-49.json`。跨项目真实登录页面和撤回/不可用原文页面尚未验收。
- P0-A/B/C、UX及远端目标仍开放，P1/P2未放行；round50先安全建立页面治理fixture，再继续新版本重解析/隔离索引验证，不使用旧凭据或改冻结版本。

## 当前有效状态（2026-11-17，round48 Mock planner 与评测预算守卫）

- round48将Mock限制为识别`[AGENT_PLANNER_V1]`时返回包含`objective/scenario_key/subject/steps`的schema-valid计划；普通Mock响应行为保持不变。round46降级被归类为测试Double结构契约不匹配，不是已证实的生产执行越权。
- 新增`RAG_MODEL_BUDGET_REQUIRED=true`：预算路径同时缺失时，在HTTP发送前fail-closed；默认仍为opt-in，不改变普通生产流量。评测runtime必须先提供共享账本才能继续启动，API/worker和candidate37均显式启用。
- 定向测试最终53 passed；两次失败attempt均保留：先暴露Mock缺字段，后暴露预算检查顺序/测试桩签名不匹配。py_compile和diff check通过。
- 本轮只读SQLite核对与`BUDGET.json`一致：531/800请求、3,608,925/8,000,000 tokens、reserved 0、unknown 3。外部模型请求0，未改任何服务、数据、索引或公网路由。
- 活跃历史进程仍有监听；Windows进程清单不含继承的环境变量。未读取旧隔离凭据文件，因此这些历史服务的实际budget-required/provider环境保持未核实；不能据此认定所有进程已受守卫。
- 详见`rounds/ROUND-20261117-48.md`和`evidence/ROUND-20261117-48.json`。P0-A/B/C整体、UX、远端部署/验收仍开放；P1/P2未放行。
- 下一步：维持新鲜授权来源缺口为阻断；补跨项目拒绝及撤回/不可用原文页面治理fixture，继续核验候选/评测路径强制共享账本；不得重跑已通过浏览器写操作、调用真实模型或切公网。

## 当前有效状态（2026-11-17，round46 当前代码隔离组件通路）

- round46独立PG/Redis容器/卷已启动，API `18125`、PG `15441`、Redis `16391`，均为专属loopback端口。PostgreSQL迁移head `202611010014`。
- 初始runtime API `/version` 身份 `206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.d4a246c19116`；后续 formal API `18126` 使用BGE和独立Redis DB2/3，identity为 `206d4313a5805613f5bf7e0b5db41390ab92d31f+worktree.a17bdedabe3f`。初始 `/health/ready=ready`；formal索引运行后真实组件ready。
- round46后续报告 `.local-run/rag-long-run/round-20261117-46/runtime/formal-index-attempt1.json` 证明仅合成资料项目1/文档1/版本1建立1/1向量索引；检索返回引用，Agent任务completed；回答needs_confirmation/low；版本原文SHA与合成源SHA一致。Embedding为本地BGE，LLM为Mock，provider请求0。Agent worker中Mock planner schema验证失败后进入降级路径，该缺陷仍须审查；这是合成技术链路，不是业务gold或holdout。
- round47当前前端隔离生产构建连接API同身份实例已验收：错误登录401后正确登录200、任务列表及既有详情、创建表单校验、证据抽屉真实下载原文哈希、桌面/390px、键盘及Escape焦点闭环通过。结果见`rounds/ROUND-20261117-47.md`和`evidence/ROUND-20261117-47.json`；无新任务、外部模型调用或资源修改。
- round47为连接前端而启动临时同源码API `18129`，唯一配置差异为CORS来源只允许隔离前端 `18128`，其余仍用round46 formal隔离PG/Redis/Celery/Milvus/BGE；前端独立dist `.next-round47-browser`。验收结束已停止临时API/前端，保留round46 API `18125/18126`、BGE `18127`及其隔离组件。
- round46脚本守卫5 passed；最终脱敏报告`.local-run/rag-long-run/round-20261117-46/runtime/runtime-attempt1.json`。首次WSL子进程访问、短readiness探测和启动器NameError均保留；没有重启服务，使用只读`finalize`完成实际运行核验。
- 新运行凭据仅位于忽略目录`.local-run/rag-long-run/private-round46/`；禁止读取旧隔离凭据或向共享Milvus写入。
- 前端build有既存Hook依赖ESLint warnings，编译、TS检查和54路由构建均成功；首个服务器包装路径错误及前两次原文SHA取证脚本错误均保留，修正下载Blob校验后attempt3通过。
- 下一步：P0-A来源审查/外部授权与独立留出新鲜度证据、shared SQLite预算及candidate端到端守卫审计；继续审查round46 Mock planner返回schema不兼容的失败降级。真实模型调用依旧等待新留出冻结与共享预算守卫审查通过。远程公网部署尚未切换。
- P0-A/B/C整体、UX、远程部署/验收仍开放；P1/P2不放行。详见`rounds/ROUND-20261117-46.md`与`rounds/ROUND-20261117-47.md`。

## 当前有效状态（2026-11-17，round45 WSL 独立 Milvus）

- 新增 WSL 隔离 Milvus/etcd/MinIO：网络 `rag-p0-r45-net`、三个独立命名卷、loopback 端口 `19531`。Windows PyMilvus 实连成功，Milvus collection 列表为空；共享 `ybt-dev-milvus-1` 的容器 ID/启动时间与创建前一致。
- 本轮工具回归3 passed，JUnit `.local-run/rag-long-run/round-20261117-45/milvus-runtime-tests-attempt2.junit.xml`；机器报告 `.local-run/rag-long-run/round-20261117-45/isolated-milvus-runtime-attempt2.json`。首次宿主健康端点探针失败保留并已登记。
- 本轮没有启动 API、worker、PostgreSQL 或前端，没有导入/索引资料，也没有模型请求；provider请求/token、collection创建、既有资源修改均为0。该运行环境不是 P0-C 通过证据。
- 凭据安全：一次旧隔离环境 DB 连接凭据曾意外输出。此后不得读取、复制、使用或轮换该凭据，也不得读取其历史来源文件；本轮未使用它。只登记不含值的事件 `SEC-ISOLATED-CREDENTIAL-OUTPUT-002`。
- 下一步：在不接触旧凭据和共享 Milvus 的前提下，设计当前代码的全新 API 运行身份；启动 PG/Redis/API/worker 前核对资源唯一性、容量与健康检查，使用新凭据，确保任何报告不输出 secrets。模型 route 继续关闭。
- round44 的工作簿重解析差异仍待隔离新版本与独立 collection 技术复核，不能原位改写冻结版本；已观察题/工作簿不得当作留出。P0-A 独立新来源仍缺失。
- 本轮交付见 `rounds/ROUND-20261117-45.md`；P0-A/B/C 与 UX/远端未关闭，P1/P2未放行。

## 当前有效状态（2026-11-17，round44 原始工作簿与冻结语料对账）

- 找到4份与上传哈希完全一致的本地隔离原件副本；使用项目1/文档1/版本1，并以只读事务核对隔离PostgreSQL。
- 新增只读可续跑对账器`backend/scripts/rag_workbook_reconciliation.py`。当前v3解析9/9 sheet、5958单元；当前解析结果保留所有可见非空源单元值。
- 历史冻结语料仍是v1：5922单元、旧报告7/9 sheet、parse_blocked=true。相对当前解析，37行“穿透层问答”缺失、1个旧定位孤立；另有33个转1104/EAST重复反馈列值未在旧文本中。源单元总计708个未在旧入库文本中，主要为整张未入库sheet。
- 不在原位修改冻结版本/索引。后续应使用新文档版本重新导入、审核、激活并建立隔离索引，核对新版本单位数、逐sheet定位、权限/版本与回退；P0-A独立新来源/留出仍未解决。
- 对账脚本测试2 passed，`py_compile`通过；DB/index/provider/remote写入均0。报告仅含哈希、坐标、列头及计数，无工作簿单元格值；git HEAD及相关文件哈希已记录。详情`rounds/ROUND-20261117-44.md`、`evidence/ROUND-20261117-44.json`。
- 总目标检查保持consistent=true、complete=false；P0-A/B/C、UX及远程目标仍开放，P1/P2未放行。模型预算531/800请求、3,608,925/8,000,000 tokens、预留0；本轮模型调用0。

## 当前有效状态（2026-11-17，round43 工作簿语义重复列静默漏解析修复）

- 本轮P0解析审查发现别名不同但语义相同的重复列（如`问题`/`具体问题描述`、`回复`/`答疑结果`）可能只保留排序优先的一个值。修前反例失败，丢失另外两个业务值，证据`.local-run/rag-long-run/round-20261117-43-red-junit.xml`。
- 修复后，同一语义组值冲突时不猜结构化值，逐列保留原文、列号和父分组，并生成`duplicate_semantic_column`行级诊断；值相同或仅一个非空值时仍能映射结构化字段。解析配置版本升级至`xlsx-knowledge-config-v3`。
- 解析诊断测试模块22 passed；加知识上传/检索集成测试共23 passed、0失败、1 Starlette/httpx弃用warning，最终JUnit `.local-run/rag-long-run/round-20261117-43-acceptance-junit.xml`。`py_compile`通过。
- 本轮修改解析器及其测试；没有真实模型或外部provider调用，预算增量0。目标检查待本次文档更新后复核，P0-A仍缺可证明新鲜、授权、未曝光且样本充分的新来源。
- 原始工作簿线索：历史`component-inventory.json`记录原文件SHA-256为`51228a75d5f22ed9a058c9a7c29834989ab56da95e35435164084c537b9ec311`且上传时匹配；其本地评估摘要仍报告历史解析7/9、5922行。以该哈希检查`_assessment_work`和`assessment-results`现有XLSX未找到原文件；已生成的工作簿不得冒充源文件，需从原上传/备份存储取回完全同哈希字节。
- P0-A解析技术子项补强不等于原始工作簿完整性、独立留出和P0-A整体完成；P0-B/C、UX、远端验收未关闭，P1/P2未放行。详见`rounds/ROUND-20261117-43.md`、`evidence/ROUND-20261117-43.json`。

## 当前有效状态（2026-11-17，round42 模型调用期间治理变化时序回归）

- 本轮继续P0-B，未改变18项目标或P1/P2门禁。为验证请求期间资料状态变化，在真实SQLite ORM校验链路上增加服务级反例：模拟模型调用期间撤回版本或禁用单元；两种变化均被模型返回后的citation/governance重检拦截，答案未被返回。
- 完整`test_rag_upgrade_correctness.py`与`test_retrieval_eligibility_unified.py`：80 passed、0 failed，JUnit `.local-run/rag-long-run/round-20261117-42-p0b-junit.xml`。与之前批次有覆盖重叠，不跨轮累计为独立测试数。
- 仅新增测试，未修改生产逻辑。验证使用SQLite和mocked retrieval/model；不是PostgreSQL/Milvus真实组件、真实模型或公网浏览器证据。
- 本轮模型调用/token增量0；预算沿用最近核实值531/800请求、3,608,925/8,000,000 tokens，预留0。未访问/修改relay、未部署或写远端。
- 总目标检查仍为`consistent=true, complete=false`；P0-A新来源、P0-B整体关闭、P0-C真实问答等仍未完成，P1/P2未放行。详见`rounds/ROUND-20261117-42.md`和`evidence/ROUND-20261117-42.json`。

## 当前有效状态（2026-11-17，round41 P0-B版本/权限/支撑与非有限重排分数）

- 总目标仍是完成`GOAL-LOCK.md`和`GOALS.json`锁定的18项；本轮仅推进P0-B隔离正确性回归。P0-A新来源、P0-C真实模型问答、整体UX和远程发布验收仍未关闭，P1/P2未放行。
- 本轮3个隔离模块通过16项：冻结版本钉扎及judge支持冲突、受限Embedding外发拒绝/脱敏、关闭judge时字段码引用支撑；无真实模型调用。JUnit：`.local-run/rag-long-run/round-20261117-41-p0b-junit.xml`。
- 审计发现重排器已有非有限分数fail-closed实现，但无NaN/Inf回归覆盖；新增NaN、正Inf、负Inf三例，均降级并保持原候选对象/顺序。重排器全模块19 passed；JUnit：`.local-run/rag-long-run/round-20261117-41-reranker-junit.xml`。
- 本轮共35项通过、0失败；无生产逻辑修改。目标检查器`consistent=true, complete=false`，2项verified、9项in_progress、7项pending。
- 模型预算无变化：531/800请求、3,608,925/8,000,000 tokens，预留0；本轮调用0。按round40安全边界，不触碰临时relay凭据、不启用模型路由、不执行真实模型问答。
- round40报告和candidate37-attempt2结果保持历史有效但范围有限：其真实登录/布局不等于真实问答验收。工作区其他未提交修改均保留。
- 本轮文件改动仅`backend/tests/test_retrieval_reranker.py`及long-run交付文档；应用行为与默认设置未改变。详见`rounds/ROUND-20261117-41.md`和`evidence/ROUND-20261117-41.json`。

## 当前有效状态（2026-11-17，round40 candidate37通路与预算边界审计）

### round40 追加（2026-11-17）

- candidate37-attempt2真实浏览器登录与任务台桌面/390px布局记录见`.local-run/rag-long-run/round-20261116-39/candidate37-browser-auth3/results.json`；`/auth/me`通过，但无真实模型问答结果。
- SSH反向隧道health为200并返回中央账本就绪标记；未认证completion探针返回401。探针前后中央provider请求和token增量均为0。
- 中央`BUDGET.json`与共享SQLite一致：531/800请求、3,608,925/8,000,000 tokens，预留0/0，未知usage 3；剩余269请求、4,391,075 tokens。
- candidate37本地预算汇总为0/0；SQLite尝试数0、预留0，但`limits`尚未初始化。路由启用在预检处停止，没有重启API/worker、改Nginx/profile、启用预算或发起认证请求。修正本地预检并新增测试；桥接/预算测试25 passed，py_compile和diff check通过。
- 扩展P0-B本地隔离回归两批：12模块212 passed及4模块46 passed，合计16个不同模块258 passed、6 subtests passed、1条Starlette/httpx弃用warning。此为隔离回归，不代表真实模型、业务holdout或生产治理验收。
- 安全记录：在上一轮停止边界提出之前，桥接已生成并上传一份relay凭据；值未记录，未用于认证请求。其后没有读取、移动、改写或轮换凭据；SSH隧道已关闭。
- P0-A仍缺合格新来源；P0-B/C、整体UX、远程真实问答与回退未关闭。P1/P2继续锁定。详见`rounds/ROUND-20261117-40.md`及`evidence/ROUND-20261117-40.json`。

## 历史有效状态（2026-11-16，round37 当前源码发布包与候选容量审计）

### round38 追加（2026-11-16）

- 已实现独立candidate37发布脚本`backend/tests/rag_remote_candidate37_release.py`：默认read-only，显式执行才建新候选；含源码包校验、数据库dump/restore和逐表行数/schema head对照、零额度守卫及candidate37专属回退入口。脚本py_compile通过；预算护栏单测11 passed；发布包1002个成员逐项校验哈希。
- SSH身份与candidate28 `app_commit`源码后缀匹配；远端read-only预检通过：源码包hash身份匹配，预算relay ready，候选额度0，root可用约4.51 GB、`/home`约6.95 GB。
- 唯一远端写入为暂存当前source archive、manifest与部署脚本到`/home`；**没有**创建candidate37 release/容器/网络/volume/DB副本/preview，没有服务或数据库改动，没有模型调用。
- **阻断**：Milvus接入candidate network后仍是可写API；当前没有只读账号、访问代理或候选独立副本。不能执行已写好的`--execute`。round39先核实Milvus业务调用及round24恢复副本成本；隔离恢复独立Milvus/etcd/MinIO并核验集合身份，或建立经验证的只读路径。容量须按构建与新向量服务峰值复核。
- P0-A依旧缺新鲜、授权、未曝光且样本充分的来源；已观察题只能作回归。P0-A/B/C、UX和部署/验收仍未整体关闭；P1/P2未放行。详见`rounds/ROUND-20261116-38.md`与`NEXT-TASK.md`。

- 唯一行为目标：在不改变默认排序、不动已冻结索引、不重复付费调用的前提下，定位并修复 P0 检索/上下文正确性问题，并为独立留出建立条件。正式 P1/P2 仍未放行。
- round29 使用已观察 tuning 集12题，在真实PostgreSQL/Milvus/BGE上完成SQL标识符加分A/B（答案生成和judge关闭）：相同源码/语料/索引，关闭Hit@5=3/12、MRR=0.2065、角色上下文6/15；开启Hit@5=10/12、MRR=0.6925、角色上下文15/15；0外部模型调用，0权限/版本泄漏。结果只可作回归，不能当holdout质量通过。详见`rounds/ROUND-20261116-29.md`。
- SQL 目标证据有3/15未进前50，其余虽被召回仍有6/15角色要求未进入前12上下文；候选池约1041-1106，rerank/返回50，legacy 装配窗口12。问句字段码抽取为空，SQL单元无target_field_code/table_code，故此前精确字段码加分未被此题集触发。
- 冻结时源码/runtime29 API+worker身份`dd3438b7522a231e6339d0c6aab3d4f0cf7e8ed25008e1020ecdf3e01a6af95d`，端口18124健康；最终同源A/B由独立进程运行，源码身份`e6253c20cd1657869c216377b1f58dbff8ee3a497885fcc4dda02ded65d64101`（并非旧API/worker已热载修后代码）。题集版本`10120bb574470ab94b7a0ba781c80600fcb306fd91a2d787ed2d068c1bdfea3a`，语料哈希`072efb43292a6e5c23328a9ed912bf47fd1adaa7702ae109ddc81a77c1221948`。SQL identifier实验开关默认false。
- 修后定向35 passed/6 subtests；最终源码检索、问答和正确性回归195 passed/1 warning，JUnit见`.local-run/rag-long-run/round-20261116-29-final-sql-identifier-regression.junit.xml`。仓库源码/模型预算统计净增0 provider请求和0 token。题集已观察，永久只能作回归。
- 累计模型预算仍为531/800请求、3,608,925/8,000,000 token，预留0。round30审计后没有可用的本地独立来源；下一步获取新来源包，再建立按文档族隔离的独立holdout。冻结前不生成/裁判；保持权威排序契约和默认关闭实验，不用待确认掩盖召回缺陷。
- round30 已只读核验5个候选来源并计算哈希。三份产品5.1 SQL为同一已公开/演示ETL家族，多源 SQL 位于历史评估目录并在交接内容曝光，账户 lineage SQL 只有单条窄查询；没有可证明新鲜且样本充分的本地来源。P0-A 阻塞原因和恢复条件见`rounds/ROUND-20261116-30.md`；禁止冻结或调用模型，直到取得新来源包。
- round30 调用/token净增0；`rag_goal_check.py`=`consistent=true, complete=false`，P0-A/B/C继续in_progress，所有已有未提交工作保持不变。下一动作已改为定位/取得新鲜来源，不再盲目搜索候选文件名。
- round31 修正可选历史案例 `no_historical_case` 被误并入主体证据缺口的问题：仅当历史案例步骤明确`required=false`时剔除全局缺口；必需步骤与其他工具同码缺口保留。执行过程保留降级提醒并使用业务中文。定向31/31与`tsc --noEmit`通过；前端全套`npm test`未通过，生产目录浏览器首测超时及两个其他页面契约断言失败，详见round31。没有调用模型，预算不变。
- round32 使用`.next-round32`构建在`127.0.0.1:3222`完成隔离生产前端浏览器复验：主体依据区不呈现可选历史缺口，执行过程显示业务说明且隐藏内部工具键，390px无横向溢出；桌面/移动截图均未见发布身份告警。结果`production_frontend_browser_mocked_api`，3/3通过；API由Playwright夹具mock到本机API代理地址，没有真实后端、登录、模型或远端证据。浏览器产物在`.local-run/rag-long-run/round-20261116-32/browser-attempt5/`。本轮无模型调用，预算仍531/800请求、3,608,925/8,000,000 token。
- round32 只关闭本地生产构建/mock浏览器交互子验收；G-UX-IMPLEMENT/G-UX-ACCEPT、P0-A/B/C及所有正式发布门禁仍未关闭。P0-A仍等待可追溯且此前未曝光、样本充分的新授权来源包；本轮未部署、未切公网、未执行真实任务链路。
- round33修复`retrieval_sql_identifier_boost_enabled`被`query_expansion_enabled`意外门控的问题；100项检索/上下文/资格治理/正确性回归passed，py_compile通过。匹配round29冻结身份的PostgreSQL/Milvus/BGE真实组件retrieval-only on/off各12/12成功：Hit@5 10/12 vs 3/12、MRR 0.692460 vs 0.204833、角色上下文15/15 vs 6/15；语料未变、权限/版本泄漏0、provider调用0。round29已观察且gold无人工批准，不能作为独立留出或质量通过；实验开关默认false。应用源码SHA-256 `7534FA3DC5967D2DD09DF801C1DD08146331537535E2DFE2D93BF88AF02E4446`，组件源码身份`f30a4cd5116b40582cd13a5159182c1ba59507f1b4b72662534f5eec971e8476`。错误project1的无效attempt和隔离DB追加的检索日志均保留。目标检查器`consistent=true, complete=false`、11 passed/4 subtests。完整hash/配置/限制见`rounds/ROUND-20261116-33.md`及`P0-SQL-BOOST-EXPANSION-COUPLING`。
- round33没有新增provider请求或token；预算仍531/800、3,608,925/8,000,000，预留0。回放进程已退出；用户所有既有WSL Docker服务保持运行，本轮未停止任何共享组件。P0-A/B/C、整体UX、远程部署/验收/回退及总交付仍未完成；P1/P2不放行。
- round34审计确认字段/码值确定性缺口、显式`cannot_answer_reason`、冲突和装配角色缺失均作为judge不可覆盖的硬阻断；冻结版本由检索器和问答组装前双重fail-closed过滤。本轮未发现新生产缺陷，只增加judge关闭/全部支持/timeout三路径的端到端状态矩阵；相关三组回归69 passed，新矩阵3 passed，py_compile与diff check通过。性质为Mock/隔离测试，不是模型语义验收。详见`rounds/ROUND-20261116-34.md`。
- round34 provider调用/token净增0/0，预算仍531/800和3,608,925/8,000,000，reserved 0。当前直接下一步为冻结版本全链路反例与防误伤测试；P0-A来源阻塞、P0-B/C、整体UX及远端发布目标仍in_progress，P1/P2未放行。
- round35新增问答服务层版本钉扎集成反例：多查询合并后错版v2与缺版本候选被二次fail-closed过滤，只有匹配冻结v1进入上下文/prompt；1 passed。性质为隔离Mock/服务测试，未跑真实组件或模型，生产代码未改。详情`rounds/ROUND-20261116-35.md`。
- round35 provider调用/token净增0/0，预算仍531/800、3,608,925/8,000,000，reserved 0。下一步只读核验隔离候选部署身份、服务与budget relay，再执行P0-C真实用户链路；不切原公网入口。P0-A/B/C和18项目标仍未完成，P1/P2未放行。
- round36固定host key通过、33条远端只读命令完成、远端写入0。candidate28三容器仍以旧round28镜像运行且无published ports，不能代表round33/34/35后的源码。根分区可用约4.3 GB，`/home`约6.5 GB；新候选须先核算空间与隔离数据路径，严禁删除旧容器/镜像/备份。WSL现有PostgreSQL/Milvus/Redis容器保持运行。详情`rounds/ROUND-20261116-36.md`。
- round36模型预算净增0/0，仍531/800、3,608,925/8,000,000，reserved 0。下一步核对当前源码包、构建依赖、远端隔离网络/挂载、共享预算relay及磁盘后，才可形成新候选发布清单；执行前审查逐条命令。公网入口不切换，旧服务/数据不动。
- round37生成当前worktree的1002文件源码包，source hash`f30a4cd5116b40582cd13a5159182c1ba59507f1b4b72662534f5eec971e8476`、归档3434359 bytes；不含凭据/数据库/上传资料。依赖锁与70个迁移文件均与candidate28包相同；candidate28 `/version`仍为旧source hash。预算relay只读检查ready。
- round37测试主机空间：root约4.3 GB、`/home`约6.5 GB空闲；在线PG数据目录1.2 GB且被旧candidate挂载，不得文件复制。已确认旧升级脚本会停止/替换旧候选，不可重用。下一步为round38独立候选脚本，必须一致性dump/独立恢复DB、隔离Redis、只读复用Milvus、零模型预算、独立loopback预览。两份只读计划10条命令exit0，远端写入0；预算仍531/800、3,608,925/8,000,000，reserved0。详情`rounds/ROUND-20261116-37.md`。
- 124题完整回归、SQL 20题零Hit@5、全量生成裁判与远端治理/回退历史见下方“历史状态（round28）”；原公网入口未切换。所有P0仍未关闭，P1/P2未放行。

## 历史状态（round28）

## 历史状态（round28恢复，已失效）

- 此节覆盖以下历史状态。session20936等待job26时HTTP502退出；后台核验仍正常running，已达5696/5985。新增tests/rag_resume_holdout_index.py仅续查现有job26，session36318在途，不重复上传或提交索引；完成后核对Milvus健康、活动索引及语料哈希再恢复冻结。
- 远端问答attempt-2已exit0，生产登录、真实DeepSeek模型及usage、V1实际引用、原文、桌面/390px与焦点归还均通过；仅为合成资料链路，不代表银行黄金集质量通过。session84777预算隧道和75306维护会话保留。
- 全旧题委托审核新增发现：SQL-I01..I10绑定18025、SQL-T01..T10绑定18028，实际单元分别仅80/86字符来源摘要，不含题目所问CASE；此前已读104道业务题，SQL20题不得据此批准。正在核验原始脚本与其他入库单元，必须保留旧gold及失败，明确纠正证据绑定。
- 当前源码27ffd1261a9c6e6fe4ae1dc89dbee4a8df5144791c83a352c7288caca027ecdf保持不变；新留出首次生成/裁判完成前仅修改tests与文档。任务台task14可选历史依赖导致blocked的红测仍1failed/3passed，尚未实施生产修复。
- 最近账本125次/771575token、预留0，后续以共享账本为准。18目标未完成，P0未关闭，P1/P2未放行。

## 历史状态（2026-11-16，round26/27，已失效）

- 最新补充：固定上游共享预算relay的8项测试通过，SSH双向隧道session84777就绪（预览18130/relay18131，远端回环18090）；候选模型route配置exit0，仍无直连云端出口。profile传输local_vllm但classification local_only=false。维护75306仍可接plan。不要终止隧道后误称候选模型可用。
- 远端生产任务project34/task14首轮blocked：必需回答硬依赖optional历史案例，后者无案例跳过。反例round28红测1failed/3passed已保存，应用未改，等待新留出冻结完成。另直接问答真实答案grounded/V1引用/usage通过，原文按钮测试名称错误timeout，session26377正跑独立attempt-2，先读退出码。
- 账本最新124次/770012token、预留0（第二次问答在途以实时账本为准）。session20936已完成六资料入库，job26正在5985单元向量索引；source_hash仍27ffd。不得重复启动或冻结时改应用代码。

- 本节覆盖下方历史。源码身份修补纳入frontend/hooks，新增红测后21项回归通过；最新hash为27ffd1261a9c6e6fe4ae1dc89dbee4a8df5144791c83a352c7288caca027ecdf。runtime26 API18122与worker已核验匹配，冻结期间禁止改应用及backend/scripts。
- 服务器candidate-20261116-26前后端生产构建、迁移及隔离启动成功；维护session75306的preview-health已exit0。独立Nginx仅127.0.0.1:18089，公网入口未切换；候选容器历史名candidate25但镜像为round26。远端模型额度仍0，尚无跨主机共享预算通路，不能称远端模型或浏览器验收通过。
- 新独立SQL来源12题已在任何生成前完成委托预期审核；session20936正在真实入库，job20工作簿1600/5958，后续还需其他资料及项目索引。恢复文件round-20261116-27/fresh-mart/ingestion-state.private.json；不要重复启动。冻结、生成、裁判均未完成，本批provider调用0。
- 远程盘点与备份两个目标已verified：两库320表行数匹配、4143文件哈希匹配、7个向量集合stats匹配，原服务正常。最新累计模型账本120次/763288token、预留0；3次历史未知usage保守计账。P0未关闭，P1/P2未放行。
- 当前下一动作：检查预览脱敏结果、建立经本地共享账本计数的候选模型路由，等待session20936完成冻结再进行12题首测；同时补最新治理页面。禁止重跑旧付费生成或覆盖失败产物。

## 历史状态（2026-11-16，round25，已失效）

- 本节覆盖下方历史。round24两题freeze/generate/judge/summarize均exit0：2真实、均grounded、3/3支撑、2/2完整、角色2/2、泄漏0；旧失败保留。累计120次/763288token，预留0，历史故障unknown3。
- 远程认证成功，原库/上传/部署/Redis/索引已备份；两库隔离恢复320表行数全部匹配（1280449+1299284行），4143文件SHA匹配；Milvus新私网恢复7集合stats一致，原应用live/version均200、无paused。备份目录/home/rag-long-run/backup-20261116-24；完整私密证据在round24/remote-*。G-REMOTE-INVENTORY已verified，backup尚待闭环记录。
- 撤回/历史预览生命周期缺少提示：新增6红后改document_preview_service，四组83passed/1依赖deprecation warning，session90040 exit0。授权历史原文仍可读，检索继续排除撤回。新runtime25已在18121启动，源码b79678af...，Redis16390的8/9。尚无最新治理浏览器。
- 独立发布初次白名单包漏frontend/hooks，远程backend镜像构建成功、frontend构建失败；未启动候选、未切换入口。旧发布保留，release目录/home/rag-long-run/releases/candidate-20261116-25。正在修打包和身份漏hooks；原源码身份没有记录hooks也需补齐。新增红测正在执行，后续修rag_regression与rag_review_environment、重打独立新包/新release，不覆盖原失败。
- 远程维护会话75306仍停在Next plan path or exit，可继续发plan文件路径；认证只在内存。最新只读输出round25/remote-build-inspect。所有旧模型生成已收尾，无在途付费。
- 三份新SQL（汇率、终端、集团成员）已读原文，尚未写gold、入库或生成，不算留出通过。后续先冻结来源期望及独立问题家族，再生成；全124题委托批准仍未完成。P0未关闭，P1/P2未放行。

## 历史状态（round24，已失效）

- 本节覆盖下方历史状态。round23五题生成、裁判、汇总、生产build与五组浏览器均已exit0；不得重复在途命令。详见ROUND-20261116-23.md。
- round24句后引用绑定修复：红3failed/9passed，绿86passed/6subtests，272.20秒，session27317已exit0。新增建议不能强化为要求的提示，尚待两题真实复验。
- runtime24启动session56825曾超时exit1；随后API18120及worker已经就绪，日志无启动错误，正在核验身份并恢复缺失state元数据，不重启、不覆盖旧runtime。
- 新凭据重试session81877已exit0：主机公钥与首轮一致，24项只读盘点成功，远端写入0。证据round-20261116-24/inventory-attempt2/inventory.json；后续先备份恢复验证再部署。
- 预算113次/732529token，预留0；下一动作恢复runtime24状态、冻结02dc81ee70c8e016与98869678ef262d9e，真实生成上限2、裁判上限10。全题批准、新鲜独立留出及治理页面仍缺。P0未关闭，P1/P2未放行。

## 历史状态（round23，已失效）

- round21生成/裁判/汇总均已exit0，15题真实、27/27引用支持、13/15完整、角色上下文16/17/实际引用15/17，泄漏0；6待确认已逐题审查，量化题缺完整枚举合理，不能全称误拒。全部旧题仅回归。
- round23合成反例修前11failed/1passed，修后88passed/6subtests；加查询名称/混合未知范围防漏检后77passed/6subtests，有重叠不相加。另批准元数据红3failed→绿29passed。修规则编号误抽、字段前缀、隐式冲突范围，显式冲突/同字段对立证据仍保守；加正文/另列主张identifier_diagnostics，未直接消除未知误报。
- 当前新runtime-20261116-23：API18119、前端18103，Redis16390的4/5。源码6dbbc64dd7e8a0b87d6f7adcce8210652d4893ac7ba69308ce933468553d9e66；API/worker/schema/ready及语料已核验。冻结5题snapshot f8e4f863856cdef4683f19de18eaafeea7288293ee9bce3f6f12a5376c922c4e，freeze session95453 exit0。
- 五题真实生成session65278正在运行，max-generation-requests5、workers2；下一步仅收尾该批再judge（显式上限20）和summarize，不重复生成。冻结期间禁止改生产源码/backend/scripts。
- 独立生产前端build session95541已编译成功、类型/lint检查完成（其他模块已有hooks警告），54页已生成，正在build traces；必须读取退出码。build使用专属.next-production-rag-20261116-23、API18119及同commit/build_time，未覆盖旧构建。Next自动更新next-env/tsconfig，二者不在应用哈希集合。
- tsc session31828 exit0；任务创建成功后折叠面板已加入当前身份，失败时保留草稿。待生产真实交互和截图复验，不重跑旧空项目脚本（项目3已有task3）。
- 预算最近96次/650097token、预留0，3次历史注入usage未知保守计账；五题在途以实时BUDGET/SQLite为准。总上限800次/800万token。
- 十八目标检查consistent=true、complete=false，6in_progress/11pending/1blocked_external。远程37716认证失败，凭据核对问题已发送；远端命令及写入0。P0仍未关闭，P1/P2未放行。
- 下一唯一动作：读取session65278和95541，生成结束后跑5题离线裁判。主线程执行，未启动子代理。

## 历史状态（round21/22，以下已被上节覆盖）

本节覆盖下方旧进展。18项目标仍未完成，P1/P2未放行。恢复时先读取本节及NEXT-TASK，不重复已完成的付费生成。

- round21在生成前完成十五道可答题原文预期的委托业务批准，记录delegated-answerable-review-20261116.json；已观察题仅作回归。approved-snapshot数据集8461d04ec8f5ba6e5989c92c216f7ab3fe85a42c46460840aa615b6fdd19472d，旧gold另存。
- runtime-20261116-21为当前冻结环境，API18118/前端18102，Redis16390的2/3。源码9709fe0eb257374e18e7c2077031c3a9e229f88782fa0214689bc9e3d171550a，身份及语料已核验；旧runtime不能代替。
- 十五题生成session35587 exit0，15/15真实通路、版本/项目泄漏0；9 grounded、6 needs_confirmation。裁判session48121已输出15/15、30次本批请求，仍待进程退出及最终汇总。禁止冻结期间修改生产源码或backend/scripts。
- round18三题独立补审已完成，第二题原完整性误报消除；第三题14170角色缺口保留。round19断连分类修复53项定向回归通过；真实生成断连、judge503及恢复三条浏览器路径通过，故障进程已结束。不是同构建生产验收。
- round20任务台六组真实交互通过，42项视图测试及tsc通过；报告待补结果。生产build/视觉验收、治理异常仍缺，成功创建后面板仍展开待评估。项目3已创建task3，不能重新用作空项目。
- round22服务器只读盘点session44864 exit1，指定入口认证失败AuthenticationException；证据round-20261116-22/inventory-attempt1/inventory.json，远端写入0。已请求用户核对凭据，不猜口令/端口，不阻断独立本地工作。
- 预算截至本次恢复读取94次/640031token，预留1次/21140token；3次显式故障usage未知已保守计账。实时以BUDGET.json和共享SQLite为准。
- 下一唯一动作：收尾session48121，使用同快照summarize，逐题定位6个待确认原因与引用支持/完整性，再更新台账。子代理权限条件不满足，主线程执行。

## 历史状态（round18，已被上节覆盖）

本节覆盖下方历史进展中的旧会话、旧预算和旧下一动作。总目标18项仍未完成，P1/P2未正式放行。

- round16真实任务→V2激活→跨项目V1原文、下载字节哈希、390px/Escape焦点归还已通过；合成资料项目5与业务项目4分离，不冒充业务金标准。
- round16真实业务三题：完整2/3、引用支持10/10、角色3/4；54205ddddc3bc29b已grounded，第三题仍缺14170。第二题完整性评测遗漏其他合法实际引用，原结果保留。
- round17历史network_error五题复测session15784已结束exit0；五题均real_model/HTTP200/泄漏0，四题needs_confirmation、一题grounded。未做本轮语义审核，不声称旧网络故障已修复。
- 预算快照40次/246778token，无未知usage或预留；真实后续以BUDGET.json及共享SQLite账本为准。
- round18仅改两个离线评测脚本：统一gold、actual_cited_sources及context身份；4个新增反例修前失败，修后连同工具29passed；补充来源身份护栏20passed。两组部分重叠，不相加为不同用例数。
- 下一唯一动作：对round16保存答案做独立补审，明确生成哈希与评测哈希，不重新生成、不覆盖原评测；首次输出父目录不存在已在发送前中止，调用0，补mkdir parents。
- runtime-20261116-16仍服务18110/18099，API/worker源码293ea8035190；当前工作区仅评测脚本已变化，不能把该API标作新源码已加载。新生成须重新建立匹配身份环境。
- 当前不启动子代理：danger-full-access不满足用户AGENTS对受限角色的启动条件。主线程完成并核对证据。

## 历史进展（仅供追溯）

> 2026-11-16 结果补充：round05 64 passed、round06 45 passed、round07 47 passed；round08 来源字段契约12 passed（19.90秒）。四项均仅关闭隔离子缺陷，真实模型/浏览器/业务批准仍未完成。

更新时间：2026-11-16（预算授权恢复轮09；以下本轮进展和风险含历史记录）
当前有效预算：累计上限800次provider/800万token；round13后已用22次/130145token，无未知usage或预留。历史“未获预算”描述仅代表当时状态。
当前唯一动作：round14校验范围64passed；round15来源/引用两批102个不同用例通过；round16任务模型身份和数值用量13passed。报告已存rounds/ROUND-20261116-{14,15,16}.md。新runtime-20261116-16启动session3999，18110/18099/Redis14+15；先读启动结果，再冻结3题及真实任务版本链路。冻结期间不编辑生产源码/backend/scripts。18109/18098仅代表round13旧源码。
业务批准：用户已授权代理逐题批准；3题原文预期已审核，记录delegated-business-review-20261116.json，不冒充human-approved，不批准有缺陷的生成结果发布。
目标版本：GOAL-MODE-PROMPT.md；原用户目标附件已完整阅读。
总目标：RAG P0→P1→P2、任务台 UX、保留旧数据的公网测试部署及真实验收，仍未完成。
当前阶段：P0收口；round01至08已结；长目标一致性护栏已初验。

## 本轮进展

- 分类上一轮：进展。已交付完整目标模式提示词，但未完成开发验收。
- 当前本轮建立 GOAL-LOCK、GOALS、FAILURES、NEXT-TASK 和本检查点；18 项目标全部保留。
- 只读核验分支 dsh/handoff-20261025-round73，HEAD 206d4313a5805613f5bf7e0b5db41390ab92d31f；未刷新远端；工作区已有大量未提交修改。
- Python 3.12.4，Node v24.15.0；未访问远程，未修改数据库/索引或默认实验开关。
- 新增隔离反例，旧代码 1 failed：第 21 条主张得到 claim-1 而非 claim-21。
- 最小实现：跨批全局 claim ID；每批发送证据和 pinned_versions；仅首批汇总引用 verdict，后续 pair 只作主张；收集各批冲突。
- 新反例修后 1 passed，71.29 秒；结果在 .local-run/rag-long-run/round-20261115-01-green.junit.xml。
- 修前失败保留于 .local-run/rag-long-run/round-20261115-01-red.junit.xml。
- 旧的“第二批无 evidence”断言已改成每批都有证据且引用仅汇总一次；两组隔离回归最终34passed，exit0，613.92秒。
- 新增 claim/pair 双格式及后续timeout防误伤通过；原上限/尾部/版本/冲突/关闭开关用例通过。py_compile和git diff --check通过。完整报告见rounds/ROUND-20261115-01.md。

## 文件与命令

本轮修改：
- backend/app/services/rag/citation_validator.py
- backend/tests/test_overnight_citation_status.py
- docs/development/long-run/GOAL-LOCK.md、GOALS.json、FAILURES.md、NEXT-TASK.md、CURRENT-CHECKPOINT.md

在 backend 目录：

    .venv/Scripts/python.exe -m pytest tests/test_overnight_citation_status.py::test_claim_batches_keep_global_ids_and_evidence_without_double_counting_citations -q --junitxml=../.local-run/rag-long-run/round-20261115-01-green.junit.xml

第一次虚拟环境相对路径错误（未进 pytest）已改正。无真实模型调用、token=0；当前只运行 SQLite/Mock，L2 证据。未设置新真实调用预算，历史383次裁判等记录仍仅归属旧批次。

## 风险和未完成事项

- 批处理子缺陷已完成相关隔离回归；不能据此宣称整个D03或真实模型问题关闭。
- 17 个真实裁判格式失败、D01 来源边界、D02 可答题、D04 网络降级和 D05 当前浏览器仍未关闭。
- 新留出、业务批准、P1/P2、UX、远程所有门槛未完成；不允许正式进入下一阶段。
- 配置读取时曾回显敏感连接信息，已登记 SEC-LOCAL-CONFIG-OUTPUT-001，禁止复述并改用安全摘要。
- 已完成Windows/WSL端口复查；18105 ready恢复200。普通.env 5432不可达，专用15439可达；尚未修改旧配置。
- 18105 Python进程启动早于新代码，/version旧build_time；无法证明当前源码已加载，不把其health通过写成新代码验收。
- 回归session_id=24161已终结exit0；静态检查5421、53154也均exit0，无本轮未结束测试。不要重跑已通过整批。
- 只读环境命令已终结：专用PG/Redis与Milvus、Ollama容器运行；18105/health/ready 和18095/health/ready各8秒超时，18097/health=200。不是组件验收通过。
- 新增 BUDGET.json：新增真实模型额度0，当前调用/token=0；旧评测配额不自动复用。DECISIONS.md 记录旧跨项目检查点不可用于本轮。
- round03已修改backend/scripts/rag_review_environment.py，支持--port/--redis-database及源文件哈希；拒绝非空旧目录/分库、占用端口、非专用数据库。新增backend/tests/test_rag_review_runtime.py。
- 工具回归session8649已结束exit0，17passed/7.47秒；py_compile/diff检查通过。
- 新runtime已启动：.local-run/rag-long-run/runtime-20261115-03；18106，broker6/result7，backendPID38028/workerPID11084。旧服务保留。
- 真实组件/API/认证/worker身份探针session82074结束exit0，详见evidence/ROUND-20261115-03-runtime.json。真实模型调用0。
- 源码身份5195d99ecc99f9ba5a721afa6707141d4ba7351b7dcbd848bc760de17593977f，766文件已存私密源码ZIP；107个依赖版本已保存。本轮改代码后不得继续把旧runtime当新候选。
- 已向用户异步询问新真实模型预算（800次/800万、200次/200万、暂不调用），目前没有收到答复；相关付费调用仍0，其他工作继续。
- round04：生成载荷JSON、publisher/工作表/行定位、建议/反馈/体系语义修复；3个新失败反例后相关63项通过121.05秒。源码候选已不同于18106，禁止混用构建证据。
- round04相关测试session18243已结束exit0；当前无未终结测试会话。API/worker为有意保留的开发服务，不是仍待完成的测试命令。
- round05修前7个格式反例全部失败，证据`.local-run/rag-long-run/round-20261115-05-red.junit.xml`，645.15秒；现已在网关校验verdict标签，格式缺失/非法的引用裁判显式`invalid_model_response`，合法unknown不降级，faithfulness保留`invalid_judgement`。修后citation/faithfulness/overnight/vnext2回归64 passed，3697.08秒，exit=0，JUnit`.local-run/rag-long-run/round-20261115-05-regression.junit.xml`，SHA256 `B99A470FABB1A912B153907592540A0A51BB153FDF6C2ED8AA83649528FB9584`。这只关闭格式边界子缺陷，不关闭D03整体。
- 新增只读目标账本检查器`backend/scripts/rag_goal_check.py`和11项unittest，全绿；当前检查显示18项中0 verified、2 in_progress、16 pending。检查器验证目标覆盖、预算、证据路径/哈希、source hash及阶段依赖；不会自动关闭目标。py_compile通过。
- UX静态初查确认任务台已有URL筛选、列表/详情上下文、轮询、操作、错误态、诊断和证据抽屉；尚未视觉/键盘浏览器验收，也未改UX。Playwright skill已读。
- Playwright CLI 打开18094任务页超时，已中止；没触发业务写入。真实浏览器验收仍未跑。
- round05至今模型请求/token=0，未访问公网服务器；`git diff --check`和py_compile通过；session56607已exit0。

## 下一步唯一动作

下一唯一动作：读取新runtime启动session3999；冻结3题并真实复测，独立版本夹具prepare→页面创建任务→upgrade→页面原文验收。当前所有round14-16测试已结束，不重复绿色回归。P1/P2未放行。

恢复时先读 GOAL-LOCK → GOALS.json → 本文件 → NEXT-TASK → FAILURES 最新事件，核对会话56607是否已结束并读取退出码；不得重启已结束回归或把隔离测试冒充真实模型通过。
