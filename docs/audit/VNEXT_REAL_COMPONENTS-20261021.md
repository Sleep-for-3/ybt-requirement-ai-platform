# VNext 真实组件与真实模型验收（WSL / 公司 DeepSeek）

生成时间：2026-10-21 22:0x（Asia/Shanghai）
执行人：DSH Lead（本地实测，无公网 SaaS、无在线搜索）
目标：盘点 WSL 内真实可用组件，指出缺失；用公司 API 的 DeepSeek 配置做真实模型验证（不再考虑 Qwen）。
结论先行：**PostgreSQL / Redis / Milvus / 公司 DeepSeek 网关 = 真实可用（REAL）；Embedding 服务 = BLOCKED（镜像缺 llama-server）；Celery worker/beat、前端容器、Milvus 语义索引 = 未启动/空索引。** 真实模型引用判定在 10 条合成案例上 7/10 与期望一致，其余 3 条为裁判职责外的治理项（见 §4），不能据此声称真实业务准确率。

## 1. 组件清单（实测证据）

| 组件 | 状态 | 证据 |
| --- | --- | --- |
| Docker Engine（Ubuntu WSL2） | REAL | 29.6.2；8 vCPU / 7.7 GiB；`docker ps` 见下表 |
| PostgreSQL 16（compose `ybt-postgres`） | REAL | `postgres:16`，healthy，`127.0.0.1:5432`，库 `ybt_dsh_handoff_v2`，`alembic upgrade head` → 150 张表；冒烟 latency 862ms |
| PostgreSQL 16（`ybt-pg-host`） | REAL | `127.0.0.1:15432`，user `ybt`，本机通用宿主库 |
| Redis 7（compose `ybt-redis`） | REAL | `redis:7-alpine`，healthy，`127.0.0.1:6379`，AOF on；PING 与 SET/GET 往返 OK（321ms，空库 0 keys） |
| Milvus 2.5.4 standalone | REAL | `milvusdb/milvus:v2.5.4` healthy + etcd v3.5.18 + minio；`http://127.0.0.1:19530`；经 `app.services.vector.milvus.MilvusVectorStore` 建集合、512 维写入 3 条、search 命中、count=3、drop 全部成功 |
| 公司 LLM 网关（DeepSeek） | REAL | `backend/.env`：`LLM_PROVIDER=openai_compatible`、`LLM_BASE_URL=http://47.101.159.7:29988/v1`、`LLM_MODEL=deepseek-v4-flash`、key 已配置；字段重排 2.42s/375 tokens 判对；引用裁判 1.62s/230 tokens 判对；`/api/ai-runtime/status` 显示 `is_mock=false, configuration_status=configured` |
| 后端应用（当前源码） | REAL | 本机 uvicorn 8011，`.env` 真实配置启动成功，`/api/health` ok，`/api/ai-runtime/status` 返回非 mock 运行时；Milvus `reachable=true` |
| 后端容器 `ybt-dev-app` | 旧镜像 | 运行中但镜像为 `ybt-backend:production-sync-20260909-verified2`，**不是当前源码**；8000 未发布到宿主 |
| Ollama（`ybt-ollama`，alpine/ollama:0.32.4） | BLOCKED | `127.0.0.1:11434` 可连，模型库里有 `BAAI/bge-small-zh-v1.5`（17MB ollama 格式），但请求 embedding 返回 `HTTP 500: error starting llama-server: llama-server binary not found (checked: /usr/lib/ollama/llama-server, …)`——alpine 镜像内缺推理二进制，模型在库也无法加载 |
| 本地 embedding 备选（fastembed 0.8.0） | BLOCKED | 进程内 `TextEmbedding("BAAI/bge-small-zh-v1.5")` 触发 HF 下载，5 个文件卡在 0%（300s 超时转后台后终止）→ 当前网络无法取权重 |
| Docker Hub 拉取 `ollama/ollama:latest`（Debian 版） | BLOCKED（网络） | 拉取 35 分钟未完成（层下载挂起），已终止；本机到 Docker Hub 大镜像带宽受限 |
| Celery worker / beat | 未启动 | 当前 `ybt-dev` 栈只起 postgres/redis/milvus/etcd/minio/app；旧项目 `ybt-worker`/`ybt-beat` 是 5 周前另一工程，未复用 |
| 前端 | 未启动 | 3000 未监听；`ybt-frontend` 为 5 周前旧容器 Exited |
| Milvus 语义索引 | 空 | `/api/ai-runtime/status`：`semantic_index.state=unavailable`、`active_index_count=0`（因无可用 embedding，尚未灌库） |

其它已确认：`jieba 0.42.1` 已装；`pymilvus 2.6.17` 与 2.5.4 服务端兼容（用 `MilvusClient` API）；`fastembed 0.8.0` 已装但无本地权重缓存；`tiktoken` 未使用；仓库内没有任何 Qwen 部署配置。
注意：当前 WSL 同时存在两套依赖实例——`ybt-postgres`/`ybt-redis`（发布到宿主 5432/6379，应用 `.env` 指向的就是它们，库表与冒烟都在这套）与 `ybt-dev-pg`/`ybt-dev-redis`（compose 内部实例、未发布）。两套并存容易混淆，后续应保留一套并停掉另一套；本次未擅自删除运行中实例。

## 2. 本轮实际动作

