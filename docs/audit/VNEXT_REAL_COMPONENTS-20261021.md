# VNext 真实组件与真实模型验收（WSL / 公司 DeepSeek）

生成时间：2026-10-21 22:0x（Asia/Shanghai）
执行人：DSH Lead（本地实测，无公网 SaaS、无在线搜索）
目标：盘点 WSL 内真实可用组件，指出缺失；用公司 API 的 DeepSeek 配置做真实模型验证（不再考虑 Qwen）。
结论先行：**PostgreSQL / Redis / Milvus / Celery worker / Embedding（本机 fastembed 服务）/ 公司 DeepSeek 网关 = 真实可用（REAL）；知识上传→审核→生效→向量索引→混合检索闭环已在真实组件上跑通；Celery beat、前端容器、浏览器验收 = 未验证。** 真实模型引用判定在 10 条合成案例上 7/10 与期望一致，其余 3 条为裁判职责外的治理项（见 §4），不能据此声称真实业务准确率。更新（2026-10-21 23:5x）：用户 VPN 连通后经 hf-mirror 下载权重成功，embedding/Llama-server 阻断已解除，见 §9。

## 1. 组件清单（实测证据）

| 组件 | 状态 | 证据 |
| --- | --- | --- |
| Docker Engine（Ubuntu WSL2） | REAL | 29.6.2；8 vCPU / 7.7 GiB；`docker ps` 见下表 |
| PostgreSQL 16（compose `ybt-postgres`） | REAL | `postgres:16`，healthy，`127.0.0.1:5432`，库 `ybt_dsh_handoff_v2`，`alembic upgrade head` → 150 张表；冒烟 latency 862ms |
| PostgreSQL 16（`ybt-pg-host`） | REAL | `127.0.0.1:15432`，user `ybt`，本机通用宿主库 |
| Redis 7（compose `ybt-redis`） | REAL | `redis:7-alpine`，healthy，`127.0.0.1:6379`，AOF on；PING 与 SET/GET 往返 OK（321ms，空库 0 keys） |
| Milvus 2.5.4 standalone | REAL | `milvusdb/milvus:v2.5.4` healthy + etcd v3.5.18 + minio；`http://127.0.0.1:19530`；经 `app.services.vector.milvus.MilvusVectorStore` 建集合、512 维写入 3 条、search 命中、count=3、drop 全部成功；应用真实索引重建生成 `ybt_semantic_p1_v4_ec2e880fd3f8_d512` 并灌入 5 个知识单元 |
| 公司 LLM 网关（DeepSeek） | REAL | `backend/.env`：`LLM_PROVIDER=openai_compatible`、`LLM_BASE_URL=http://47.101.159.7:29988/v1`、`LLM_MODEL=deepseek-v4-flash`、key 已配置；字段重排 2.42s/375 tokens 判对；引用裁判 1.62s/230 tokens 判对；`/api/ai-runtime/status` 显示 `is_mock=false, configuration_status=configured` |
| 后端应用（当前源码） | REAL | 本机 uvicorn 8011，`.env` 真实配置启动成功，`/api/health` ok，`/api/ai-runtime/status` 返回非 mock 运行时；Milvus `reachable=true`；`TASK_QUEUE_PROVIDER=celery` 下任务经 Redis broker 真实投递并被 worker 执行 |
| 后端容器 `ybt-dev-app` | 旧镜像 | 运行中但镜像为 `ybt-backend:production-sync-20260909-verified2`，**不是当前源码**；8000 未发布到宿主 |
| Ollama（`ybt-ollama`，alpine/ollama:0.32.4） | 已停用 | 该镜像缺 `llama-server`（请求返回 `HTTP 500: error starting llama-server: llama-server binary not found`）；已 `docker stop ybt-ollama` 让出 11434 端口，改用 fastembed 服务（见下） |
| Embedding 服务（本机 fastembed，REAL） | REAL | `scripts/local_embedding_server.py`（FastAPI，OpenAI 兼容 `/v1/embeddings`，`BAAI/bge-small-zh-v1.5`，512 维）；权重经 `HF_ENDPOINT=https://hf-mirror.com` + `HF_HUB_DISABLE_XET=1` 下载成功；`/health` 返回 model/dimension，`/v1/embeddings` 单条/批量均 512 维；应用 `embed_documents` 4 条 999ms、`embed_query` 单条约 650ms |
| Celery worker（真实 Redis broker） | REAL | `celery -A app.workers.celery_app worker --pool=solo` 连 `redis://127.0.0.1:6379/0`，收到 `app.workers.execute_background_job` 任务，任务内真实调用 `http://127.0.0.1:11434/v1/embeddings 200 OK`，`succeeded in 16.0s/5.9s`；job 状态 queued→running→completed，`celery_task_id` 落库 |
| Celery beat | 未启动 | 定时任务（红线巡检/重投）未验证；不影响单次任务链路 |
| 知识语料与语义索引 | REAL | 项目 1 上传合成监管材料 → 解析 5 个知识单元 → 送审/审核/生效 → 重建索引 `document_count=1, chunk_count=5, indexed_count=5, valid=true` → 混合检索返回 5 条命中（含 `final_score/vector_score/keyword_score/authority_rank=6`） |
| 前端 | 未启动 | 3000 未监听；`ybt-frontend` 为 5 周前旧容器 Exited |

