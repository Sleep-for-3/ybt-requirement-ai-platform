import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const doc = readFileSync("components/requirement-workspace/DocumentPreview.tsx", "utf8");
const workspace = readFileSync("components/requirement-workspace/RequirementWorkspace.tsx", "utf8");
const api = readFileSync("lib/api.ts", "utf8");

test("需求模式的导出必须先冻结：预检提供冻结导出回调与格式/版式选择", () => {
  assert.match(doc, /onFreezeAndExport\?\.?: \(options: \{ format: "xlsx" \| "docx"; layout: "survey" \| "standard" \}\) => Promise<ExportOutcome \| null>/);
  assert.match(doc, /继续导出会先把当前内容冻结为快照，再按该快照导出——同一内容重复导出得到同一份文件。/);
  assert.match(doc, /aria-label="导出格式"/);
  assert.match(doc, /aria-label="导出版式"/);
});

test("一表通调研表式只允许 xlsx，前端必须先行拦住而不是交给后端报错", () => {
  assert.match(doc, /const surveyBlocked = exportLayout === "survey" && exportFormat !== "xlsx";/);
  assert.match(doc, /disabled=\{exporting \|\| freezing \|\| surveyBlocked\}/);
  assert.match(doc, /一表通调研表式只支持 xlsx；要导出 Word 请选平台内置版式。/);
});

test("导出后必须把快照号/产物号/文件 hash 交给评审", () => {
  assert.match(doc, /aria-label="导出身份"/);
  assert.match(doc, /快照 #\{exportOutcome\.snapshotId\}/);
  assert.match(doc, /exportOutcome\.snapshotCreated \? "本次新建" : "内容未变，复用已有快照"/);
  assert.match(doc, /产物 #\{exportOutcome\.artifactId\}/);
  assert.match(doc, /exportOutcome\.fileSha256/);
  assert.match(doc, /凭快照号可重新导出同一份文件；改动内容需要新的快照。/);
});

test("工作台用乐观锁字段调用 freeze-and-export，并把响应头转成身份结论", () => {
  assert.match(workspace, /requirements\/\$\{requirement\.id\}\/freeze-and-export/);
  assert.match(workspace, /form\.append\("expected_version", String\(requirement\.version\)\);/);
  assert.match(workspace, /form\.append\("expected_hash", contentHash\);/);
  assert.match(workspace, /file\.headers\["x-requirement-snapshot-id"\]/);
  assert.match(workspace, /file\.headers\["x-requirement-snapshot-created"\] === "true"/);
  assert.match(workspace, /file\.headers\["x-requirement-render-artifact-id"\]/);
});

test("缺内容 hash 时不得导出：宁可报错也不能导出无法复现的编辑态文件", () => {
  assert.match(workspace, /if \(!contentHash\) \{ setError\("当前内容尚未加载完成，无法冻结导出。"\); return null; \}/);
});

test("下载辅助必须透出交付身份响应头，且只透出白名单", () => {
  assert.match(api, /const DOWNLOAD_IDENTITY_HEADERS = \[/);
  for (const header of [
    "x-requirement-render-artifact-id",
    "x-requirement-rendered-file-sha256",
    "x-requirement-renderer-version",
    "x-requirement-snapshot-id",
    "x-requirement-snapshot-created",
    "x-requirement-snapshot-hash",
  ]) {
    assert.ok(api.includes(`"${header}"`), `identity header ${header} must be forwarded`);
  }
  assert.match(api, /headers: downloadIdentityHeaders\(response\),/);
});
