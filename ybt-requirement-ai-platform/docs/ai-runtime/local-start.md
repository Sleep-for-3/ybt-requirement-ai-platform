# 本地启动

`backend/.env.example` 是公开模板，Docker Compose 实际只读取未纳入 Git 的 `backend/.env`。复制模板后必须人工检查配置；项目不会自动复制模板，也不会把 Secret 烘焙进镜像。

## Windows PowerShell

```powershell
git checkout main
git pull origin main
cd ybt-requirement-ai-platform
Copy-Item backend/.env.example backend/.env
notepad backend/.env
python scripts/check_local_setup.py
docker compose up --build
```

## Linux / macOS

```bash
git checkout main
git pull origin main
cd ybt-requirement-ai-platform
cp backend/.env.example backend/.env
${EDITOR:-vi} backend/.env
python scripts/check_local_setup.py
docker compose up --build
```

检查脚本输出 `PASS`、`WARN` 和 `FAIL`，不会打印 API Key。存在 `FAIL` 时退出码为 1；只有警告时仍为 0。

启动后访问：

- 前端：<http://localhost:3000>
- 存活检查：<http://localhost:8000/health/live>
- 就绪检查：<http://localhost:8000/health/ready>
- OpenAPI：<http://localhost:8000/docs>
- AI 运行环境：<http://localhost:3000/model-profiles>

`/health/ready` 只验证 Provider 配置完整性，不发起收费模型请求。联网测试必须由管理员在 AI 运行环境页面点击“测试连接”，或显式运行：

```powershell
python scripts/test_llm_connection.py
python scripts/test_llm_connection.py --embedding
```

这些命令只发送固定的最小连接测试文本，不读取项目、知识库、银行文件或用户输入。