其它已确认：`jieba 0.42.1` 已装；`pymilvus 2.6.17` 与 2.5.4 服务端兼容（用 `MilvusClient` API）；`fastembed 0.8.0` 已装且权重已缓存（`HF_ENDPOINT=https://hf-mirror.com`、`HF_HUB_DISABLE_XET=1`）；`tiktoken` 未使用；仓库内没有任何 Qwen 部署配置（用户已明确本轮不考虑 Qwen）。网络实测：`huggingface.co`/`registry-1.docker.io`/`pypi.org` 直连超时或极慢，`hf-mirror.com`、`modelscope.cn` 可达——内网/受限网络下应配置 HF 镜像或离线导入权重。
注意：当前 WSL 同时存在两套依赖实例——`ybt-postgres`/`ybt-redis`（发布到宿主 5432/6379，应用 `.env` 指向的就是它们，库表与冒烟都在这套）与 `ybt-dev-pg`/`ybt-dev-redis`（compose 内部实例、未发布）。两套并存容易混淆，后续应保留一套并停掉另一套；本次未擅自删除运行中实例。

## 2. 本轮实际动作

1. 删除 5 周前另一工程的冲突容器 `ybt-redis`、`ybt-postgres`（数据卷保留），避免容器名冲突。
2. 在 WSL 的 `C:\Users\李儒伟\Documents\智能分析智能体平台` 用显式项目名启动 compose：`docker compose -p ybt-dev --profile milvus up -d postgres redis etcd milvus-minio milvus`（中文目录导致 compose 默认项目名为空，必须 `-p`）。
3. 在 compose PG 内创建应用角色/库 `ybt_dsh_handoff_v2`，执行 `alembic upgrade head`（150 张表，revision 到 `202611010001`）。
4. 启动 `alpine/ollama:0.32.4` 并拉取 `BAAI/bge-small-zh-v1.5` → 发现镜像缺 `llama-server`，embedding BLOCKED。
5. 以真实 `.env` 启动当前源码后端（`uvicorn app.main:app --port 8011`），确认 PostgreSQL/Milvus/LLM 三项真实可用。
6. 新增并运行两个真实冒烟脚本（见 §5），结果写入 `docs/audit/VNEXT_REAL_COMPONENT_SMOKE-20261021.json` 与 `docs/audit/VNEXT_REAL_MODEL_GOLDEN-20261021.json`。
7. 修复引用裁判证据投影缺陷（见 §3），补 2 条回归测试（`tests/test_rag_citation_support.py`，14 passed）。
8. 用户 VPN 连通后（m01449「你现在尝试一下下载，我VPN应该已经连接网了」）：`HF_ENDPOINT=https://hf-mirror.com HF_HUB_DISABLE_XET=1` 下载 `BAAI/bge-small-zh-v1.5` 权重成功（653s），`docker stop ybt-ollama` 让出 11434，改由 `scripts/local_embedding_server.py` 提供 OpenAI 兼容 embedding（512 维实测）。
9. 真实语义检索冒烟：`scripts/vnext_semantic_smoke.py`（应用 embedding + Milvus）4 文档 / 3 中文查询 **Top1 3/3、Top3 3/3**（客户标识 0.7566、借据号 0.6663、统计日期 0.7151），随机向量对照仅 1 命中，证明不是「凡查必中」。
10. 真实知识闭环：`scripts/vnext_knowledge_smoke.py` 走 API（登录→上传→送审→审核→生效→重建索引→混合检索），并新增 `scripts/vnext_seed_smoke_user.py` 预置登录用户（真实 argon2 哈希）与项目成员关系；发现 optional 匿名模式下 `background_jobs.created_by=0` 违反外键（见 §10）。
11. 真实 Celery 队列：`TASK_QUEUE_PROVIDER=celery` 重启 API + `celery -A app.workers.celery_app worker --pool=solo`；`scripts/vnext_celery_smoke.py` 记录 queued→running→completed、worker 侧真实调用 embedding 服务、索引集合升级到 `_v4`。

