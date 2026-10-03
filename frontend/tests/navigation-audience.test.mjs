/**
 * B16: UAT and audit entries are business capabilities, not administrator capabilities.
 *
 * They used to be nav items with audience "admin", so a reviewer or auditor without the
 * administrator capability never saw 验收管理 / 审计 even when their project role granted
 * uat.view / audit.read.
 */
import test from "node:test";
import assert from "node:assert/strict";

import { canViewNavigationAudience, navigationAccessForProject } from "../lib/navigation-contract.mjs";

function auth(permissions, capabilities = {}) {
  return { capabilities, effective_project_permissions: { "7": permissions } };
}

test("审计员凭 audit.read 看到审计入口，无需管理员", () => {
  const access = navigationAccessForProject(auth(["audit.read", "project.view"]), 7);
  assert.equal(access.isAdmin, false);
  assert.equal(access.canViewAudit, true);
  assert.equal(canViewNavigationAudience("audit", access), true);
  assert.equal(canViewNavigationAudience("admin", access), false);
});

test("验收人员凭 uat.view 看到验收入口，无需管理员", () => {
  const access = navigationAccessForProject(auth(["uat.view", "project.view"]), 7);
  assert.equal(access.isAdmin, false);
  assert.equal(access.canViewUat, true);
  assert.equal(canViewNavigationAudience("uat", access), true);
  assert.equal(canViewNavigationAudience("admin", access), false);
});

test("uat.manage / uat.execute 同样可见（执行 UAT 不需要管理员）", () => {
  for (const permission of ["uat.manage", "uat.execute"]) {
    const access = navigationAccessForProject(auth([permission]), 7);
    assert.equal(canViewNavigationAudience("uat", access), true, permission);
  }
});

test("无业务权限时看不到验收与审计", () => {
  const access = navigationAccessForProject(auth(["project.view"]), 7);
  assert.equal(access.canViewUat, false);
  assert.equal(access.canViewAudit, false);
  assert.equal(canViewNavigationAudience("uat", access), false);
  assert.equal(canViewNavigationAudience("audit", access), false);
});

test("管理员仍能看到两者（不受影响）", () => {
  const access = navigationAccessForProject(auth([], { can_view_admin: true }), 7);
  assert.equal(canViewNavigationAudience("uat", access), true);
  assert.equal(canViewNavigationAudience("audit", access), true);
});

test("技术/巡检 audience 行为不变", () => {
  const access = navigationAccessForProject(auth(["technical.edit"]), 7);
  assert.equal(canViewNavigationAudience("technical", access), true);
  assert.equal(canViewNavigationAudience(undefined, access), true);
  assert.equal(canViewNavigationAudience("cockpit", access), false);
});

test("没有选择项目时按权限为空处理", () => {
  const access = navigationAccessForProject(auth(["uat.view"]), null);
  assert.equal(access.canViewUat, false);
  assert.equal(access.canViewAudit, false);
});
