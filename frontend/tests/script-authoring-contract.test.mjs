import { strict as assert } from "node:assert";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const pagePath = path.join(process.cwd(), "app", "projects", "[projectId]", "readiness", "page.tsx");
const page = readFileSync(pagePath, "utf8");
const servicePath = path.join(process.cwd(), "..", "backend", "app", "services", "requirement_script_authoring.py");
const service = readFileSync(servicePath, "utf8");
const apiPath = path.join(process.cwd(), "..", "backend", "app", "api", "requirements.py");
const api = readFileSync(apiPath, "utf8");

test("一键建需只能出现在“脚本可建需且还没有需求”的表上", () => {
  assert.match(page, /item\.state === "script_ready" && !item\.requirement_count/);
  assert.match(page, /aria-label=\{`从脚本为 \$\{item\.table_code\} 建需`\}/);
  assert.match(page, /从脚本建需/);
});

test("前端必须先预检再建需，不能自己拼字段绑定", () => {
  const previewIndex = page.indexOf("/requirements/author-preview");
  const authorIndex = page.indexOf("/requirements/author-from-scripts");
  assert.ok(previewIndex > 0, "缺少预检调用");
  assert.ok(authorIndex > previewIndex, "建需调用必须在预检之后");
  assert.doesNotMatch(page, /field_bindings/);
  assert.doesNotMatch(page, /preview_hash:/);
});

test("建需成功必须说明“正文仍需生成候选并采纳”", () => {
  assert.match(page, /按同名规则绑定/);
  assert.match(page, /正文仍需到工作台生成候选并采纳/);
  assert.match(page, /不能一键建需：/);
  assert.match(page, /从脚本建需失败/);
  assert.match(page, /setCoverageReload\(\(value\) => value \+ 1\)/);
});

test("服务端复用脚本依据与模板校验，不绕开既有链路", () => {
  assert.match(service, /AUTHORING_VERSION = "requirement-script-authoring-v1"/);
  assert.match(service, /MAX_TABLES = 10/);
  assert.match(service, /script_preview\(/);
  assert.match(service, /create_script_requirements\(/);
  assert.match(service, /begin_nested\(\)/);
  assert.doesNotMatch(service, /freeze_draft|ensure_artifact|export_word/);
  assert.match(api, /author-preview/);
  assert.match(api, /author-from-scripts/);
  assert.match(api, /author_requirements_from_scripts/);
});

test("批量建需：可多选、上限 10 张、逐表回显结果", () => {
  assert.match(page, /aria-label=\{`选择监管表 \$\{item\.table_code\} 批量建需`\}/);
  assert.match(page, /全选可建需表（\$\{authorableVisible\.length\}）/);
  assert.match(page, /批量建需（\$\{authorSelected\.length\}）/);
  assert.match(page, /slice\(0, 10\)/);
  assert.match(page, /aria-label="批量建需结果"/);
  assert.match(page, /一次最多 10 张表；只绑"脚本输出列与监管字段同名"的字段，未绑字段留作缺口。/);
  assert.match(page, /未建（\$\{item\.reason \|\| "原因未返回"\}）/);
});

test("批量建需同样先预检再建需，不静默跳过不能建需的表", () => {
  const batchStart = page.indexOf("async function authorBatch()");
  assert.ok(batchStart > 0, "缺少 authorBatch");
  const batch = page.slice(batchStart, batchStart + 2600);
  const previewIndex = batch.indexOf("/requirements/author-preview");
  const authorIndex = batch.indexOf("/requirements/author-from-scripts");
  assert.ok(previewIndex > 0 && authorIndex > previewIndex, "批量路径也必须先预检");
  assert.match(batch, /不能自动建需，具体原因见下方逐表结果/);
  assert.doesNotMatch(batch, /field_bindings/);
});