## 3. 引用裁判的真实缺陷与修复

**缺陷（可复现）**：`app/services/rag/citation_support.py::citation_evidence` 只把 `citation_id/label/quoted_content` 交给裁判，**丢掉了来源名、条款位置、版本、生效日期**。后果：裁判无法识别「培训 PPT 转述」与正式条款、无法发现版本/时点不一致——正是任务书 1.4 要求的「证据版本须与适用时点相符、无证据保留待确认」。

**修复**：
- `citation_evidence` 透传白名单 `source_name/title/location_text/locator/version/effective_date/published_at`，长度上限 `MAX_PROVENANCE_CHARS=200`，空白值不传；
- `CITATION_SUPPORT_SYSTEM_PROMPT` 增加判定规则：非正式原文（培训/二手/转述）→ unknown；版本、生效日期、适用范围不一致 → unsupported；只覆盖部分条件 → unsupported；表内/表外等口径扩大 → unsupported。

**效果（真实 DeepSeek，10 条合成 C 族案例）**：修复前 6/10 一致（C07 二手摘要被判 supported），修复后 **7/10**（C07 正确判 unknown）；C01–C07 全对。平均 2.39s/例，0 降级。
**未闭合的 3 条**（裁判职责之外，属下一工作包）：
- C08 多条件只引一条：新规则 3 使其判 unsupported，而黄金集期望（单条引用层面）为 supported——属黄金集期望与产品策略的口径差，需人工定口径；
- C09 两份高权威制度冲突：需要管线层冲突检测（`_evidence_conflicts` / 召回冲突集）显式把冲突证据交给裁判，裁判本身只做蕴含判断；
- C10 快照 v1 vs 导出引用 v2 不一致：需要把快照版本号/文档版本随引用一起传入（当前 `document_version_id` 有值但版本号/生效日不在投影里）。

## 4. 真实模型验证结果（可复核）

- `/api/ai-runtime/status`：`llm.provider=openai_compatible, model=deepseek-v4-flash, is_mock=false`；`vector_store.provider=milvus, reachable=true`；`embedding.configuration_status=configured` 但服务端 500（BLOCKED）。
- 字段重排冒烟（真实 rerank prompt，客户统一标识案例）：SRC1 判 0.99 排第一，理由「客户主键，全行唯一」，SRC2/3 判低分理由正确；2.42s、375 tokens。
- 引用裁判冒烟：正确判 unsupported（证据只说客户粒度、结论按产品粒度）。
- 引用黄金集真实评测：7/10 与期望一致（详见 §3 与 JSON）。
- 真实业务准确率：**UNVERIFIED**（黄金集标签无独立银行专家确认；10 条均为 Lead 转写输入）。

