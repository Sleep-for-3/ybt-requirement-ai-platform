# DSH M0 交付报告：环境复现与交接基线核验

## 任务 ID / 输入基线 / 当前状态

- 任务 ID：M0（第一单，只读核验 + 新开发环境安装 + 隔离测试 + 报告）
- 输入基线：`C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform`，交接清单 `HANDOFF-MANIFEST.json`（created_at 2026-09-30T15:09:43+08:00）
- 交接清单声明：files=1410, source_bytes=39,019,464, git_head=`3e94e5495a4faefa4e1b66aa23286e76cde91a3f`, includes_git_history=false, tracked_files_omitted=0
- 当前状态：**M0 PASS**（本机复跑全部通过）。已具备进入 B3-R1 的条件。
- 本机实际模型：**未提供、未调用**。本报告所有模型侧结论均来自 Mock/确定性路径；运行时不提供可核实的模型 ID，故不填写“实际使用模型”。

## 环境事实（本机复跑，非原机证据）

| 项 | 实际值 |
| --- | --- |
| 根目录 | `C:\Users\admin\Downloads\ai-platform-dsh-20260930-150943\ai-platform` |
| OS | Windows 11 专业版，NT 10.0.26200.0 |
| Python | PATH 无语料 Python（`C:\...\WindowsApps\python.exe` 为商店占位符，`py` 启动器不存在） |
| Python 解释器（实际使用） | DSH 运行时 `C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe` = **3.12.14** |
| 新建虚拟环境 | `backend\.venv`（全新创建，未复制旧 .venv），venv pip 25.0.1 |
| Node | PATH 无 node；DSH 运行时 `...\dependencies\node\bin\node.exe` = **v24.21.0** |
| npm | **本机原先完全不存在 npm**（DSH 运行时 node 的 `node_modules` 只有 README.txt）。已在新工具目录 `C:\Users\admin\.dsh\tools\npm10` 安装 **npm 10.9.9**（项目目录外，未改动 DSH 运行时） |
| Git | **交接包内无 `.git`**（协作方案明确排除 Git 历史），因此本机无法复跑 `git rev-parse/status`；HEAD 只能记录为“清单声明值”，不能声称本机核验 |
| 磁盘 | C: 剩余约 29.8 GB（依赖安装后） |

### 与交接清单的逐文件核对（强证据）

对 `HANDOFF-MANIFEST.json` 全部 **1410** 条目逐条比对文件字节数与 SHA-256：

```text
UTF8 verified_ok=1410 missing=0 mismatch=0 of 1410
disk_files=1429 extra=19
```

19 个 extra 全部是本次 M0 自己产生的证据文件 + 清单自身（`HANDOFF-MANIFEST.json`、`docs/evaluation/dsh-m0-20260930/*`、`docs/ux/acceptance/dsh-m0-cross-layer-browser-20260930/*`）。**未发现清单内文件缺失或内容不符，未发现来源不明的多余源码文件。**

> 说明：首次用 PowerShell 默认编码读取清单时出现 67 个“缺失”，实为 GBK 误解码中文路径造成的假阳性；改用 UTF-8 显式读取后为 0 缺失。该假阳性记录在此，避免后续误判。

### 迁移链与 AI Skill 表（隔离 SQLite，非用户库）

```text
python -m alembic heads            -> 202609270044 (head)                 exit 0
python -m alembic upgrade head     -> 202609270042 -> 043 -> 044 均执行   exit 0
alembic_version = [('202609270044',)]
tables = 142
ai_skill_tables = ai_skill_definitions, ai_skill_release_events, ai_skill_scope_bindings,
                  ai_skill_test_cases, ai_skill_test_results, ai_skill_test_runs, ai_skill_versions
```

使用系统临时目录中的一次性 SQLite 文件，结束即删除（`temp_cleaned=True`）；**没有连接用户数据库、没有修改迁移链**。

## 完成的行为与文件

