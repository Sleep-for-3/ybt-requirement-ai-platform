# AI P0 可信性与安全修复交付报告

- 目标契约：`docs/upgrade/P0-AI可信性与安全-GOAL提示词.md`
- 当前状态：verified（确定性、Mock 与真实 API 传输路径已验证；未声明真实模型验收通过）
- 开始日期：2026-09-20
- 执行约束：保留现有未提交修改；单代理、单上下文、串行工具调用；不提交、不推送、不部署

## 1. P0 总表

| 项目 | 状态 | 当前结论 | 下一步证据 |
| --- | --- | --- | --- |
| P0-1 AI 接口权限与租户隔离 | verified | Prompt、评测、运行、结果、反馈接口已显式认证并校验项目权限；创建人和机构由服务端派生 | 目标测试与知识/RAG、发布加固回归均通过 |
| P0-2 Mock/真实模型/规则结果混淆 | verified | 已统一 `real_model`、`mock_model`、`deterministic`、`degraded` 运行语义并接入模型调用与主要页面标签；Mock 血缘解释已修复为符合当前 Schema 的固定输出 | 后端、前端、Mock 浏览器与真实 API 传输浏览器验收通过 |
| P0-3 Prompt 版本配置错误承诺 | verified | Prompt 页面改为明确的只读视图，`GET /prompt-versions` 返回 `runtime_binding`，不再承诺编辑、测试、发布和回滚 | 真实 API 浏览器页面显示“只读、尚未渲染”，且无编辑/测试/发布/回滚按钮 |
| P0-4 伪 AI 标签 | verified | 主要业务语义改为候选建议，血缘与解释区展示 Mock、真实模型、确定性规则、降级和上下文完整性 | 156 项前端测试、类型检查和真实 API 浏览器截图通过 |
| P0-5 静默截断和证据丢失 | verified | 上下文投影记录预算、缺口和截断原因；超限在调用模型前阻断；引用按固定 `selected_fact_refs` 白名单校验并持久化拒绝声明；降级态也显示上下文完整性 | 定向测试与 Mock/真实 API 浏览器路径通过 |
| P0-6 AI 反馈与评测闭环 | verified | 反馈从关联运行记录服务端派生执行类型、输出哈希和证据，可幂等转为 `feedback_regression` 评测样例 | 真实 API 浏览器重复执行转换仍成功，反馈与回归样例均保留 |

### 迁移门禁

| 项目 | 状态 | 结论 |
| --- | --- | --- |
| `202609200040`、`202609200041` 空库迁移 | verified | 迁移已改为检测缺失列、索引和外键后再新增；SQLite 隔离空库完成 `upgrade head -> downgrade -1 -> upgrade head -> current` |
| PostgreSQL 迁移 | verified | 任务专用 PostgreSQL 16 容器通过 `upgrade head -> downgrade -1 -> upgrade head -> current`；容器已停止并删除，未复用用户容器 |

## 2. 现有能力核验

### 已有

- 模型 Profile、Prompt 版本、模型调用日志和基础 Mock/真实 Provider 抽象存在。
- RAG 评测案例、运行、结果、引用覆盖和反馈模型存在。
- 血缘解释已经采用事实优先、引用校验、模型失败降级的产品语义。
- 需求候选和 Mapping 生成已有确定性规则、人工内容保护以及审核链路。

### 部分具备

- `ModelCallLog` 能记录 Provider、模型、Prompt key/version，但缺少统一 `execution_kind`、上下文完整性和输出哈希字段。
- `AIUserFeedback` 能记录项目与用户，但缺少 institution、运行 ID、输出哈希和执行类型。
- Mapping 上下文会标记截断，但生成入口尚未在截断时阻止“完整草稿”语义。
- Prompt 版本参与 system prompt，但 user template 未被统一编译。

### 缺失或需修复

- `GET /prompt-versions`、评测案例创建/查询、评测运行/结果查询、反馈接口缺少统一的显式主体校验与项目边界断言。
- 页面没有统一区分真实模型、Mock、规则算法和模型降级。
- `ai_suggested` 等历史状态可能被误解为真实 AI 输出，缺少来源说明。
- 模型 citations、拒绝声明和上下文截断没有统一持久化。
- 反馈尚未进入可复用的回归闭环。

## 3. 修改文件与证据

本节按阶段持续追加。

### P0-1

- `backend/app/api/knowledge_rag.py`：为 Prompt 版本、评测案例、评测运行/结果、反馈接口增加 `CurrentPrincipal`、`PermissionService` 和跨项目资源校验；反馈关联模型调用时校验其项目归属。
- `backend/app/models/entities.py`：新增向后兼容的机构、创建人、运行关联、输出哈希、执行类型、上下文和证据 JSON 字段。
- `backend/alembic/versions/202609200040_ai_trust_execution_metadata.py`：新增可空增量迁移，不修改旧数据。
- `backend/tests/test_ai_p0_security.py`：覆盖未登录、平台管理员、本机构授权、跨项目拒绝、创建人/机构派生与反馈运行归属。

关键安全语义：

- `GET /prompt-versions` 仅平台管理员可读。
- 评测案例创建/运行需要 `knowledge.manage`，读取需要项目可见权限。
- 反馈需要 `knowledge.manage`，且 `model_call_log_id` 必须属于当前项目。
- 旧接口路径与响应字段保持兼容；新增字段均可空。

### P0-2 至 P0-6