## 5. 复现命令

```powershell
# 组件冒烟（真实 PG/Redis/Milvus/公司 DeepSeek）
cd backend
$env:PYTHONIOENCODING='utf-8'
.\.venv\Scripts\python.exe ..\scripts\vnext_real_component_smoke.py --output ..\docs\audit\VNEXT_REAL_COMPONENT_SMOKE-20261021.json

# 真实模型 + 黄金集 C 族
$env:CITATION_SUPPORT_CHECK='judge'; $env:RAGAS_JUDGE_ENABLED='true'
.\.venv\Scripts\python.exe ..\scripts\vnext_real_model_golden_eval.py --output ..\docs\audit\VNEXT_REAL_MODEL_GOLDEN-20261021.json

# 以真实组件启动当前源码后端
cd backend
$env:AUTH_MODE='optional'; $env:PYTHONIOENCODING='utf-8'
$env:STORAGE_DIR=(Resolve-Path .\dev_storage_local).Path
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8011
```

## 6. 当时缺口与当前状态（2026-10-21 23:5x 更新）

1. **Embedding（原 P0 阻塞）→ 已解除**：走了第三条路（fastembed 进程内 + HF 镜像权重），由 `scripts/local_embedding_server.py` 在同一 11434 端口提供 OpenAI 兼容接口；`/health` 返回 `dimension=512`，应用 `embed_documents`/`embed_query` 真实调用成功。**生产建议仍按内网要求改为公司内部 `/v1/embeddings` 或离线权重目录，不要把 HF 镜像下载当作部署方案。**
2. **Celery worker（原 P1）→ 已验证**：本机 solo worker 连 Redis 完成真实任务；**beat 未启动**，重投/定时巡检、Worker 崩溃恢复、租约过期仍需专项验收。
3. **Milvus 灌库（原 P1）→ 已完成**：真实知识单元 5 个入索引，集合名含指纹与维度（`ybt_semantic_p1_v4_ec2e880fd3f8_d512`），`validation.valid=true`；重启恢复与删除同步未测。
4. **前端（P1）**：仍未启动/未点检，浏览器关键操作 UNVERIFIED。
5. **裁判上下文（P1）**：C09/C10 类缺口仍需把版本号/生效日/冲突证据传入 `check_citation_support`；C08 需人工定口径。
6. **optional 模式背景任务外键**（见 §10.1）与 **混合检索分数饱和导致 Top1 并列**（见 §10.2）为本轮新发现缺陷；**2026-10-22 已修复并带回归测试与真实证据，见 §11.1 / §11.2**。

## 7. 未验证 / 保留声明

- 真实业务准确率、独立人工标注：UNVERIFIED（0 名独立银行专家标注；本轮知识材料为 Lead 编写的合成测试规范，明确标注「非真实监管文件」）。
- Celery 队列**异常语义**（重复投递幂等、Worker 崩溃恢复、租约过期、迟到返回不覆盖）：**2026-10-22 已真实测，见 §11.3（4/4）**；worker/beat 无 restart policy 仍属运维注意事项。
- 前端真机操作：**2026-10-22 已真实浏览器点检 5/5，见 §11.4**；生成/重试等长链路交互仍未点检。
- Milvus 检索**质量**：仅 3 条自造查询、4 条自造文档（Top1 3/3），样本量不足以支撑业务准确性结论；重启恢复、删除同步未测。
- 混合检索排序：`final_score` 饱和缺陷已于 §11.2 修复（排序改用未截断分数），真实查询 Top1 已验证；更大规模排序质量仍待评估。
- 公司 DeepSeek 网关为开发/验证用；生产主模型按任务书仍是项目既定内网模型，本次不改变生产配置；用户已明确本轮不考虑 Qwen。

## 8. 运行方式与重启注意事项（实测踩坑）

启动（WSL 内；目录含中文，必须显式 `-p`）：

