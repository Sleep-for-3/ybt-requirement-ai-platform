# 全量后端回归（第三阶段后，新鲜执行不复用历史计数）

## 执行环境

- 工作目录 `ai-platform/backend`，venv `.venv`（Python 3.12.14，Windows 11）。
- 环境变量：`TASK_QUEUE_PROVIDER=inline`、`AUTH_MODE=optional`。
- 命令：`.venv\Scripts\python.exe -m pytest -q`（全量，无 `-k` 过滤、无跳过）。
- 提交：`76c20c0`（第三阶段发布固化，本地工作区含未提交的文档草稿）。
- 日志：`.local-run/full-regression-phase3.log`。

## 结果

```
1 failed, 1477 passed, 11 warnings in 1037.22s (0:17:17)
PYTEST_EXIT=1
```

## 唯一失败的定性与处置

| 项 | 内容 |
| --- | --- |
| 用例 | `tests/test_semantic_catalog_api.py::test_semantic_catalog_701_concepts_uses_existing_index_with_bounded_queries` |
| 失败断言 | `assert elapsed_ms < 2_000` → `assert 2444.85449999047 < 2000`（`tests/test_semantic_catalog_api.py:1761`） |
| 同一用例的其它断言 | `warm.status_code == 200`、`response.status_code == 200`、`total == 701`、`items == 100`、**`len(statements) <= 12`（查询条数上界）全部通过** |
| 单独复跑 | `pytest <该用例> -q` → **1 passed（3.28s）** |
| 定性 | **墙上时钟性能断言**，在 17 分钟全量回归的机器负载下超时；查询**条数**契约（真正防止 N+1 的断言）始终满足。**与本轮 P1–P4 改动无关**（改动只涉及 Dockerfile / CI / compose / 发布脚本 / 依赖与契约测试）。 |
| 处置 | 不改动该断言（复核原则：不得为变绿而放宽既有测试）；如实记录为“既有脆弱性能断言，全量负载下偶发”。 |

## 结论

第三阶段的改动没有造成功能回归：**1477 passed**，唯一失败是既有的时间敏感断言，已单独复跑证明通过并记录原因。

## 未验证

- 未在 CI（Linux runner）上执行该全量回归；本结论适用于 Windows 本机环境。
- 未执行前端 test/tsc/lint/build 与安全扫描（属最终验收轮，尚未开始）。
