import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pagePath = new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url);
const apiPath = new URL("../../backend/app/api/requirements.py", import.meta.url);

test("「已排期跟随新脚本」必须真的排出重新生成任务", async () => {
  const page = await readFile(pagePath, "utf8");
  assert.match(page, /if \(decision === "follow_planned"\)/);
  assert.match(page, /\/requirements\/" \+ target\.requirement_id \+ "\/script-basis-regenerate"/);
  assert.match(page, /form\.append\("script_file_id", String\(version\.script_file_id\)\)/);
  assert.match(page, /form\.append\("expected_version", String\(target\.requirement_version\)\)/);
  assert.match(page, /form\.append\("expected_hash", target\.current_content_hash\)/);
  assert.match(page, /form\.append\("sections", "business,lineage"\)/);
  // 提示必须说清"任务已排、正文还要采纳、依据不会自动切换"，否则会被当成一键切换依据。
  assert.match(page, /正文仍需在生成轮次里逐字段采纳；脚本依据不会自动切换。/);
  assert.match(page, /aria-label="复核决定结果"/);
});

test("后端重新生成只建输入与任务，不采纳、不冻结、不改脚本依据", async () => {
  const api = await readFile(apiPath, "utf8");
  const start = api.indexOf('"/projects/{project_id}/requirements/{requirement_id}/script-basis-regenerate"');
  assert.ok(start > 0, "找不到 script-basis-regenerate 路由");
  const tail = api.slice(start);
  const end = tail.indexOf("\n@router.");
  const body = end > 0 ? tail.slice(0, end) : tail;

  assert.match(body, /指定脚本不在本需求的冻结依据里/);
  assert.match(body, /没有可重新生成的绑定字段/);
  assert.match(body, /PrepareGenerationInput\(/);
  assert.match(body, /idempotency_key=f"script-basis-regen-/);
  // 治理边界：这条路径绝不能顺手采纳候选、冻结快照或改写脚本依据。
  assert.doesNotMatch(body, /adopt/i);
  assert.doesNotMatch(body, /freeze_draft/);
  assert.doesNotMatch(body, /script-basis-confirm/);
  assert.doesNotMatch(body, /content_version = /);
});