```bash
cd /mnt/c/Users/李儒伟/Documents/智能分析智能体平台
docker compose -p ybt-dev --profile milvus -f docker-compose.yml -f docker-compose.dev-ports.yml up -d postgres redis milvus
```

- **WSL 会空闲回收**：本机 `.wslconfig` 为 `networkingMode=mirrored`。没有任何 WSL 进程时发行版停止，Windows 侧 `127.0.0.1:5432/6379/19530/11434` 立即变成「积极拒绝」；下次执行 `wsl` 命令时容器才重新拉起（`docker ps` 显示 Up 几秒）。**必须保持一个常驻 WSL 进程**（例如计划任务运行 `wsl -d Ubuntu -- bash -lc "sleep infinity"`），否则 uvicorn、浏览器验收会间歇性连不上。
- 数据重启后仍在（`ybt-dev_postgres_data`/`ybt-dev_redis_data` 命名卷）：PG 150 张表、Redis AOF 均可恢复；但 Milvus 栈（etcd/minio/milvus）**没有 restart policy**，docker 重启后需手动 `compose up -d milvus`（实测重启后三容器 Exited，手动拉起后 healthy）。
- 重启后复测证据：`docs/audit/VNEXT_REAL_COMPONENT_SMOKE-20261021-after-restart.json`——postgres real（150 表/1.06s）、redis real（0.44s）、milvus real（512 维/3 条/2 命中/7.2s）、embeddings 仍 BLOCKED（缺 llama-server）。
- 真实后端（uvicorn，真实 `.env`）已验证 `/api/health` OK、`/api/ai-runtime/status` `is_mock=false`、Milvus `reachable=true`、语义索引 `available=false`（该次会话早于 embedding 可用；23:4x 后同一接口为 `semantic_index.state=ready, active_index_count=1`，见 §9）。

## 9. 真实 embedding / 语义检索 / 知识闭环 / Celery（2026-10-21 23:3x–23:4x 实测）

证据文件：
- `docs/audit/VNEXT_REAL_SEMANTIC_SMOKE-20261021.json`（embedding + Milvus 直接链路）
- `docs/audit/VNEXT_REAL_KNOWLEDGE_SMOKE-20261021.json`（API 全链路）
- `docs/audit/VNEXT_REAL_CELERY_QUEUE-20261021.json`（真实队列）

1. **Embedding 服务**：`PYTHONIOENCODING=utf-8 .\.venv\Scripts\python.exe ..\scripts\local_embedding_server.py --port 11434`；`GET /health` → `{"status":"ok","model":"BAAI/bge-small-zh-v1.5","dimension":512}`；服务端以 numpy float32 列表序列化（早期 `list(float32)` 非 JSON 可序列化导致 500，已修）。
2. **语义检索（应用自身代码路径）**：4 条字段文档（客户标识/产品编号/借据号/统计日期）+ 3 条中文查询，`embed_documents` 512 维/999ms，Milvus upsert 4 条/1053ms，检索 Top1=3/3、Top3=3/3，单查询约 650ms；随机向量对照只命中 1/1（说明必须比语义，而不能只看「有命中」）。
3. **知识闭环（HTTP API）**：`scripts/vnext_seed_smoke_user.py` 建真实登录用户并绑定项目成员 → `scripts/vnext_knowledge_smoke.py`：login → `POST /api/projects/1/knowledge/documents/upload`（真实 multipart，解析出 5 个知识单元，`parse_status=parsed`）→ `submit-review` → `review` → `activate` → `POST /api/projects/1/semantic-index/reindex {force:true}` → `GET semantic-index/status` 返回 `mode=formal, document_count=1, chunk_count=5, active_index_current=true, milvus_health.healthy=true` → `POST /api/projects/1/knowledge/hybrid-search` 返回 5 条，字段含 `final_score/vector_score/keyword_score/authority_rank=6/lifecycle_status=active`。
4. **Celery（真实 Redis broker）**：API 以 `TASK_QUEUE_PROVIDER=celery` 启动，worker 用 `--pool=solo`；任务 `app.workers.execute_background_job` 由 worker 接收（`celery_task_id=4c261c01-…`、`d96821b1-…`），worker 日志出现 `POST http://127.0.0.1:11434/v1/embeddings "HTTP/1.1 200 OK"` 与 `succeeded in 16.0s / 5.922s`；job 状态 `queued→running→completed`，`result_summary_json` 含 `indexed_count=5, collection=ybt_semantic_p1_v4_…`。
5. **复现命令补充**：

