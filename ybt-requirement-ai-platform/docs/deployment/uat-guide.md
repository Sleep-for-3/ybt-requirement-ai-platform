# UAT 操作指南

1. 在 `/uat` 选择项目，确认 8 个内置套件已幂等初始化；真实脱敏材料仅放入运行环境的 `UAT_LOCAL_PACK_DIR`。
2. 可用 `python scripts/generate_demo_uat_pack.py --output <临时目录>` 生成公开虚构材料，或上传经批准的 ZIP/多文件材料包并执行完整性校验。
3. 进入套件创建执行轮次。自动 Case 独立保存；手工和混合 Case 保持 pending，不能伪装为自动通过。
4. 在运行页查看 passed、failed、blocked、pending、预期/实际结果和结构化证据。单个失败不会中断无依赖的后续 Case。
5. 对失败项创建 Finding，填写可复现描述；完成修复后标记 resolved，由复测人员 verify。
6. 使用“重跑失败项”只重跑 failed/blocked，并复用已有 CaseResult，避免重复记录。
7. 只有 Run 为 passed 且 critical Finding 已关闭，业务负责人、技术负责人、项目经理和最终验收角色才能按权限签署。
8. 下载十 Sheet UAT 报告和证据 ZIP，核对 `SHA256SUMS`、Git SHA、migration revision 和健康摘要。

所有 UAT 材料必须脱敏。报告、日志和证据包不得包含密码、Token、数据库文件、完整生产 SQL、未脱敏知识正文或 restricted 原文件。
