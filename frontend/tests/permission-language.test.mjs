import assert from "node:assert/strict";
import test from "node:test";
import { groupPermissions, institutionRoleLabel, permissionLabel, projectRoleLabel } from "../lib/permission-language.mjs";

test("permission presentation uses Chinese labels while retaining unknown codes", () => {
  assert.equal(institutionRoleLabel("institution_admin"), "机构管理员");
  assert.equal(projectRoleLabel("business_analyst"), "业务分析人员");
  assert.equal(permissionLabel("business.edit"), "编辑业务口径");
  assert.equal(permissionLabel("future.permission"), "未配置中文名称");
  assert.deepEqual(groupPermissions(["future.permission"])[0].permissions[0], { code: "future.permission", label: "未配置中文名称", configured: false });
});
