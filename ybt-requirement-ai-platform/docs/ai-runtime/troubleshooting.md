# AI 运行环境故障排查

## Docker 无法启动

先运行 `docker version`、`docker compose version` 和 `python scripts/check_local_setup.py`。确认 Docker Desktop/daemon 正在运行，3000、8000 端口未被占用，并检查 `docker compose config`。

## `.env` 未加载

Compose 只读取 `backend/.env`，不会读取 `.env.example`。确认文件名没有被 Windows 保存成 `.env.txt`，修改后重建后端和 worker 容器。

## API Key 未识别

`LLM_API_KEY_ENV_NAME` 的值必须是合法环境变量名，例如 `OPENAI_API_KEY`；再在同一 `backend/.env` 中设置该变量。页面只显示 `api_key_present`，绝不显示 Key。

## HTTP 错误

- 401：认证失败，检查 Key 所在环境变量。
- 403：凭据没有模型或服务权限。
- 404：检查 Base URL 是否包含兼容 API 前缀，以及模型名称是否正确。
- 429：额度不足或频率限制；客户端最多进行两次短指数退避重试。
- 5xx：上游暂时异常；仅 500、502、503、504 进行有界重试。

400、401、403、404 不重试，也不会转为 Mock 成功。

## JSON Mode 或输出格式

若兼容服务不支持 `response_format=json_object`，在 Profile 能力配置中关闭 JSON Mode。模型返回最外层明确的 ` ```json ` 代码块可以被安全移除；非法 JSON 会触发一次受控格式修复，第二次仍失败则不写入草稿。

## Embedding 维度异常

测试接口只返回维度，不返回向量。维度为零、向量为空或元素不是数值时视为失败。确认模型是 Embedding 模型，并检查向量库现有 collection 的维度是否一致。

## 请求超时

默认 60 秒，Profile 可设 1–180 秒。网络超时最多重试两次；不要通过无限延长超时掩盖 Provider 性能问题。

## CORS

本机默认 `CORS_ORIGINS=http://localhost:3000`。如浏览器使用 `127.0.0.1` 或其他端口，应显式加入逗号分隔白名单并重启后端。

## 后端健康但前端不可访问

先访问 `/health/live` 和 `/docs`，再检查前端容器日志、3000 端口以及 `NEXT_PUBLIC_API_BASE_URL`。模型 Key 不应出现在任何 `NEXT_PUBLIC_*` 变量中。

## 为什么页面显示 Mock

检查 `LLM_PROVIDER`、是否有一个已启用的数据库 ModelProfile，以及容器是否在修改配置后重建。已启用 Profile 的优先级高于环境中的聊天模型配置。

## 如何确认真实 API 已调用

管理员先查看 `/api/ai-runtime/status` 的 `is_mock=false`，再执行 `/api/ai-runtime/test-chat`。成功响应包含 Provider、模型、HTTP 状态、延迟和 Token 使用；业务调用可在当前项目的“最近模型调用”查看。兼容服务不返回 usage 时会明确显示 `usage unavailable`，不能据此伪造 Token。