```powershell
# 1) embedding 服务（后台常驻，占 11434）
$env:HF_ENDPOINT='https://hf-mirror.com'; $env:HF_HUB_DISABLE_XET='1'
.\.venv\Scripts\python.exe ..\scripts\local_embedding_server.py --port 11434

# 2) 预置登录用户（写真实 PG，仅隔离冒烟库）
.\.venv\Scripts\python.exe ..\scripts\vnext_seed_smoke_user.py

# 3) 语义检索直接链路 / API 闭环 / Celery 队列
.\.venv\Scripts\python.exe ..\scripts\vnext_semantic_smoke.py --output ..\docs\audit\VNEXT_REAL_SEMANTIC_SMOKE-20261021.json
.\.venv\Scripts\python.exe ..\scripts\vnext_knowledge_smoke.py
.\.venv\Scripts\python.exe ..\scripts\vnext_celery_smoke.py   # 需 API=TASK_QUEUE_PROVIDER=celery + worker 在跑
```

## 10. 本轮新发现的产品缺陷（未擅自修改业务代码，留证据与最小修复建议）

### 10.1 optional 认证模式下背景任务写入 `created_by=0` 违反外键（真实可复现）

- 现象：`AUTH_MODE=optional`（非生产）时匿名上传知识文档触发 `POST /api/projects/1/knowledge/documents/upload` → 500；PostgreSQL 报 `background_jobs_created_by_fkey` 冲突。
- 根因：`app/services/auth/dependencies.py:31-33` 匿名 principal 为 `Principal(None, "legacy-system", …)`；`app/services/task_queue/…`/`submit_project_job` 把 `principal.user_id` 直接写入 `background_jobs.created_by`（None→0），而 `users.id` 无 0。
- 影响：仅 optional/legacy 模式；生产 `AUTH_MODE=required` 不受影响（本次用真实登录用户验证通过）。但开发/演示环境会把「首次上传」变成 500，属可复现真实缺陷。
- 最小修复：`created_by` 允许为空（迁移）或写 NULL 而非 0；或在 optional 模式下用系统用户占位（需产品口径）。本轮未改源码，避免触碰历史迁移。

### 10.2 混合检索 `final_score` 饱和为 1.0 → Top1 退化到 unit id 兜底（真实可复现）

- 现象：查询「报送数据按哪天取数」时，`## 2 客户统一标识`（vector 0.3831/keyword 0.0524）与 `## 3 报送日期口径`（vector 1.0/keyword 1.0）返回的 `final_score` 都是 `1.0`，排序按 `-knowledge_unit_id` 兜底，导致语义更相关的「报送日期」排第二。
- 根因：`app/services/retrieval/hybrid_retriever.py:306` 为 `min(1.0, fused + rule_boost)`；`_normalize_scores`（:387-397）把 min-max 结果压到 0.01–1.0，`fused=1.0` 再加 0.05 被截断，多个高分单元并列；:343-347 排序键 `(authority_rank, final_score, -knowledge_unit_id)` 无二级语义信号。
- 影响：权威等级相同（同为当前生效监管资料）时 Top1 可能不稳定/错误；RAG 引用与字段召回都受影响。属「可复现排序缺陷」，不是测试环境问题。
- 最小修复建议：排序用未截断的 `fused`（或加 `boosted` 前值）作第二键；`final_score` 仅作展示或按 `fused/(1+boost)` 归一；补「同权威等级、两候选分数并列时按 fused 排序」的回归测试。**未在本次改动**，避免未经真实评测调整排序。

