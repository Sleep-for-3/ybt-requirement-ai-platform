# 2026-10-06 最终验收：全量后端 + 前端 test/tsc/lint/build + 安全扫描

在**最终源码提交**上执行，**不复用历史计数**。

## 1. 后端全量回归

### 第一次（发现 3 例真实回归，已修复）

```
cd backend
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
<py> -m pytest -q
→ 3 failed, 1503 passed, 1 skipped, 13 warnings in 1182.38s（PYTEST_EXIT=1）

FAILED tests/test_resources_data_contract.py::test_invented_claim_is_not_grounded[Invented.column]
FAILED tests/test_resources_data_contract.py::test_invented_claim_is_not_grounded[Known.table [99999]]
FAILED tests/test_resources_data_contract.py::test_invented_claim_is_not_grounded[Known.table.column]
```

**这是我本轮 C06 改动引入的真实回归**，不是环境问题：

```
TypeError: test_invented_claim_is_not_grounded.<locals>.<lambda>() got an unexpected
           keyword argument 'model_profile_id'
  at app/services/rag/grounded_answer_service.py:71
```

C06 为了让"评测指定的模型"真正到达 runtime，把 `grounded_answer` 改成**总是**传
`model_profile_id=`；而该测试用两参数 lambda 替换了 `get_prompt_runtime`，于是签名不匹配。

**修复**：只在**确实选中了** profile 时才传该关键字参数，"未指定"保持原有两参数调用形状：

```python
selected_profile_id = filters.get("model_profile_id")
runtime = evidence_runtime(
    get_prompt_runtime(db, "regulatory_field_explanation")
    if selected_profile_id is None
    else get_prompt_runtime(db, "regulatory_field_explanation",
                            model_profile_id=selected_profile_id))
```

修复后定向复验：
```
<py> -m pytest tests/test_resources_data_contract.py \
    tests/test_rag_evaluation_semantic.py tests/test_rag_evaluation_fidelity.py -q
→ 44 passed, 1 warning（含此前失败的 3 例）
```

### 第二次（最终，通过）
```
cd backend
$env:TASK_QUEUE_PROVIDER='inline'; $env:AUTH_MODE='optional'
$env:PHASE4_VERIFY_DATABASE_URL=postgresql+psycopg://...@127.0.0.1:5432/ybt_iso_phase4_synthetic
<py> -m pytest -q
→ 1507 passed, 13 warnings in 1185.44s（0:19:45）
→ PYTEST_EXIT=0
```

**1507 passed / 0 failed / 0 skipped**。基线 `fd7a532` 为 1480 passed / **1 skipped**；
本轮新增 **27 条后端用例**（C03/C04/C05 共 9 条 + C06/C07/C08 共 17 条 + 其他 1 条），
且此前那 1 例 skipped 在设置 `PHASE4_VERIFY_DATABASE_URL` 后**执行并通过**（因此 skipped 归零）。
完整输出：`.local-run/c-round-final-regression2.log`。

## 2. 前端验证（最终提交）

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 单元测试 | `node --test tests/*.test.mjs` | **267 passed / 0 failed** |
| 类型检查 | `tsc --noEmit --incremental false` | **exit 0** |
| Lint | `next lint --no-cache` | **exit 0**（12 处既有 warning，非本轮引入） |
| 生产构建 | `next build`（注入 `NEXT_PUBLIC_APP_COMMIT`/`BUILD_TIME`） | **exit 0** |

> 计数说明：上一轮前端基线是 253 passed；本轮新增 **14 条**（C01 7 条 + C02 3 条 + C11 4 条），
> 合计 **267**。原有用例全部保留（C11 更新了 1 条断言旧缺陷契约的用例，未删除任何断言）。

## 3. 安全扫描（最终提交）

| 扫描 | 结果 |
| --- | --- |
| `npm audit --omit=dev` | **total 0**（info/low/moderate/high/critical 全 0） |
| 依赖修复 | 本轮发现 `source-map-js` GHSA-68fv-2mgg-jv7q（1 high）→ override `^1.2.2`，实装 1.2.2 |

> 该公告是**新公布**的（本轮未触碰 postcss/source-map-js），因此同一份 lock 在 2026-10-05 扫描时是干净的。
> 已按其实际影响修复，详见 [security-source-map-js.md](security-source-map-js.md)。

## 4. 本轮新增测试（全部覆盖真实触发行为）

| 项 | 新增/更新 | 修复前 | 修复后 |
| --- | --- | --- | --- |
| C01 | 新增 7（驱动真实 `lib/api.ts`） | 1 passed / 6 failed | **7 / 0** |
| C02 | 新增 3 + 升级 1 | 9 passed / 3 failed | **12 / 0** |
| C03/C04/C05 | 新增 9 | 6 failed / 3 passed | **9 / 0** |
| C06/C07/C08 | 新增 17 | 14 failed / 3 passed | **17 / 0** |
| C09 | 新增动态回归（12 项检查） | 4 failed / 8 passed | **12 / 12** |
| C10 | 重写为隔离验收（12 步 + 负例） | 无守卫（源码确认） | **12 / 0** + 负例非零退出 |
| C11 | 新增 4 + 更新 1 | 8 passed / 2 failed | **10 / 0** |

「修复前」列均由 `git stash` 临时还原**产品源码**后重跑同一份回归测得，不是引用历史报告。

## 5. 最终计数

| 项 | 结果 |
| --- | --- |
| **后端全量回归（最终）** | **1507 passed / 0 failed / 0 skipped**（19:45，`PYTEST_EXIT=0`） |
| 前端单元测试 | **267 passed / 0 failed** |
| 前端 tsc / lint / build | **全部 exit 0** |
| `npm audit --omit=dev` | **0 漏洞** |

## 6. 未验证 / 待验收（不得当作通过）

1. **真实银行资料与签署人仍缺失**（W11 银行验收未完成）；
2. 未在业务库应用任何迁移；新增迁移 `202610060001` 只在**全新隔离库**验证到 head；
3. 未改动 3000/8000 服务；未清共享 Redis（DB0 哨兵全程保留）；
4. 未调用未批准的真实模型（C06/C07 用 spy，C10 子进程强制 mock）；
5. 未在 CI（Linux runner）执行；未做容器镜像层扫描；`npm audit` 仅覆盖生产依赖；
6. C09 未在真实 Docker/Compose 执行；
7. 未做多机部署、broker/数据库高可用与容量压测；
8. 未做真实浏览器断网（DevTools offline）逐项验证 C11 的提示条与重试按钮。

## 7. 边界与保护（未被破坏）

- **未操作业务库**：`ybt_dsh_handoff_v2` 未连接写入、未应用迁移；
- **未改动 3000/8000**：用户既有服务全程未受影响（本轮未启动/停止这两个端口）；
- **未清共享 Redis**：验收在专用 DB15 的 UUID 队列上运行，DB0 的业务哨兵消息经前后核对**完全未变**；
- **未调用真实模型**：模型边界为 spy 或 mock；
- 未删除任何用户文件或目录。
