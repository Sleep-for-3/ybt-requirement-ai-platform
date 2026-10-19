# C01 / C02 / C11 补交复核

代码：`3db4db6516a2c2cd495fe4109701a5a6451cb393`。对照上一轮《银行智能平台-当前代码复核与今晚修复任务书-2026-10-06.md》C01、C02、C11 与本轮升级记录。

本次只读产品源码，在评审目录新增脚本与 JSON。全部 HTTP、浏览器存储、计时器与 React 边界为内存替身；复用真实 api.ts、http-response、草稿 key 表达式、存储 helper、polling registry 和 hook。未访问业务服务、模型或数据库；未修改源码、业务环境或已有工作区变更。仓库与上级工作区未检索到 AGENTS.md。

## 结论

| 项目 | 当前判断 | 已实现部分 | 尚需补交 |
|---|---|---|---|
| C01 | **部分完成，出现 P1 新回归** | A 的晚到续期不会再覆盖 B，也未把旧业务请求重放给 B；前端已请求服务端 logout | 正常成功续期后原请求必须继续成功；旧 A 请求的晚到 401 不能启动 B 的续期 |
| C02 | **原缺陷核心已关闭** | actor 来自真实登录 principal；跨账号 key/owner 校验、无身份与错误 owner 拒读均有效 | 把记录中 `/ai-skills/permissions` 更正为实际 `/ai-skills/capabilities`；真实浏览器仍属于明确验收边界 |
| C11 | **部分完成** | 失败后保留订阅；online 能恢复并取到终态；主任务详情有提示与手动恢复 | visibility 的 running 恢复不能再停住；成功恢复必须清提示，状态应按 job 隔离；其他进度页面需显示断连/恢复信息 |

脚本 `frontend-followup-reproduction.cjs` 实际执行 exit 0，结果在 `frontend-followup-reproduction.json`。exit 0 仅表示复现脚本成功执行，不代表上述补交项通过。

## C01：身份覆盖关闭，但正常续期被代次变化误拦截

文件：`frontend/lib/api.ts:32-35,75-89,139-147`。

`saveSession()` 在 `:33` 自增 sessionEpoch。`performSessionRefresh()` 在 `:86-87` 验证当前代次和刷新令牌后，于 `:88` 调用 saveSession，使代次增加。外层 fetchWithSessionRetry 在 `:146` 又要求原代次等于当前代次。因此 **同一用户成功续期也必然不进入重放**，返回原始 401；readApiResponse 认为请求已不属于当前代次，抛 401，但本地已有新 token。

内存实测：正常 A 请求首次 401 → refresh 200，令牌更新为 A-new；受保护请求调用数仍为 **1**，最终 `rejected_status=401`，而预期应请求第二次并得到 `{ok:true}`。真实使用中，审核、保存、生成、下载等在访问令牌过期时会失败，用户再次点击才可能成功。

已有测试为什么通过：`frontend/tests/session-epoch.test.mjs:121-122` 将 `/one`、`/two` 的拒绝 catch 为普通值；`:126-129` 只检查续期次数与 token，没有检查两条原请求的成功结果，所以“并发续期只一次”通过并不能证明“续期后业务继续成功”。

另一个未闭合路径：`api.ts:143-144` 在决定发起 refresh 之前，没有检查该响应是否仍属于当前会话。实测 A 的业务请求延迟返回 401、此时已登录 B，旧 A 请求会发送 **B-refresh** 到 `/auth/refresh`，并把 B token 轮换为 B-new。此测试中未跨账号重放业务请求，也未覆盖成 A，但旧账号响应仍触发了新账号的会话操作。

最小修法：区分**身份转换**和**同身份 token 续期**。登录/退出/失效递增身份代次；同身份续期通过专门的条件写入函数更新 token，不改变身份代次。发起续期前、完成后、重放前都校验请求归属；飞行中的 refresh 固定 epoch/token，并在结束时只清理自己对应的 promise，不能由旧 promise 清除新会话的 flight。

必须新增的回归：

1. 普通 401→续期 200→原 GET/POST/下载成功，检查结果和重放 Authorization，不能 `.catch(error=>error)` 后只检查 token。
2. 两个并发 401→一次续期→两个原请求均成功。
3. A 续期晚到、A 401 晚到、退出后晚到：不得启动 B 续期、不得重放、不得覆盖/清理 B。
4. 续期拒绝时保持失效处理；退出同步清本地且发送吊销请求，服务端不可达不复活本地身份。

当前已经关闭的证据：A refresh pending→退出/登录 B→A refresh 晚到，JSON 中 `old_refresh_after_login_b.closed=true`、B token 未变、旧受保护请求调用数 1；logout JSON 记录了实际 `/auth/logout` 请求和本地清理。不能再将这两项写成“完全未修”。

## C02：owner 确实来自当前登录用户，原缺陷关闭

