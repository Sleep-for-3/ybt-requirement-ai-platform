# 验证记录

更新：2026-11-15。验证针对未提交工作区；未提交、推送或修改生产数据。下表保留 2026-11-14 的历史测量；最新解析修复、代理逐题审核、独立留出和真实裁判测量以 [原文审核验收](real-components/source-review-acceptance-20261115.md) 为准，不能合并不同快照的数字。

## 结果与证据层级

2026-11-15 新增验证：主定向回归 229 passed；最后解析与引用状态专项 33 passed；审核/组件工具专项 18 passed。三组有重叠，不相加；JUnit 位于 `.local-run/rag-source-review-20261115/{correctness,parser-support,review-tooling}.xml`。新增完整性审核输入契约 10 passed；随后补的两条 SQL 摘要误绑定反例均先失败，证明缺陷存在，修复后须再次通过。真实生成、裁判与业务放行结论见最新报告，不将单测代替真实语义验收。

| 验证 | 结果 | 证据边界 |
| --- | --- | --- |
| 统一后端定向回归 | 215 passed，1010.06 秒 | SQLite/Mock；含 XLSX 和组件工具回归，见 `real-components/correctness.junit.xml`；早期 194 项记录仍在根目录 |
| 最终影响范围专项 | 80 passed，31.00 秒 | SQLite/Mock，包含最后补修的历史意图、归档/草稿向量可见性、版本碰撞与恢复脚本；见 `real-components/final-fixes.junit.xml`，与统一回归重叠，不能相加 |
| 最后改动的边界专项 | 50 passed，17.46 秒 | 覆盖中文/否定码值、Agent 问答、重排；与整包回归有重叠，不叠加为 244 |
| 新增治理复核专项 | 62 passed，28.33 秒 | 在实施中验证过资料撤回、禁用、归档、正文变化、项目范围变化、版本变化及历史授权边界；后续已纳入整包回归 |
| 前端问答、历史与登录契约 | 8 passed | 纯函数/请求契约，不能代替页面验收 |
| TypeScript | `npx --no-install tsc --noEmit` 退出 0 | 使用最终生成配置；已恢复开发服务器造成的配置噪声 |
| 浏览器隔离链路 | 7/7 | Chromium、SQLite/Mock；见 `browser-results.json` |
| 104 题关键词回放 | 104 条逐题结果 | 仅一份合成资料；没有业务质量结论，不能用这份延迟代表实际业务系统 |
| 104 题真实混合检索回放 | 104 条执行完成，失败 0；全部 effective_mode=hybrid | PG/BGE/Milvus；前后代码/语料一致，检索 p95 2455.04 ms；未生成答案，未获人工金标准，不代表业务命中率通过 |
| 人工审核工作包 | 104 题；18 题有建议锚点，86 题有旧证据待核对 | 人工批准 0；包内含原文和定位，仅保存在本机忽略目录，摘要在 `real-components/human-review-summary.json` |
| 快照校验 | 通过 | `dataset.json` 的规范化内容哈希匹配 |
| 发布门禁反例 | 按预期拒绝，退出 1 | 将隔离报告与自身比较仍拒绝，缺失标签和真实组件不会被绕过 |
| `git diff --check` 与新增 Python 文件编译 | 通过 | 静态检查 |
| 真实 PostgreSQL/Redis/Celery/Milvus/BGE | 通过组件与治理补验，35/35 | 新增隔离 PG 16.15、Redis 7.4.11，复用 WSL Milvus 2.5.4 的独立集合；语料索引 5,922 行、原文哈希一致、就绪 200 |
| 真实组件浏览器 | 8/8 | 真实组件 + 真实模型配置（浏览器历史证据仍为 Mock 生成）；V2 已激活后，跨项目打开任务仍下载 V1 原始字节；见 `real-components/browser-results.json` |
| 真实模型及人工质量评测 | 未执行 | 没有外部模型调用；缺审核金标准及明确预算 |

完整后端复现命令位于 `README.md`。50 项专项命令：

```powershell
# backend
$env:AUTH_MODE='optional'
$env:ENVIRONMENT='test'
python -m pytest -q tests/test_rag_upgrade_correctness.py tests/test_agent_knowledge_question.py tests/test_retrieval_reranker.py
```

