import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const pagePath = path.join(
  process.cwd(),
  "app",
  "projects",
  "[projectId]",
  "readiness",
  "page.tsx",
);
const page = readFileSync(pagePath, "utf8");

test("批量导出必须整体预检：版本与内容哈希都随清单提交", () => {
  assert.match(page, /requirements\/exports-batch/);
  assert.match(page, /expected_version: item\.requirement_version/);
  assert.match(page, /expected_hash: item\.current_content_hash/);
  assert.match(page, /内容哈希还没返回/);
  assert.match(page, /本次没有冻结任何需求/);
});

test("批量入口要能多选，且默认折叠为一条 zip + 清单", () => {
  assert.match(page, /aria-label=\{`选择需求 \$\{item\.name\}`\}/);
  assert.match(page, /批量冻结并导出（\$\{selected\.length\}）/);
  assert.match(page, /全选/);
  assert.match(page, /manifest\.json/);
  assert.match(page, /任何一条不一致就一条都不冻结/);
});

test("结果必须报告条目数、新建快照数与压缩包哈希", () => {
  assert.match(page, /x-requirement-batch-items/);
  assert.match(page, /x-requirement-batch-snapshots-created/);
  assert.match(page, /x-requirement-batch-file-sha256/);
  assert.match(page, /aria-label="批量导出结果"/);
  assert.match(page, /本次新建快照/);
});

test("导出格式与版式必须与后端契约一致，不允许前端自造", () => {
  assert.match(page, /form\.append\("format", "xlsx"\)/);
  assert.match(page, /form\.append\("layout", "survey"\)/);
  assert.doesNotMatch(page, /layout: "standard"/);
  assert.match(page, /uploadFormDownload/);
});
