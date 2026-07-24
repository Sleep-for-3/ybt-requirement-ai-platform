# 上线安全检查清单

- [ ] `AUTH_MODE=required`，生产密钥由 Secret 管理且完成轮换预案。
- [ ] CORS 仅允许批准的 HTTPS 源，DEBUG 关闭，代理头设置与入口拓扑一致。
- [ ] PostgreSQL、Redis、MinIO/S3、Milvus 不暴露到公共网络。
- [ ] 数据源账户只读，上传大小、ZIP 解压大小和文件数有限制。
- [ ] Git 拉取使用主机/本地根白名单；不执行上传的 SQL、Shell 或 Git hooks。
- [ ] 机构与项目越权返回 404，角色不足返回 403；前端隐藏按钮不替代后端鉴权。
- [ ] 日志不含 Authorization、Cookie、密码、Token、连接串、原始 SQL或 restricted 正文。
- [ ] `/health/details` 仅平台管理员可见。
- [ ] 数据库与对象存储备份已加密并完成恢复演练。
- [ ] UAT critical Finding 已验证关闭，签署角色符合职责分离。
- [ ] 证据包校验 SHA256SUMS，且不包含 `.env`、数据库、凭据或真实原始材料。
