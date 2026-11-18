# DeepSeek 真实 API 通路验收

日期：2026-11-14（Asia/Shanghai）
范围：隔离组件环境 `rag-p0-components-20261113`
目的：先验证真实模型通路，不替换此前 Mock 生成评测的历史结果。

## 配置

- provider：`openai_compatible`
- model：`deepseek-v4.1-flash`
- gateway：`http://47.101.159.7:29988/v1`
- 网关地址来自用户提供文件，使用 HTTP；请求中的 API Key 没有 TLS 传输保护。若网关提供 HTTPS 地址，应改用 HTTPS 后再做长时间评测。
- API Key：从 `C:\Users\李儒伟\Desktop\spi.txt` 的备用模型段读取，保存为隔离工作区的私有进程环境变量 `DEEPSEEK_API_KEY`；密钥未写入源码、报告或日志。
- 生成上限：`LLM_MAX_OUTPUT_TOKENS=1024`；交互超时 60 秒；重试 0。
- embedding、Milvus、PostgreSQL、Redis 继续使用本地/隔离组件。
- 模型档案：`DeepSeek V4.1 Flash 本地连通性`，ID `1`，已启用并作为当前运行档案。

## 结果

### 1. 网关协议探测

使用单次、无业务数据的最小 chat completion 请求：

- HTTP：`200`
- 返回模型：`deepseek-v4.1-flash`
- token：prompt `37`，completion `22`
- `finish_reason`：`stop`

### 2. 应用连接测试

调用平台管理员接口 `POST /api/ai-runtime/test-chat`，由应用自身完成密钥解析、provider 构造、JSON 响应校验和模型调用：

- 结果：`ok` / `连接成功`
- HTTP：`200`
- 实测延迟：约 `1641 ms`
- 应用运行时：`OpenAICompatibleLLMService`
- 当前来源：已启用模型档案（profile `1`）

### 3. 应用问答链路

对隔离项目中的合成资料提问“合作方式字段 F250007 只能填什么？”：

- 答案：正确返回 `02`，并带合成资料引用 `[5924]`
- 引用数：`1`
- 执行类型：`real_model`
- 模型调用日志：provider `openai_compatible`、model `deepseek-v4.1-flash`、status `success`
- 该请求同时验证了本地 embedding、Milvus 检索、真实生成和引用装配链路。

## 当前运行状态

`GET /api/ai-runtime/status` 返回：

- LLM：`openai_compatible / deepseek-v4.1-flash`，`api_key_present=true`，`configuration_status=configured`
- generator：`OpenAICompatibleLLMService`，profile `1`
- embedding：本地 `BAAI/bge-small-zh-v1.5`，512 维
- vector store：Milvus，可达
- semantic index：`ready`
- 配置问题：空
- 前端：`http://127.0.0.1:18096` 返回 HTTP `200`。

## 复现边界

本次只做了最小真实调用和 1 个合成知识问答，控制了调用次数和输出长度；没有运行 104 条真实生成评测，也没有把原始业务语料发送到外部模型。此前报告中的 `external_model_calls=0` 仍表示此前 Mock 生成评测范围，本记录单独记录本次真实 API 验收。