- `backend/app/services/llm/execution_metadata.py`：统一运行类型、上下文完整性、输出哈希和执行元数据。
- `backend/app/services/mapping/context_adapters.py`、`generator_context.py` 及各生成器：生成预算、缺口、事实选取和超预算阻断。
- `backend/app/services/llm/prompt_runtime.py`、`backend/app/api/*.py`：持久化执行元数据、引用、拒绝声明，并在 409 中返回预算和缺口。
- `backend/app/api/knowledge_rag.py`：补齐反馈查询、反馈到评测样例的幂等转换，以及运行记录归属校验。
- `backend/app/models/entities.py` 与 `202609200040/041`：以可空字段增量记录 Skill、Prompt、上下文、引用、执行类型和反馈回归关联。
- `frontend/app/prompt-versions/page.tsx`：明确只读语义，不再展示不存在的编辑/发布操作。
- `frontend/lib/ai-execution-label.mjs`、`lineage-explanation.mjs` 及相关页面：统一显示真实模型、Mock、确定性规则、降级和上下文完整性。
- `frontend/app/evaluations/page.tsx`：提供反馈列表和“转为评测样例”入口。
- `backend/app/services/llm/mock.py`：血缘解释不再依赖可编辑 Prompt 文案识别任务，改为识别结构化 `relation/facts` 输入，避免改写 Prompt 后天然降级。
- `frontend/components/TableFieldGraph.tsx`：模型降级时仍展示上下文完整性、降级说明和保留的确定性事实。
- `frontend/tests/ai-p0.browser.acceptance.mjs`：支持 Mock 路由验收与真实 API 传输验收，校验只读 Prompt、执行标签、上下文预算、制度缺口和反馈转回归。
- `backend/tests/ai_p0_acceptance_server.py`：使用任务临时文件 SQLite 隔离数据库，避免并发请求争用单连接；强制 Mock Provider，退出时删除临时库。

## 4. 测试与验收

本节按阶段持续追加实际命令、结果、失败摘要和环境隔离说明。

- `python -m pytest tests/test_ai_p0_security.py tests/test_ai_execution_metadata.py tests/test_generator_context_adapters.py tests/test_llm_gateway.py tests/test_lineage_edge_explanation.py -q`：34 passed（26.37s）。
- `python -m pytest tests/test_double_layer_mapping.py tests/test_scenario_traceability.py tests/test_knowledge_rag.py tests/test_release_hardening.py -q`：72 passed（910.93s）。
- SQLite 隔离空库：`upgrade head -> downgrade -1 -> upgrade head -> current` 通过，当前 head 为 `202609200041`。
- PostgreSQL 16 隔离容器：`upgrade head -> downgrade -1 -> upgrade head -> current` 通过，当前 head 为 `202609200041`；任务容器已停止并自动删除。
- 前端 `npm test`：156 passed。
- 前端 `npx tsc --noEmit`：通过。
- 隔离生产构建 `NEXT_DIST_DIR=.next-p0-ai-isolated npm run build`：通过；构建目录已清理，`tsconfig.json` 的临时 include 已恢复。
- 回归中曾有 13 项失败，原因是误把 `AUTH_MODE=required` 用在旧默认认证测试集；移除该误设后同一批 72 项全部通过，不是业务回归。
- 测试使用隔离 SQLite、隔离测试账号和隔离目录，未连接生产或本地现有数据库。

## 5. 浏览器验收

已完成两条浏览器验收路径，均使用隔离前后端、真实生产构建和隔离测试数据；没有连接生产环境，没有使用真实银行数据。

### 5.1 真实 API 传输 + Mock Provider

- 时间：`2026-09-20T11:39:12Z`
- 传输：页面通过真实 HTTP 访问隔离 FastAPI，`apiTransport=real`
- 模型声明：`realModel=false`，Provider 强制为 Mock
- 结果：`passed=true`，`pageErrors=[]`
- 已核验：Prompt 只读、Mock 流程、缺少制度依据、上下文完整性、反馈转评测样例
- 截图：`docs/ux/acceptance/ai-p0-browser-real-api-20260920-v2/`

### 5.2 Playwright 路由 Mock

- 时间：`2026-09-20T11:39:26Z`
- 传输：`apiTransport=mock`
- 模型声明：`realModel=false`
- 结果：`passed=true`，`pageErrors=[]`
- 已核验：结构化 409 阻断、预算与缺口、Mock 流程、缺少制度依据、上下文截断、反馈转评测样例
- 截图：`docs/ux/acceptance/ai-p0-browser-20260920/`

浏览器验收中曾发现并修复两个问题：Prompt 文案变化导致 Mock 血缘输出命中旧 Schema；模型降级时页面未显示上下文完整性。两者均已通过新增测试和再次浏览器验收确认。

## 6. 已验证、未验证与遗留

- 已验证：P0-1 至 P0-6；定向测试、相关后端回归、前端测试、类型检查、隔离生产构建、SQLite/PostgreSQL 隔离迁移，以及 Mock 路由和真实 API 传输浏览器验收。
- 未验证：真实模型 Provider 端到端。本轮没有可用的真实模型凭据，也未将 Mock 结果描述为真实模型效果。
- 遗留：真实模型上线后仍需用同一验收脚本切换 Provider 做一次真实模型抽样，并单独记录延迟、成本、引用和失败行为。

## 7. 服务与版本声明

- 本任务仅启动并在验收后停止隔离 FastAPI 服务 `127.0.0.1:8000`；停止后复查 8000 无监听进程。
- 未启动、停止或修改用户现有服务；未覆盖用户 `.next`，构建使用 `.next-ai-p0-acceptance`。
- `.next-ai-p0-acceptance` 的递归清理命令被运行策略拦截，目录仍作为未跟踪构建产物留在工作区；没有执行绕过策略的删除。正式提交前应在获得允许后用任务专用命令清理。
- 未提交、未推送、未部署。
- 未读取或输出任何凭据，未修改账号密码。
