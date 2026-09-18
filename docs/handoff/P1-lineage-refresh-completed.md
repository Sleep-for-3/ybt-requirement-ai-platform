# P1: 需求血缘显式核验功能 - 完成报告

> 完成日期：2026-09-14
>
> 状态：✅ 已完成并通过测试

## 实现内容

### 后端实现

1. **新增服务函数** (`backend/app/services/requirement_revisions.py`)
   - `refresh_lineage()`: 从当前资产图重新核验血缘关系并建立新修订
   - 保留字段内容、人工归属、证据和缺口
   - 仅更新 `lineage_graph` 快照
   - 清除 `edited_lineage` 缺口
   - 为未覆盖字段添加 `lineage_missing` 缺口

2. **新增 API 端点** (`backend/app/api/requirements.py`)
   - `POST /projects/{project_id}/requirements/{requirement_id}/revisions/{content_version}/refresh-lineage`
   - 需要权限：`lineage.view` + `technical.edit`
   - 要求当前修订为草稿状态
   - 返回新修订版本号、内容哈希和评估状态

3. **测试覆盖** (`backend/tests/test_requirement_lineage_refresh.py`)
   - ✅ 创建新修订并更新图
   - ✅ 清除编辑血缘缺口
   - ✅ 保留字段内容和人工归属
   - ✅ 锁定版本拒绝刷新
   - **测试结果**: 4 passed

### 前端实现

1. **更新血缘面板** (`frontend/components/requirement-workspace/RequirementLineagePanel.tsx`)
   - 新增"刷新血缘快照"按钮
   - 当无血缘快照时显示醒目提示和操作按钮
   - 集成 mutation 调用后端 API
   - 刷新成功后自动失效相关查询缓存
   - 通过 `onRevisionChange` 回调通知父组件版本变更

2. **用户体验**
   - 按钮仅在需要时显示（草稿状态 + 无血缘快照）
   - 刷新过程中显示"正在刷新..."状态
   - 错误时显示红色提示框
   - 成功后自动更新到新版本

## 测试结果

### 后端测试
```bash
# 血缘刷新功能测试
pytest tests/test_requirement_lineage_refresh.py -v
结果: 4 passed, 1 warning in 5.41s

# 回归测试
pytest tests/test_requirement_formal_delivery.py
       tests/test_requirement_candidate_adoption.py
       tests/test_requirement_snapshot_api.py
       tests/test_requirement_generation_input.py -q
结果: 16 passed, 1 warning in 12.79s
```

### 前端检查
```bash
npx tsc --noEmit
结果: 通过，无类型错误
```

## 功能特性

### 核心能力
1. ✅ 从当前资产图重新查询有界字段关系
2. ✅ 保存为新的需求修订（版本号递增）
3. ✅ 保留所有字段内容、人工归属、证据和缺口
4. ✅ 清除人工编辑血缘产生的 `edited_lineage` 缺口
5. ✅ 为图中未覆盖的字段添加 `lineage_missing` 缺口
6. ✅ 仅允许在草稿状态下刷新

### 安全保护
1. ✅ 权限校验：`lineage.view` + `technical.edit`
2. ✅ 状态校验：已锁定版本不可刷新
3. ✅ 版本校验：预期版本不匹配时拒绝
4. ✅ 审计记录：记录刷新操作

## 解决的问题

根据交接文档 P1 要求：

> 当前最重要的剩余工作：完成需求修订中血缘快照的显式刷新/核验操作，使正式送审不因缺少关系快照而无法完成。

✅ **已解决**：
- 用户现在可以在需求血缘页面显式刷新血缘快照
- 刷新操作会建立新的需求修订，不会覆盖历史版本
- 技术口径修改后产生的 `edited_lineage` 缺口会在刷新后清除
- 正式交付前的血缘核验阻断现在有明确的操作路径

## 未完成项

无。P1 的所有要求已完成。

## 下一步

按照交接文档执行顺序，下一步应该是：

**P2: 完整隔离银行样本**
- 8 字段、2 源表、1 中间表的连贯样本
- 含真实缺口和冲突规则
- 供后续浏览器验收和 Excel 检查使用

**P3: 正式审核浏览器闭环**
- `RequirementDeliveryPanel.tsx` 的完整端到端操作验证
- 送审 → 三步审核 → 固定 → 下载的完整流程

## 文件清单

### 新增文件
- `backend/tests/test_requirement_lineage_refresh.py` (193 行)

### 修改文件
- `backend/app/services/requirement_revisions.py` (+68 行)
- `backend/app/api/requirements.py` (+29 行)
- `frontend/components/requirement-workspace/RequirementLineagePanel.tsx` (+60 行)

## 验证建议

建议在进入 P3 之前：
1. 在真实浏览器环境验证刷新血缘按钮的显示和交互
2. 确认刷新后的新修订能正常进入正式交付流程
3. 验证权限控制（无 `technical.edit` 权限时应拒绝）