身份来源链：`frontend/app/ai-control/skills/page.tsx:79-80` 请求 `/ai-skills/capabilities` 并保存服务端结果；`:96` 仅在 capabilities 存在时创建 SkillEditor；`:129-131` 取 capabilities.actor_id 构造独立 key。后端 `backend/app/api/ai_skills.py:69-80` 使用 `RealPrincipal` 并返回 `principal.user_id`，因此 actor 不是从项目 ID、显示姓名或任意本地设置猜出的。

实际调用：页面 `:145` 写入带 actor 草稿，`:164-165` 无身份不读、带 actor 读取；`:182,224` 按 actor 清理。`frontend/lib/unsaved-changes.mjs:79-90,98-108` 在 key 和 payload 上验证 actor/owner。

内存实测当前 key 表达式与 helper：A=17 能读 own；B=18 不读 A；未知身份 key=null；强行在 B key 下放 owner=17 的载荷，读取结果仍 null。JSON `c02.closed=true`。

记录与源码注释里的 `/ai-skills/permissions` 不是真实接口，应更正为 `/ai-skills/capabilities`。这属于文档准确性，不应重开账号隔离缺陷。真实浏览器双账号恢复尚未执行，本次结论为源码身份链+内存行为确认。

## C11：自动恢复和提示状态仍需补齐

### 1. visibility 恢复拿到 running 后又停止

文件：`frontend/lib/job-polling.mjs:50-57,60-70,87-89,99-108`。

online 的 resumeStalled 会将 failed=false；但 handleVisibilityChange 直接 poll，没有清 failed。一次恢复读取成功只清 errors、不清 failed，schedule 又因 failed 拒绝排程。

实测：3 次错误后，仅触发 visibility（网络已可用），第 4 次查询返回 running；`stalled_after_success=true`、`scheduled_timers=0`。这不是在线事件已恢复终态的用例，而是**页面重新可见时任务还在运行**的场景，之后无法持续观察完成。

最小补交：visibility 恢复使用与 online/manual 一致的 resume 过程，或成功读取时准确解除 failed；确保隐藏页仍暂停、恢复不会产生重复订阅或重复定时器。回归必须 running→continued polling→completed，不能只让第 4 次直接 completed。

### 2. 错误提示是全局且成功后不清除

文件：`frontend/hooks/useJobPolling.ts:11-17,23-27,46-49,64-74`。

onPollingError 忽略 registry 传入的 jobId，把所有错误写到一个模块级字符串 pollingUnavailable；useJobPollingStatus(jobId) 读的是同一个字符串。成功回调只 setJob，online 自动恢复没有清这个字符串；只有手动 resume 成功才清。

实测真实 hook：job41 连续失败后 online 恢复并收到 completed，`unavailable_after_completed` 仍是“后台任务状态暂时无法更新”；与故障无关的 job99 也读到同一提示。若 job41 已完成被删除，用户再点“立即重试”，resume 返回 false，提示仍不能清除。旧模块状态也可能跨页面或账号留存。

最小补交：状态以 jobId 为键，明确 running/stalled/recovering/ready 与 lastSuccessAt；成功、终态、解除订阅/会话切换时按归属清理；使用事件订阅推动渲染，或保留 1s 读取但必须有正确归属和清理。回归两条不同 job 同时订阅，只有失败 job 显示提示；online/manual 恢复成功后提示消失，终态不提供无效恢复按钮。

### 3. 其余调用方仍没有可见状态

目前只有 `frontend/app/jobs/[jobId]/page.tsx:82,92-98` 使用 useJobPollingStatus。其余实际使用点包括：

- `frontend/app/fields/[fieldId]/scenarios/page.tsx:79,88`
- `frontend/app/deliverables/[packageId]/page.tsx:27`
- `frontend/app/datasources/[datasourceId]/catalog/page.tsx:48`
- `frontend/app/uat/runs/[runId]/page.tsx:57`
- `frontend/app/knowledge/documents/page.tsx:109`
- `frontend/app/knowledge/documents/[documentId]/page.tsx:53`
- `frontend/components/requirement-workspace/RequirementWorkspace.tsx:144-145`
- `frontend/app/lineage/scripts/page.tsx:40`

这些页面已受益于 registry 的 online 恢复，不能声称仍全部永久不恢复。但连续故障期间仍只展示旧进度，没有断连说明和现场恢复入口。上一份任务书 `:133-135` 明确要求“可见断连状态”“三次断网后有可见状态”，因此仅主详情页接线属于 **范围部分完成**；本轮 C11 记录也承认了该边界。

最小补交：在已有公共 JobProgressPanel/同类状态区接入按 job 的断连、更新时间和恢复入口，避免逐页重复；逐项检查调用方是否实际渲染公共区。无需新任务模块。至少验证需求生成、交付渲染、知识摄取的进度面板和主任务详情页。

## 建议补交顺序

1. 先修 C01 正常续期成功却业务失败的 P1 回归，同时阻止旧 401 操作新会话。
2. 修 C11 visibility running 恢复与按 job 清理提示，随后补公共进度区接线。
3. C02 保持已关闭，修正文档接口名并补真实浏览器双账号验收证据即可。

禁止用当前 7/7 或 10/10 单测计数替代上述缺失断言。复核范围外的其他 C 项由根任务独立核查。
