/**
 * 契约：批量"只重新冻结"必须是"冻结快照、不产生文件"。
 *
 * 真实场景：模板表级口径更新后，看板上十几条需求变成"快照落后于当前内容"（正文没改）。
 * 用户要的是把快照对齐，而不是再生成一批文件。这个契约守住四件事：
 *
 * 1. 页面发的是 `{requirement_id, expected_version, expected_hash}`，其中哈希只能取
 *    `current_content_hash`、版本只能取 `requirement_version`——不能在前端猜；
 * 2. 只调 `/requirements/refreeze-batch`，不走导出端点；
 * 3. 后端该端点不得调用渲染/打包（`_builtin_export_artifact`、`build_archive`）；
 * 4. 结果提示必须说明"没有生成任何文件"，并且结束后重新拉取交付状态。
 */

import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.dirname(fileURLToPath(import.meta.url));
const pagePath = path.join(root, "..", "app", "projects", "[projectId]", "readiness", "page.tsx");
const apiPath = path.join(root, "..", "..", "backend", "app", "api", "requirements.py");
const page = readFileSync(pagePath, "utf8");
const api = readFileSync(apiPath, "utf8");

function refreezeEndpointSlice() {
  const start = api.indexOf('"/projects/{project_id}/requirements/refreeze-batch"');
  assert.ok(start > 0, "后端必须有 refreeze-batch 端点");
  const rest = api.slice(start + 10);
  const next = rest.search(/\n@router\./);
  return next === -1 ? rest : rest.slice(0, next);
}

test("页面发的是服务端给的版本与内容哈希，不自己猜", () => {
  const body = page.slice(page.indexOf("async function refreezeSelected"));
  const call = body.slice(0, body.indexOf("async function downloadArtifact"));
  assert.match(call, /\/projects\/\$\{projectId\}\/requirements\/refreeze-batch/);
  assert.match(call, /expected_version: item\.requirement_version/);
  assert.match(call, /expected_hash: item\.current_content_hash/);
  assert.doesNotMatch(call, /expected_hash:\s*"0"\.repeat/);
  assert.doesNotMatch(call, /exports-batch/);
});

test("后端只冻结、不渲染也不打包", () => {
  const slice = refreezeEndpointSlice();
  assert.match(slice, /freeze_draft\(/);
  assert.doesNotMatch(slice, /_builtin_export_artifact\(/);
  assert.doesNotMatch(slice, /build_archive\(/);
  assert.match(slice, /本次未冻结任何需求/, "预检失败必须一条都不冻结");
});

test("按钮与结果提示说清后果，并在结束后刷新交付状态", () => {
  assert.match(page, /重新冻结这 \$\{selected\.length\} 条（不导出）/);
  assert.match(page, /aria-label="重新冻结结果"/);
  assert.match(page, /这次没有生成任何文件，需要文件请在导出面板单独导出。/);
  assert.match(page, /setDeliveryReload\(\(value\) => value \+ 1\)/);
  assert.match(page, /disabled=\{!selected\.length \|\| refreezeBusy\}/);
});