## 11. 缺陷修复与补充真实验收（2026-10-22 00:0x–00:4x，用户口径 m01788）

证据 JSON：`docs/audit/VNEXT_DEFECT_FIXES-20261022.json`、`docs/audit/VNEXT_CELERY_RECOVERY-20261022.json`、`docs/audit/VNEXT_WORKSPACE_BROWSER-20261022.json`（+ 截图 `VNEXT_WORKSPACE_BROWSER-20261022.png`）。本节覆盖 §6/§7/§10 中已解除的项；未被本节提及的 UNVERIFIED 结论保持不变。

### 11.1 缺陷 §10.1 修复：optional 模式匿名任务不再违反 `background_jobs_created_by_fkey`

- 根因确认：任务投递把 `int(principal.user_id or 0)` 写入 `background_jobs.created_by`（`NOT NULL` FK → `users.id`）；匿名 legacy principal 的 `user_id=None` → 0 → 外键冲突 → 请求 500。
- 修复（新增 1 文件 + 改 2 文件）：
  - 新增 `backend/app/services/auth/actors.py`：`ensure_actor_user_id(db, actor_user_id)` 在缺省 actor 时物化一次性系统用户 `username='legacy-system'`（`status='active'`）并复用；有真实 user_id 时原样返回，因此生产 `AUTH_MODE=required` 行为不变。
  - `backend/app/services/task_queue/idempotency.py:101`：`created_by=ensure_actor_user_id(db, created_by or None)`。
  - `backend/app/services/lineage/ingestion.py`：改用同一解析器，避免第二处写 0。
- 回归：新增 `backend/tests/test_task_queue_legacy_actor.py`（2 条）。**改前可复现失败**：`sqlalchemy.exc.IntegrityError: (sqlite3.IntegrityError) FOREIGN KEY constraint failed`（INSERT `background_jobs` … `created_by` 0）；改后 `task_queue_legacy_actor + job_attempt_fencing + knowledge_reindex` **24 passed / 168.33s**。
- 真实 PG 证明（服务层，非 mock）：在 compose PostgreSQL（150 表）上用 `Principal(None, "legacy-system", …)` 投递任务，INSERT 成功且 `created_by=2`、`users.username='legacy-system'`（`fk_ok=true`；探针 handler 为占位 lambda 故该行状态 failed，与缺陷无关，行已清理）。
- 标签：**FIX + TESTED_REAL（服务层真实库）**；`AUTH_MODE=required` 生产路径未改变（匿名仍 401）。

### 11.2 缺陷 §10.2 修复：混合检索分数饱和不再让 Top1 退化为 unit id 兜底

- 根因确认：`backend/app/services/retrieval/hybrid_retriever.py:305-306` `final_score = min(1.0, fused + 0.05)`，而 :343-347 排序键 `(authority_rank, final_score, -knowledge_unit_id)`；多个候选 fused 接近 1.0 时并列，排序退化为 id 升序。
- 修复：排序第二键改用**未截断**的 `fused + rule_boost`（`ranking_by_id`），`final_score` 仍按原口径截断用于展示/兼容响应契约；不改变返回字段与历史 API。
- 回归：新增 `backend/tests/test_hybrid_score_saturation.py`（3 条：同权威等级并列、规则加分、仅向量命中），`hybrid + fusion + reranker` **31 passed / 13.20s**。
- 真实**改后**结果（真实 Milvus 集合 `ybt_semantic_p1_v4_…_d512`，5 个知识单元，HTTP `POST /api/projects/1/knowledge/hybrid-search`）：
  - 查询「报送数据按哪天取数」→ Top1 = unit 9「## 3 报送日期口径」（`final_score=1.0`，vector/keyword 均 1.0）；**改前**同一查询 Top1 是 unit 8「## 2 客户统一标识」（vector 0.3831/keyword 0.0524），日期口径被压到 #2。
- 标签：**FIX + TESTED_REAL（HTTP API + 真实向量库）**。注意：`final_score` 仍可能显示 1.0（展示口径未变），判断排序正确性请看返回顺序而非仅仅该字段。