1. 只读核验源码与交接清单，未修改任何业务逻辑。
2. 新建 `backend\.venv`（Python 3.12.14）并按 `backend/requirements.txt` 安装依赖：`PIP_EXIT=0`。
3. 安装并锁定前端工具链：npm 10.9.9 + 现有 `package-lock.json`（lockfileVersion 2）。
4. `npm ci` 安装 418 个包，**`package-lock.json` SHA-256 前后一致**（未被改写）。
5. 运行 M0 指定后端测试组、前端类型检查、隔离生产构建、隔离浏览器验收。
6. 新增证据目录与文件（均不在交接清单内，属本次新增）：
   - `docs/evaluation/dsh-m0-20260930/`（venv-create.log、pip-install.log、npm-ci.log、pytest-group1/2.log + m0-group1/2.xml、tsc-noemit.log、next-build.log、next-build-browser.log、browser-cross-layer.log、acceptance-server.log、alembic.log、tsconfig 前后快照）
   - `docs/ux/acceptance/dsh-m0-cross-layer-browser-20260930/`（results.json + 2 张截图）
   - 本报告 `docs/handoff/dsh-M0-result.md`

**未提交、未推送、未部署、未操作生产库、未使用真实生产凭据。**

## 关键接口/契约变化

**无。** M0 不修改任何源码、schema、迁移、接口或前端组件。唯一的项目内文件写入是：

- 新增证据文件与报告；
- `frontend/tsconfig.json` 被 Next 构建自动加入临时 include，已按交接要求**逐字节还原**（见下）。

## 测试命令、退出码、日志路径、覆盖内容

工作目录 `backend`；环境：`DATABASE_URL=sqlite:///:memory:`、`ENVIRONMENT=development`、`TASK_QUEUE_PROVIDER=inline`、`LLM_PROVIDER=mock`、`EMBEDDING_PROVIDER=mock`、`VECTOR_STORE_PROVIDER=mock`；解释器 `.venv\Scripts\python.exe`。

| # | 命令 | 退出码 | 结果 | 日志/证据 |
| --- | --- | --- | --- | --- |
| 1 | `python -m pytest tests/test_field_candidate_vocabulary.py tests/test_ai_skill_field_candidates.py tests/test_ai_skill_candidate_preparation.py tests/test_retrieval_term_boundaries.py -q` | 0 | **58 passed** (7.79s) | `docs/evaluation/dsh-m0-20260930/pytest-group1.log`、`m0-group1.xml` |
| 2 | `python -m pytest tests/test_cross_layer_adoption_guards.py -q` | 0 | **12 passed** (5.28s) | `.../pytest-group2.log`、`m0-group2.xml` |
| 3 | `node node_modules/typescript/bin/tsc --noEmit` | 0 | 无错误（TypeScript 5.9.3） | `.../tsc-noemit.log` |
| 4 | `NEXT_DIST_DIR=.next-m0-build next build` | 0 | 生产构建成功，53/53 静态页，仅保留既有 Hook lint warnings | `.../next-build.log` |
| 5 | `node tests/ai-skill-cross-layer.browser.acceptance.mjs`（后端 `SKILL_ACCEPTANCE_CROSS_LAYER=1 acceptence_server 18427`） | 0 | **6 checks passed, errors=[]**，provider=mock，realModel=false | `.../browser-cross-layer.log`、`docs/ux/acceptance/dsh-m0-cross-layer-browser-20260930/results.json` |

第 1 组 58 passed 与第 2 组 12 passed 与交接提示词参考值一致；**两组存在重叠覆盖，不相加为“全项目用例数”**。

浏览器验收 6 项（与 `docs/ux/acceptance/ai-skill-cross-layer-browser-20260930-final/results.json` 同名同数）：
`source_to_mart_published_mock_generation_preserves_final_and_displays_provenance`、`source_to_mart_stale_displayed_draft_rejected_without_final_write`、`source_to_mart_explicit_adoption_and_existing_human_content_guard`、`mart_to_ybt_*` 同三项。

### 隔离构建与 tsconfig 还原

- 构建使用 `NEXT_DIST_DIR=.next-m0-build`（未覆盖 `.next`），构建后 Next 自动向 `frontend/tsconfig.json` 的 `include` 加入 `.next-m0-build/types/**/*.ts`。
- 已删除该行，并保留既有 `next-env.d.ts`、`**/*.ts`、`**/*.tsx`、`.next/types/**/*.ts`、`.next-dev/types/**/*.ts`。
- 校验：`tsconfig.json` 与构建前副本 **SHA-256 完全一致**（`tsconfig_restored_exactly=True`，含文件尾部 CRLF 逐字节还原）。浏览器构建产生的 `.next-ai-skill-b2-acceptance` include 同样已还原（`tsconfig_matches_prebuild=True`）。
- 两个临时构建目录（各约 197 MB / 数百 MB）已删除；`frontend` 下无残留 `.next*` 目录。

