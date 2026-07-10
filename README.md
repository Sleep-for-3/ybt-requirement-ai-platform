# 银行一表通字段级口径智能辅助平台

实际代码位于 [`ybt-requirement-ai-platform`](./ybt-requirement-ai-platform)。项目采用 FastAPI、Next.js、PostgreSQL 和 Docker Compose，主产物是按产品/业务场景维护并导出的“业务口径及技术溯源 Excel”。

```bash
cd ybt-requirement-ai-platform
docker compose up --build
```

启动后访问 `http://localhost:3000`，后端接口文档位于 `http://localhost:8000/docs`。默认使用 Mock LLM，不需要真实模型密钥。

安全提示：仓库只允许提交程序生成的脱敏模拟数据。禁止提交真实银行数据、账号、密码、IP、监管答疑原件、生产 SQL 或真实表结构。
