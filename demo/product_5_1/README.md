# 表5.1 产品业务基本信息 Demo 数据工程

本目录提供可重复生成的银行产品监管场景。它不是测试 fixture，也不包含 Agent 的隐藏答案。

数据链路：

```text
六个源业务系统 SQLite
        ↓  source_to_mart SQL
监管产品数据集市 mart_regulatory.db
        ↓  mart_to_regulatory SQL
一表通 ybt_5_1_product_business_basic
```

运行时数据库统一生成到被 Git 忽略的 `.demo_runtime/product_5_1/`。`expected/golden_mapping.json` 只允许在 Agent 完成后用于评估，bootstrap 与生成流程不得读取它。

构建：

```powershell
backend\.venv\Scripts\python.exe scripts\demo\build_product_5_1_demo.py --regulatory-xlsx "C:\Users\李儒伟\Desktop\5_1产品表 - 副本.xlsx"
```

接入当前平台并执行真实能力盘点：

```powershell
$env:PRODUCT_5_1_ADMIN_PASSWORD='Product5_1-Demo-20260830!'
backend\.venv\Scripts\python.exe scripts\demo\bootstrap_product_5_1_platform.py --regulatory-xlsx "C:\Users\李儒伟\Desktop\5_1产品表 - 副本.xlsx"
backend\.venv\Scripts\python.exe scripts\demo\run_product_5_1_verification.py
```

安全重置默认只预览。当前平台没有项目删除 API，因此执行重置只删除明确命名的 Demo 运行时文件，不会删除平台项目容器；再次 bootstrap 会幂等复用该项目。未知文件会保留。

```powershell
backend\.venv\Scripts\python.exe scripts\demo\reset_product_5_1_demo.py --dry-run
backend\.venv\Scripts\python.exe scripts\demo\reset_product_5_1_demo.py --execute --confirm-project-name "一表通产品数据智能演示"
```

固定随机种子为 `20260830`，正式采集周期为 `2026-08-31`，对比周期为 `2026-07-31`。

ETL v1 是实际构建版本。`build_ybt_5_1_v2.sql` 只用于平台 Script Version / Change Impact 演示，变更点是业务系统已经停用时优先将 E010015 报送为 `02`。

当前本地演示运行时的 LLM、Embedding 与 Vector Store 均为 Mock，因此验证脚本会明确输出 `BLOCKED_LLM_RUNTIME`，不会调用 Generator，也不会伪造 AI Mapping、AI Requirement 或准确率。
