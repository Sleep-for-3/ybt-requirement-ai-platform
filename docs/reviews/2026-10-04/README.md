# DSH 最新版本跟进复核证据

复核从2026-10-04开始，于2026-10-05完成；保留启动日期目录。代码基线为开发分支8d7600619b0931044283d66ec9a17b05dc7007f1。

## 结论与开发输入

- [主审复核与下一步计划](../../../../银行智能平台最新版复核与下一步开发计划-2026-10-05.md)
- [DSH下一轮完整提示词](../../../../DSH下一轮开发提示词-2026-10-05.md)
- [后端复核](backend-followup-review.md)
- [前端产品复核](frontend-followup-review.md)
- [工程复核](engineering-followup-review.md)
- [DSH Word正文与表格提取](dsh-progress-extracted.txt)

## 动态证据

- [现场业务聚合只读采样](live-api-evidence.json)，只读业务接口；登录/退出会产生正常会话及审计记录。
- [公开版本与健康检查](live-public-health.json)
- [SQL聚合豁免、同进程任务接管、送审编辑交错与broker补投](backend-followup-repro-output.jsonl)，[隔离脚本](backend_followup_repro.py)
- [工程stub与隔离执行结果](engineering-probe-results.json)，[脚本](engineering-probes.py)
- [前端身份helper结果](frontend-identity-probe-results.json)，[脚本](frontend-identity-probe.cjs)
- [UAT签署后修改结果](uat-signed-result-repro.json)，[脚本](uat_signed_result_repro.py)。optional-auth单测模式，仅证明状态契约，不证明生产RBAC绕过。
- [UAT证据包读当前环境](uat-snapshot-repro.json)，[脚本](uat_snapshot_repro.py)。stub报告与环境，无真实数据库/健康探测。

## 测试日志

- [工程29项](targeted-pytest.log)
- [指标/UAT首次组合](product-backend-targeted-pytest.log)，24通过1失败，伴随字符集warning。
- [失败用例独立复跑](uat-permission-recheck.log)，1通过。
- [指标/UAT UTF8组合复跑](product-backend-targeted-pytest-utf8.log)，25通过。首次登录失败根因未定位，不假定由字符集造成。

后端47项和前端49项记录见各分项报告；不同测试集合有交叉，不相加作全量通过数。未在本轮独立重跑1433/253全套，未执行真实银行、收费模型、真实多worker、压力和完整系统恢复验收。没有改产品源码、迁移现有库或重启运行实例。
