# 知识治理与监管问答热修复（4b8883b）

## 新建项目后数据血缘入口消失

### 根因

- `AppShell` 只在页面首次挂载时请求一次 `/auth/me`，而项目权限是按 `projectId` 返回的。
- 在创建新项目后直接切换到该项目时，前端仍使用创建前缓存的权限表；新项目 ID 不在旧表中，`navigationAccessForProject` 会把当前用户判断为没有技术权限，因而隐藏“数据血缘”等 `technical` 导航。
- 该现象不代表新项目缺失血缘模块，整页刷新后会重新获取权限并恢复入口。

### 修复

- 当前项目 `projectId` 变化时重新请求 `/auth/me`，并用请求序号清理保护避免旧项目响应覆盖新项目权限。
- 项目切换仍由后端 `effective_project_permissions` 作为唯一权限事实，不在前端复制或猜测项目角色。

### 验证

- 前端自动化测试：`148 passed`。
- `npx tsc --noEmit`：通过。
- 隔离生产构建：通过，未覆盖现有 `.next`。

## 监管问答“问题或筛选条件无效”（4b8883b）

### 现象与根因

- 监管知识问答是“确定性检索 + 大模型组织回答”，不是把整份文档直接交给模型自由回答。检索先确定可引用知识单元，模型只能基于这些单元生成结论。
- 生产项目 `1` 当时没有 `embedding_index_versions` 的 active 正式索引。Milvus 模式下，原 `hybrid` 检索在项目尚无正式索引时抛出 `No active formal semantic index exists for this project`。
- 接口将该错误返回为 `400`，前端 `askErrorMessage` 对 `400/422` 统一显示“问题或筛选条件无效”，因此文档已经生效但页面仍表现为输入无效。
- `vector_store=healthy` 只说明 Milvus 组件可用，不能证明每个项目都已经发布正式向量索引。

### 修复

- `HybridRetriever` 在 Milvus 模式下遇到项目无 active 正式索引时，不再让 `hybrid` 问答失败；保留确定性关键词检索，并明确记录 `keyword_only` 降级。
- `keyword_only` 和 `vector_only` 的既有语义不变；`vector_only` 仍要求正式索引，避免把降级伪装成向量检索。
- 检索日志、索引状态和回答可信度继续暴露“正式索引未覆盖/关键词降级”，不伪造索引证据。

### 验证

- `backend/tests/test_hybrid_retriever.py`：`3 passed`。
- 与 `backend/tests/test_knowledge_rag.py` 联合回归：`24 passed`。
- `backend/tests/test_release_hardening.py`：`4 passed`。
- 生产容器代码已确认包含无正式索引时的关键词降级逻辑。
- 生产项目 `1` 直接调用 `grounded_answer`，问题“客户证件类型的报送范围和监管依据是什么？”返回 `answer_status=grounded`、`citations=10`、`retrieval_log_id=529`，索引状态为 `keyword_fallback=true`，未再出现“无正式索引”异常。

### 发布

- GitHub `main`：`4b8883b`。
- backend / frontend / worker / beat / embedding：`4b8883b` 镜像，全部 healthy。
- readiness 门禁：11 项全部 healthy。
- 发布前备份：`/data/ybt/backups/release-4b8883b/db.dump`。

## 知识文档审核入口热修复（68179e8）

## 问题

- 生产文档 `6` 的内部版本为 `indexed + draft`，页面只在 `pending_review` 状态显示审核按钮，导致版本记录页没有任何可执行操作。
- 旧文档的解析告警和知识单元总数保存在文档主记录，版本行字段为空，页面显示“500 个知识单元”和笼统告警，无法看到实际数量和具体原因。
- “禁用知识”入口只出现在“索引状态”页签，用户容易误以为资料不可停用。

## 修复

- 增加 `POST /knowledge/document-versions/{version_id}/submit-review`，支持解析成功的草稿显式进入待审核。
- 页面版本流程恢复为“提交审核 -> 审核通过 -> 激活生效”。
- 对旧版本只读回退读取文档主记录中的 `warnings_json` 和 `parse_summary_json.unit_count`，不修改历史数据。
- 版本记录中可展开解析警告明细，并显示真实知识单元总数。
- “禁用知识”按钮提升到文档详情顶部，所有页签均可见；操作仍然只是归档，不物理删除历史。

## 验证

- 后端知识 API 与治理版本回归：`26 passed`。
- 前端完整测试：`148 passed`。
- `npx tsc --noEmit`：通过。
- 隔离生产构建：通过。
- 生产 readiness：11 项全部 healthy。
- 生产路由存在性：`submit-review` 未认证请求返回 `401`，说明路由已挂载且受权限保护。
- 生产前端资源确认包含“提交审核”“查看解析警告”“禁用知识”。
- 文档 `6` 的真实解析结果为 `5922` 个知识单元，两条具体告警为“记录校验问答 未识别表头”和“穿透层问答 未识别表头”。

## 发布

- GitHub `main`：`68179e8`。
- backend / frontend / worker / beat / embedding：`68179e8` 镜像，全部 healthy。
- 数据库未新增迁移。
- 发布前备份：`/data/ybt/backups/release-68179e8/db.dump`。
- `myservers` 的 `18612` 映射保持不变，未触碰 `ndspod`。