### 11.3 Celery 异常语义真实验收（原 §7 UNVERIFIED → 已测）

证据：`docs/audit/VNEXT_CELERY_RECOVERY-20261022.json`（4/4 pass），环境为真实 PostgreSQL + Redis broker + Celery worker(solo)/beat + 本地 embedding。

| 检查 | 实测结果 |
| --- | --- |
| 重复投递幂等 | 同一 `idempotency_key` 两次提交返回**同一 job id**，`deduplicated=true`，该键只有 1 行；索引版本增量 1；消息重放后 0 增量、`finished_at` 不变 |
| Worker 崩溃恢复 | 真实 kill 运行中的 worker 后 job 停在 `running`（`lease_owner` 保留），**没有自动恢复**；手工触发 redispatch 扫描 → `stale_running_published=[12]` → 重新投递后最终 `completed`，增量 1 |
| 迟到返回不覆盖 | 接管后结果为 `{"attempt":"B"}`；旧 attempt 的迟到写入被 fencing 拒绝，最终仍为 B（`late_writer_blocked=true`） |
| beat 定时扫描 | beat 日志出现 `Scheduler: Sending due task redispatch-undelivered-jobs`，任务真实进入队列 |

- 代码改动：`backend/app/services/task_queue/celery.py::dispatch_undelivered` 增加「运行中但租约已过期 / 长时间未被重新投递」的 stale-running 重投，报告字段 `stale_running_candidates / stale_running_published`（原逻辑只扫 queued）；新增用例 `test_dispatch_undelivered_republishes_a_crashed_running_job`，`test_job_attempt_fencing.py` **19 passed / 171.66s**。
- 仍需注意（保留 UNVERIFIED/运维项）：worker/beat 容器**没有自动 restart policy**（本机 compose 实测），崩溃后需人工拉起；「真实 kill 后无自动恢复、依赖扫描重投」是当前设计，不是立即自愈。

### 11.4 前端真实页面点检（原 §7 UNVERIFIED → 已测）

证据：`docs/audit/VNEXT_WORKSPACE_BROWSER-20261022.json` + 整页截图 `VNEXT_WORKSPACE_BROWSER-20261022.png`。环境：`next dev`（真实 3000 端口）+ 当前源码后端 8011 + 真实 PG 种子数据（`scripts/vnext_seed_workspace_fixture.py`：项目 1、机构 VNEXT-SYNTH、一表通客户信息表 `EAST_YBT_CUSTOMER`、字段 `CUSTOMER_ID`/`PRODUCT_ID`、需求「根据借据信息取得产品信息（VNext 真实页面点检）」）。脚本：`scripts/vnext_workspace_browser_smoke.mjs`（Playwright chromium）。

| 检查 | 结果 |
| --- | --- |
| 登录页真实登录 | pass（`input[name=username]/password` + submit → 跳转工作区） |
| 工作区列出预置需求 | pass（需求下拉从后端加载到「…（VNext 真实页面点检）· v1」） |
| 需求文档渲染 | pass（5 个 Tab：结构化口径/血缘/证据/待确认/文档预览，字段范围与版本可见） |
| Tab 逐一切换 | pass（5/5 内容区切换正常） |
| 控制台/接口洁净 | pass（无 JS 异常；仅 4 条来自非管理员访问 `/api/admin/*` 的 403，属 RBAC 预期） |

- 仍未验证（诚实保留）：需求生成/重试/候选采用等需要真实模型长链路的交互（本节点检只读渲染 + 导航）；跨浏览器（仅 chromium）；移动端（任务书明确不需要）。

### 11.5 全量回归（最终门禁）

`backend` 全量 pytest：**1910 passed, 1 skipped, 0 failed / 3971.16s**（2026-10-22 03:2x，退出码 0），原始输出 `docs/audit/pytest-full-20261022.log`。中途一次失败为改 `.gitignore` 引入 BOM 的自伤，已修复并全量重跑通过（详见验收报告 §H6）。