## 浏览器检查

本轮审核工具最终回归：12 passed，7.03 秒，见 `.local-run/rag-source-review-20261115/final-tooling.xml`。包含两条先失败后修复通过的 SQL 摘要误绑定反例，以及实际引用和候选引用区分的用例。

最终真实验收：124 个问答请求、119 次真实生成、5 次网络降级；引用支撑 40/409、17 题裁判降级。补齐实际引用并纠正 SQL 原文绑定后的 124 题完整性审核全部完成，旧题 63/104 完整、留出 0/20。项目/版本违规 0/124；383 次裁判调用在 496 次预算内。语料/配置/Prompt/索引及原答案文件哈希检查通过，生成代码与新评测代码分别登记；结果是业务不放行，不是通过。

使用最终源码启动全新 `.local-run/rag-upgrade-20261113-g`，没有覆盖旧数据库：

1. 错误密码请求返回 401，页面准确显示凭据错误。
2. 随机隔离账号通过登录表单获得 200 并进入项目页。
3. 问答从已审核激活的资料检索出引用，未运行裁判的等级上限为 C，接口显示 `not_run`。
4. 追问发送完整的 user/assistant 一轮历史。
5. 清空对话后历史归零；切换项目也保持空历史。
6. 顶部选择其他项目，打开任务时引用请求仍使用任务所属项目和回答版本；preview、content 均返回 200。
7. 390×844 视口无横向溢出；另有 1440×1000 桌面截图。

证据文件：`browser-results.json`、`evidence-desktop.png`、`evidence-mobile.png`。
截图中的 Mock 答案只验证状态与链路，不能据此声称语义正确。

## 全量前端检查未全绿

`npm test` 已执行，发现以下 4 项既有静态契约失败：

| 文件 | 失败项 |
| --- | --- |
| `frontend/tests/script-authoring-contract.test.mjs` | 批量建需：可多选、上限 10 张、逐表回显结果 |
| `frontend/tests/script-binding-contract.test.mjs` | 看板把未覆盖字段列出来，并说明“未覆盖不等于不需要” |
| `frontend/tests/structure-check-contract.test.mjs` | Word（内置版式）走 docx 契约，客户模板 Word 明确拒绝而不是套用 |
| `frontend/tests/table-coverage-contract.test.mjs` | 覆盖度必须把需求维与脚本维分开 |

4 个文件定向复现结果：16 passed、4 failed。它们依赖的交付看板、Word 自检、requirements API、相关 lib 及测试文件均经 `git diff --exit-code -- <精确文件列表>` 确认与 HEAD 一致，未在本次 RAG 修改范围内。未为获得全绿而改写这些断言或扩大修改范围。全量前端和远端 CI 不能标为通过。

## 失败反例与修正

- 首轮回归的 10 个 401 来自本机强制登录配置进入旧测试。统一回归入口现显式使用隔离测试配置，实际隔离服务仍要求登录。
- “无引用编号的 Mock 回答也算满分答案”的旧断言已改为：召回指标保留，待确认答案不进入成功答案分母。
- “裁判关闭时可信等级不受影响”的旧断言已改为：显式未运行语义校验，可信等级上限 C。
- 初版隔离夹具资料待审核、不可检索；随后按版本实际状态审核、激活。重复 submit-review 的 409 已修正，不跳过治理。
- 移动端发布标识提示挤宽顶部栏，现可换行，浏览器复验通过。

## 剩余阻断与回退

真实组件及浏览器链路已补验；DeepSeek 真实生成已完成 104 题回放，但人工标签、独立文档留出、原始工作簿解析完整性、M10/V14 业务对照、回答级 p95 同环境比较仍是阻断。原登录配置的当前错误已获得只读证据，历史事故归因仍缺原失败请求。后续不应据工程通过项开启默认重排、自动拒答或切换正式索引。

实验配置和回退方式见 `README.md`。未迁移正式数据库；隔离 PostgreSQL 已执行现有迁移至 `202611010014`，未新增 schema 迁移。历史实验配置保持默认关闭，测试凭据留在被忽略的本地 state 文件中。补验明细及恢复步骤见 `real-components/delivery.md`。