1. 删除 5 周前另一工程的冲突容器 `ybt-redis`、`ybt-postgres`（数据卷保留），避免容器名冲突。
2. 在 WSL 的 `C:\Users\李儒伟\Documents\智能分析智能体平台` 用显式项目名启动 compose：`docker compose -p ybt-dev --profile milvus up -d postgres redis etcd milvus-minio milvus`（中文目录导致 compose 默认项目名为空，必须 `-p`）。
3. 在 compose PG 内创建应用角色/库 `ybt_dsh_handoff_v2`，执行 `alembic upgrade head`（150 张表，revision 到 `202611010001`）。
4. 启动 `alpine/ollama:0.32.4` 并拉取 `BAAI/bge-small-zh-v1.5` → 发现镜像缺 `llama-server`，embedding BLOCKED。
5. 以真实 `.env` 启动当前源码后端（`uvicorn app.main:app --port 8011`），确认 PostgreSQL/Milvus/LLM 三项真实可用。
6. 新增并运行两个真实冒烟脚本（见 §5），结果写入 `docs/audit/VNEXT_REAL_COMPONENT_SMOKE-20261021.json` 与 `docs/audit/VNEXT_REAL_MODEL_GOLDEN-20261021.json`。
7. 修复引用裁判证据投影缺陷（见 §3），补 2 条回归测试（`tests/test_rag_citation_support.py`，14 passed）。

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

## 6. 缺失项与最小修复路径

1. **Embedding（P0，阻塞 Milvus 语义检索）**：三条路都已实测受阻——a) `alpine/ollama:0.32.4` 无 `llama-server` 二进制；b) 拉 `ollama/ollama:latest`（Debian 版）35 分钟未下完（Docker Hub 带宽受限，已终止）；c) fastembed 进程内下载 HF 权重卡 0%。最小修复路径（按可行性排序）：① 在有外网的机器把 `bge-small-zh-v1.5` 权重（~100MB）与 Debian 版 ollama 镜像离线导入内网；② 或用公司内部模型服务提供 OpenAI 兼容 `/v1/embeddings`，只改 `EMBEDDING_BASE_URL`；③ 完成后 `POST /api/ai-runtime/test-embedding` 校验 512 维，再灌 Milvus。完成前所有依赖向量检索的验收保持 BLOCKED，不得用 Mock 结果冒充。
2. **Celery worker/beat（P1）**：需要真实队列/重投/租约验收时启动 `docker compose -p ybt-dev up -d worker beat`（当前栈未含），并建独立测试库/Redis db。
3. **前端（P1）**：`npm run dev` 或 compose frontend（3000），再做真实浏览器关键操作验收。
4. **Milvus 灌库（P1，依赖 1）**：embedding 可用后执行知识入库与 `semantic_index` 重建，校验集合维度、删除同步、重启后可恢复。
5. **裁判上下文（P1）**：把 `document_version_id`/版本号/生效日与冲突证据一并传入 `check_citation_support`，闭合 C09/C10 类缺口。

## 7. 未验证 / 保留声明

- 真实业务准确率、独立人工标注：UNVERIFIED（0 名独立银行专家标注）。
- Celery 队列语义（重复投递幂等、Worker 崩溃恢复、租约过期）：BLOCKED（worker 未启动）。
- 前端真机操作：UNVERIFIED（未启动/未点检）。
- Milvus 检索质量：BLOCKED（无 embedding、索引为空）；仅验证了写入/搜索/删除机制可用。
- 公司 DeepSeek 网关为开发/验证用；生产主模型按任务书仍是项目既定内网模型，本次不改变生产配置。

## 8. 运行方式与重启注意事项（实测踩坑）

启动（WSL 内；目录含中文，必须显式 `-p`）：

```bash
cd /mnt/c/Users/李儒伟/Documents/智能分析智能体平台
docker compose -p ybt-dev --profile milvus -f docker-compose.yml -f docker-compose.dev-ports.yml up -d postgres redis milvus
```

- **WSL 会空闲回收**：本机 `.wslconfig` 为 `networkingMode=mirrored`。没有任何 WSL 进程时发行版停止，Windows 侧 `127.0.0.1:5432/6379/19530/11434` 立即变成「积极拒绝」；下次执行 `wsl` 命令时容器才重新拉起（`docker ps` 显示 Up 几秒）。**必须保持一个常驻 WSL 进程**（例如计划任务运行 `wsl -d Ubuntu -- bash -lc "sleep infinity"`），否则 uvicorn、浏览器验收会间歇性连不上。
- 数据重启后仍在（`ybt-dev_postgres_data`/`ybt-dev_redis_data` 命名卷）：PG 150 张表、Redis AOF 均可恢复；但 Milvus 栈（etcd/minio/milvus）**没有 restart policy**，docker 重启后需手动 `compose up -d milvus`（实测重启后三容器 Exited，手动拉起后 healthy）。
- 重启后复测证据：`docs/audit/VNEXT_REAL_COMPONENT_SMOKE-20261021-after-restart.json`——postgres real（150 表/1.06s）、redis real（0.44s）、milvus real（512 维/3 条/2 命中/7.2s）、embeddings 仍 BLOCKED（缺 llama-server）。
- 真实后端（uvicorn，真实 `.env`）已验证 `/api/health` OK、`/api/ai-runtime/status` `is_mock=false`、Milvus `reachable=true`、语义索引 `available=false`；验证后进程已退出，容器保持运行。
