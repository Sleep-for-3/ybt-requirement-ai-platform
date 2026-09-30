# 固定版本文档辅助首版契约

2026-09-29。任务键 `requirement_document_assistance`，输出键 `document_assistance_v1`，调用范围 `requirement_document`。无数据库迁移；输出复用 ModelCallLog，未修改 Requirement 或 RequirementRevision。

- POST `/projects/{project_id}/requirements/{requirement_id}/revisions/{content_version}/document-assistance`。真实身份、项目查看和知识检索权限；必须有已发布且明确固定采用的 Skill，不使用隐式 Legacy 或上级最新版本。
- 依据明确的不可变修订，不追随当前需求版本。加载时验证内容哈希；将 requirement、fields、script_basis、policy_comparisons、gaps 分别投影为带修订哈希和定位符的事实。固定制度文本重新检查有效性和身份，不用现行条款悄悄替换历史文本。
- 输出四组段落：background、business_description、difference_analysis、missing_information。每段必须非空且引用固定事实 ID；拒绝未知引用及额外字段。无有效候选时显式展示缺口。Mock 通过只代表流程验证。
- 输出 Schema、任务安全提示和原生未知引用负例进入共享编译、确定性/Mock/Replay 评测与发布依赖指纹。兼容 Prompt 快照保存相同原生 Schema。
- 调用后重新核验权限、固定依据、版本与绑定锁；依赖变化或撤权拒绝返回。错误输出降级并保留固定事实，不把错误输出当作正文。
- 首版仅允许 local_only 模型配置。完整历史修订仍需逐来源补齐外发授权投影后，才能开放外部模型；不能只靠项目默认密级推断可外发。
- 页面按固定内容版本隔离结果，未保存编辑期间禁用生成；候选、实际 Skill/模型来源、引用和缺口分别显示。没有自动采用或修改正文的接口；正式 Word/Excel 继续读取原固定修订，不导出未采用的辅助候选。

验证：后端原生发布/执行/历史保护/坏引用/撤权/完整性及既有需求发布组合见 b2-document.*；本地限制和后续效力回归见 b2-document-local.*、b2-document-final.*。制度+文档真实 HTTP/隔离 SQLite/合成 Mock 浏览器 7 checks，见 docs/ux/acceptance/ai-skill-document-browser-20260929/results.json。真实模型质量、PostgreSQL 及外部模型授权仍未验收。
