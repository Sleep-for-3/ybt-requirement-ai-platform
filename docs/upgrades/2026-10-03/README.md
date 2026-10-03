# 第一阶段实施与验收记录（2026-10-03）

基线：`ai-platform @ 17486f1`（审查基线）。本目录按工作包记录：问题与行为、改动、版本、验证、业务证据、发布与恢复、已知限制。

状态标记：`已修复` / `已验证` / `待验证` / `受阻`。

| 工作包 | 对应问题 | 状态 | 提交 |
| --- | --- | --- | --- |
| W01 供应链与发布基线 | B01, B17, B18, 过期迁移 head | 进行中 | `1782bac`（B23 契约） |
| W02 机构熔断与令牌原子轮换 | B02/BA05, B05/BA04 | 已修复 / 已验证 | `16767d7`（B02）、见下（B05） |
| W03 审核内容不可变 | B03/BA01 | 待开始 | — |
| W04 SQL 限额/脱敏/连接器契约 | B04/BA02, B06/BA03, B09/BA07 | 待开始 | — |
| W05 后台任务幂等与恢复 | B07/BA06 | 待开始 | — |
| W06 人工编辑与模型配置完整性 | B10–B13, B15–B16 | 待开始 | — |

---

## B23：两个过期后端测试契约

见提交 `1782bac`。

- **问题与行为**：完整回归 1360 passed / 2 failed。`test_ai_skill_migration.py` 把 head 硬编码为
  `202609270044`，新增迁移后必然失败；`test_legacy_mapping_retirement.py` 对全生产源码禁止
  `generate_mapping_draft` 字符串，误伤新 Agent 的合法工具键。
- **改动**：迁移测试改为从 `ScriptDirectory` 取**真实唯一 head**（并断言唯一），保留历史行保留、
  升降级往返、逐表 ORM/schema 一致性；退役测试保留"旧模块不存在 + 旧模块/符号 token 禁止"，
  并把 `generate_mapping_draft` 限定为仅允许出现在 `app/services/agent/`（工具/步骤/决策键），
  其他位置仍判失败。旧接口 410、无写入、历史草稿可读的三个行为测试保持不变。
- **验证**：`pytest tests/test_ai_skill_migration.py tests/test_legacy_mapping_retirement.py`
  → **5 passed**（原 2 failed / 3 passed）。未删除或弱化任何断言。

---

## W02：机构熔断（B02 / BA05）

见提交 `16767d7`。

- **问题与行为**：机构 `inactive` 时，项目列表与 capability 已隐藏，但 `_is_institution_admin` /
  `_has_institution_role` 只查成员关系、不校验 `Institution.status`，因此**持有已知 project_id 的
  机构管理员仍能通过 `require_project_permission` 读写**（读、写、关联资源）。
- **改动**：
  - 新增唯一守卫 `PermissionService._institution_is_active()`；
  - 在 `_visible_project`（`require_project_permission` / `require_project_role` /
    `effective_project_permissions` / `load_project_resource_or_404` 的唯一入口）与两个机构角色
    helper 中一致执行；
  - 无机构（`institution_id IS NULL`）的项目保持原行为；
  - **显式恢复例外**：平台管理员（需自身平台运营机构 active）仍可访问停用机构的项目；平台运营
    机构被停用后不再授予平台管理员。
  - 回归测试还发现**列表路径的同类缺陷**：`visible_project_ids()` 的"项目成员"子查询未校验机构
    状态（只有"机构管理项目"子查询校验了），已用 outer join + (无机构 OR 机构 active) 修正。
- **验证（Mock/SQLite 层）**：`tests/test_institution_deactivation_guard.py` 9 例（active 管理员仍可访问、
  停用后 view/manage/edit 全部 404、无有效权限、关联资源 404、auditor 与 member 同样被拦、
  平台管理员恢复例外、停用平台运营机构不授予平台管理员、跨机构互访被拒）。
  `pytest tests/test_institution_deactivation_guard.py tests/test_product_integrity.py` → **33 passed**。
- **业务证据**：停用机构后，列表、直达 ID、关联资源与后台执行使用同一规则；不同租户不可互访；
  平台管理员的恢复路径显式且不再由 helper 隐式绕过。

---

## W02：刷新令牌原子轮换（B05 / BA04）

- **问题与行为**：`rotate_refresh_token` 先调用 `create_session`（内部 `commit`）发行新令牌，之后才
  撤销旧令牌，且读取旧记录不加锁。同一 refresh 在两个请求中交错时**两次轮换都能成功**，产生两枚
  有效会话（审查复现：`successful_rotations_of_same_original=2`、`active_replacements=2`）。
- **改动**（`backend/app/services/auth/authentication.py`）：
  - `create_session(..., commit=True)` 新增 `commit` 参数；`commit=False` 只在调用方事务内 `flush`。
  - `rotate_refresh_token` 用**单条条件更新**原子占用旧令牌：
    `UPDATE refresh_tokens SET revoked_at=:now WHERE token_jti=:jti AND revoked_at IS NULL AND token_hash=:hash`
    并检查 `rowcount == 1`；抢占失败（未知/已消费重放/被篡改）统一返回 "Refresh token is revoked"。
  - 撤销旧令牌、发行替代令牌、写 `replaced_by_jti` 在**同一事务**内一次提交，移除中途 commit 边界。
  - 发行替代令牌抛错时**整体回滚**（旧令牌不被消费、不留半成品活跃令牌）。
  - 过期、用户停用等失败路径同样先回滚。
- **验证（Mock/SQLite 层）**：`tests/test_refresh_rotation_atomicity.py` 5 例：已轮换令牌不可二次轮换、
  8 线程并发只有 1 次成功且仅 1 枚活跃替代、发行抛错整体回滚且随后可正常恢复、停用用户不消费令牌、
  被篡改令牌不影响真实令牌。
- **验证（真实 PostgreSQL 隔离库，** 真正依赖层 **）**：`docs/upgrades/2026-10-03/w02_postgres_concurrency.py`
  在隔离库 `ybt_upgrade_w02_iso`（新建，绝不触碰业务库）上用 20 条独立连接并发轮换同一 refresh：

  ```json
  { "ok": true, "threads": 20, "successful_rotations": 1, "losing_attempts": 19,
    "distinct_successors": 1, "active_replacements": 1,
    "original_has_successor": true, "replay_after_rotation": "rejected" }
  ```

  前置缺陷证据：`docs/reviews/2026-10-03/backend-review.md` BA04（两枚有效替代令牌）。
- **回归**：`pytest tests/test_governance.py tests/test_release_hardening.py tests/test_outbound_authorization.py`
  → **40 passed**（API 层登录/刷新/登出链路未受影响）。

### 发布与回滚

- 无需数据库迁移（未改表结构）。
- 回滚方式：回退该提交即可；`create_session(commit=False)` 为新增可选参数，旧调用方行为不变。
- 已知边界：重放与并发在同一错误码下返回，避免向攻击者泄露"令牌是否存在"；token family/设备会话
  的更进一步治理（见 B14/用户生命周期）仍属后续工作包。

### 已知限制（待验证）

- 未验证跨主机/多副本部署下的时钟偏差影响（令牌 `expires_at` 由应用生成）。
- 未实现 token family 级联撤销（当前为单令牌占用语义）。
