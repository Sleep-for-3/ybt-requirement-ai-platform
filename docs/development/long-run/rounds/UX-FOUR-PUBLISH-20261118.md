# 四处前台体验发布记录

日期：2026-11-18。用户已单独授权提交、推送与公网测试环境部署。

## 发布结果

四处体验改造已提交 GitHub 并上线现有测试服务器。公网入口：`http://103.236.92.193:18085`。

| 项目 | 发布身份 |
| --- | --- |
| 仓库 | `Sleep-for-3/ybt-requirement-ai-platform` |
| 分支 | `dsh/handoff-20261025-round73` |
| 应用提交 | `413a77f9543e5fb386a297a9c709094686edceb1` |
| 前序提交 | `15826d39c6601c11d302531ba6a038d0c2f7d307` |
| 前端镜像 | `ybt-frontend:413a77f-ux` |
| API / worker / beat 镜像 | `ybt-backend:413a77f-ux` |
| 构建时间 | `2026-11-18T06:10:00Z` |
| Schema | `202611010014`，未执行迁移 |

任务台、后台执行详情、需求阅读核对、当前项目资产搜索的行为及现场演示见 [四处前台体验交付](UX-FOUR-20261118.md)。本次只发布既有交付，不新增业务功能。发布记录的后续文档提交与已部署应用提交分开标识，无须为文档重新部署。

## 验证结果

| 证据层 | 结果 | 覆盖范围 |
| --- | --- | --- |
| 后端定向测试 | 24 passed / 32 deselected | Agent运行时、阶段归属、重试批次、全局搜索权限 |
| 前端定向测试 | 64 passed | 任务业务视图、工作台、后台任务、轮询、需求进度 |
| Linux生产构建 | 通过 | 编译、类型检查、lint、页面生成；存在原有hook警告 |
| 远端真实组件 | 通过 | 四个应用容器健康，worker/beat探针退出0；readiness中的数据库、迁移版本、存储、Redis、队列、向量库、provider配置、语义索引和磁盘检查健康 |
| 公网浏览器 | 通过 | 1440×900与390×844登录页200、焦点顺序、POST表单、无横向溢出；匿名项目接口401；前端/API提交和构建时间一致；无页面异常 |
| 登录后业务链路 | 本次未重测 | 既有本地真实组件与浏览器验收见原交付报告，不转换为线上业务验收 |
| 真实模型 | 本次未调用 | 新增外部请求0；provider就绪不等于模型业务质量验收 |

本地原始发布证据在 `.local-run/rag-long-run/ux-four-20261118/`：`remote-verification.json`、`public-browser/results.json`、`public-browser/login-1440.png`、`public-browser/login-390.png`。截图与运行材料不包含在源码提交中；脱敏结论在对应JSON交付清单内。

## 数据与回退

worker空闲后完成数据库与存储备份，仅重建API、worker、beat、前端四个应用容器；保留PostgreSQL、Redis、Milvus、Embedding、存储和全部现有卷。不新建公网演示任务，不改业务内容。

| 记录 | 升级前 | 升级后 |
| --- | ---: | ---: |
| 项目 | 33 | 33 |
| 知识文档 | 43 | 43 |
| 文档版本 | 43 | 43 |
| 智能体任务 | 13 | 13 |
| 后台任务 | 210 | 210 |
| 文件 | 86 | 86 |
| 需求 | 12 | 12 |

受保护备份目录 `/home/ybt-release-413a77f/private/` 保存数据库dump、存储归档、旧环境配置和容器检查材料。数据库归档已通过`pg_restore`目录检查，存储归档已通过文件列表检查；不据此宣称恢复演练通过。含配置的备份不得公开或提交Git。

发布源代码位于 `/home/ybt-release-413a77f/source`。现有Compose仍位于 `/opt/ybt/source`，仅更新`.env`的`YBT_RELEASE_TAG`、`APP_COMMIT`、`BUILD_TIME`，其余配置与凭据不变；原源码不覆盖，运行身份以镜像和版本接口为准。

回退命令（在服务器执行）：

```bash
python3 /home/ybt-release-413a77f/publish.py rollback
```

该命令恢复原配置并用保留的`15826d3-r2`镜像重建四个应用容器，等待API与前端启动。无迁移，无须回滚数据库。本次未执行回退演练。

## 复验方式

本地后端目录：

```powershell
.venv/Scripts/python.exe -m pytest tests/test_agent_runtime.py tests/test_governance.py -k 'not governance or global_search' -q
```

本地前端目录：

```powershell
node --test tests/agent-business-view.test.mjs tests/agent-workspace-v2.test.mjs tests/background-job.test.mjs tests/job-polling.test.mjs tests/requirement-progress.test.mjs
```

公网只读复验：打开上述入口的登录页，在1440和390宽度检查表单、焦点和布局；请求`/api/version`确认应用提交，`/api/health/ready`确认就绪，匿名`/api/projects`应401。自动浏览器脚本为本地证据目录下的`public-smoke.mjs`。登录后演示应使用现有授权账号，不在报告中保存凭据。

## 已知问题

- 线上登录后业务主链路本次未重测；不将公网登录页smoke表述为四项业务线上全量验收。
- 根分区剩余约890MB，使用率97%；`/home`约4.7GB可用。后续发布前需要安排容量处理，保留现有数据与回退镜像。
- 历史域名`57008897.xyz`的版本接口返回404，本次使用已验证的IP端口入口，未调整DNS。
- P0黄金集、独立来源和真实模型质量等历史未闭合事项不因本次发布关闭。

## 停止状态

发布完成，线上服务保持运行。唯一下一步：停止并等待用户新指令；不自动继续P0/P1/P2，不执行清理或扩展公网数据。