## 失败和未验证项

### 已定位并解决的真实失败（保留记录，未放宽任何门禁）

1. **npm 12.1.0 `EALLOWREMOTE`**：npm 12 拒绝按 lockfile `resolved` URL 抓取 “remote” 包（`zustand@https://registry.npmmirror.com/...`）。改用 npm 10.9.9（lockfileVersion 2 原生支持）后通过；未修改 lockfile。
2. **`npm ci` 生命周期脚本找不到 node**：`unrs-resolver` postinstall 以 `cmd /c node postinstall.js` 执行，而本机 node 不在 PATH，报 `'node' is not recognized`。将运行时 node 目录前置到本次进程 PATH 后通过（仅影响本次命令，未改系统 PATH）。
3. **部分 `node_modules` EPERM 清理失败**（`next/dist`、`tailwindcss`）：清理后重装，最终 `node_modules` 完整。
4. **PowerShell 内联 `python -c` 引号解析错误**：改为临时脚本文件执行，未影响结论。
5. **manifest 中文路径假缺失**：见上，编码问题，非数据问题。

### 未验证项（如实声明，不算通过）

- **PostgreSQL 未验证**：本机无 PostgreSQL/Docker 服务，未安装；迁移仅在 SQLite 上复跑。真实 PG 迁移、并发与约束行为仍未验。
- **真实模型未验证**：无授权凭据，未调用任何外部模型；全部为 Mock/确定性路径。真实模型生成质量、成本与延迟仍未验。
- **Git 状态未验证**：包内无 `.git`，无法复核 HEAD、工作区改动清单、未跟踪文件；只能引用清单声明值 `3e94e54`。
- **真实业务源库/生产环境未验证**：未连接任何用户数据源，未部署。
- **交接资料内的引用不一致**（记录差异，不以旧文档覆盖代码）：
  - `docs/handoff/DSH-Codex协作方案-20260930.md` 引用的 `environment-inventory-20260930.json` **不在交接包内**。
  - M0 提示词写的 `tests/ai-skill-cross-layer.browser.acceptance.mjs` 实际位于 **`frontend/tests/`**（后端 `tests/` 下无此文件）；`backend/tests/ai_skill_acceptance_server.py` 位置与提示词一致。
- **版本差异 WARN**：协作方案记录原机观察为 Node v24.15.0 / npm 8.6.0；本机为 Node v24.21.0 / npm 10.9.9（原机 npm 已不可得）。构建与类型检查均通过，但严格意义上不是同一工具链版本组合。
- **浏览器通道**：本机未安装 Playwright 自带 Chromium，验收脚本回退到其首选 `channel: "msedge"`（本机已装 Edge）。这与脚本设计路径一致，但与“Playwright Chromium”不是同一产物。

## 运行中服务/PID 与结束方式

- 结束时**无遗留服务**：`127.0.0.1:18427` 已确认关闭（`18427 closed`），无残留监听进程；DSH 后台作业 `pwsh-168`（我启动的验收服务）已停止。
- 未启动任何替代 Web 服务，未占用用户的 19387 GUI 端口。
- 所有 pytest、tsc、next build、npm、pip 进程均已退出。

## 代码审查风险与下一步

### 风险

- 本机 npm/node 版本与原机不一致，前端构建产物与依赖树“可重建但不完全同源”；后续前端证据应注明工具链版本（docs 已记录）。
- `.venv`、`node_modules`、依赖均为新装，未复用旧环境——这对“可复现”是优点，但任何依赖漂移会先体现在本机而非原机。
- 我无法用 Git 复核工作区，因此后续每个工作包都必须以“改动文件清单 + 逐文件 hash/差异”代替 `git diff` 作为交接证据。

### 下一步（按交接提示词）

M0 通过 → 进入 **B3-R1 受控候选模型重排**：

1. 先把具体接口方案写入本地设计文档（含公共契约变更清单），再实现；不重写治理框架。
2. 复核 `validate_rank_proposal` 现状：它只校验外部提案，**不代表已有真实模型重排**，本机复核确认其 `execution_kind` 恒为 `deterministic`、`ranking_mode="validated_proposal"`。
3. 实现后更新权威报告 `docs/handoff/ai-skill-center-implementation-report.md`，再推进查询改写/依赖式多跳与条款比较，随后 B4/B5/B6。
4. 仍然**不宣称第二部分全部完成**；PostgreSQL、真实模型质量与生产验收继续单列未通过。
