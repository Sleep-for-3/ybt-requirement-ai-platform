import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pageUrl = new URL("../app/projects/page.tsx", import.meta.url);
const contextUrl = new URL("../components/ProjectContext.tsx", import.meta.url);


test("project creation keeps a stable form element instead of reading currentTarget after await", async () => {
  const source = await readFile(pageUrl, "utf8");
  assert.match(source, /const formElement = event\.currentTarget;/);
  assert.match(source, /formElement\.reset\(\);/);
  assert.doesNotMatch(source, /event\.currentTarget\.reset\(\)/);
  assert.match(source, /client_request_id: requestId/);
  assert.match(source, /createClientId/);
});


test("project page exposes reversible suspend lifecycle rather than hard delete", async () => {
  const source = await readFile(pageUrl, "utf8");
  assert.match(source, /apiPatch<Project>\(`\/projects\/\$\{lifecycle\.project\.id\}\/status`/);
  assert.match(source, /停用项目/);
  assert.match(source, /恢复项目/);
  assert.match(source, /历史资料、版本、审核及交付记录全部保留/);
  assert.doesNotMatch(source, /apiDelete\(`\/projects/);
});


test("suspended projects leave normal project selection while remaining recoverable", async () => {
  const source = await readFile(contextUrl, "utf8");
  assert.match(source, /project_status \|\| "active"\) === "active"/);
  assert.match(source, /activeProjects\.map/);
});
