# 语义检索安全

## 数据外发决策

沿用现有分级与 `local_only` 策略：

- allowed：本地 Provider 可直接处理。
- masked：公开/内部内容发往外部 Provider 前先执行现有手机号、证件号、账号、邮件、IP、连接串和密钥样式脱敏。
- forbidden：`confidential` 和 `restricted` 默认禁止发往外部 Embedding；restricted 仅允许本地模型。

拒绝发生在请求发送前，写入安全审计，不回退 Mock、不绕过策略、不发送原文。

## 日志和任务

允许记录模型名、Provider、维度、批次数、耗时、Token 摘要、内容 Hash、Collection 和数量。禁止记录 API Key、Milvus Token、Authorization、完整 URL 查询参数、完整知识正文或完整 Embedding 请求。

Milvus 只保存追踪所需元数据和向量，不保存知识正文。citation 必须回到业务库解析当前启用的 `KnowledgeUnit`，并再次校验项目/机构可见性，不能只凭向量 ID 构造。

## 密钥管理

真实密钥只放在本机 `backend/.env` 或正式 Secret Manager 对应的环境变量中。`.env.example` 必须保持空值/Mock 默认。提交前检查 staged diff，不得使用 `git add .` 或 `git add -A`，不得提交 `.env`。
