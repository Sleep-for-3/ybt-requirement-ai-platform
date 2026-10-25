import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const page = path.join(root, "app", "projects", "[projectId]", "readiness", "page.tsx");
const service = path.resolve(root, "..", "backend", "app", "services", "requirement_worklist_archive.py");
const api = path.resolve(root, "..", "backend", "app", "api", "requirements.py");
const main = path.resolve(root, "..", "backend", "app", "main.py");

test("派工清单提供「按监管表导出」入口，走服务端分装而不是前端切文件", () => {
  const source = readFileSync(page, "utf8");
  assert.match(source, /aria-label="按监管表导出待办清单"/);
  assert.match(source, /requirements-worklist\/archive\?limit=3000/);
  assert.match(source, /async function exportWorklistArchive\(\)/);
  // 分装必须由服务端完成：前端只下载一个 zip，不能在浏览器里按表切 CSV。
  assert.doesNotMatch(source, /groupBy\(|reduce\([^)]*target_table_code/);
});

test("服务端按表分组、清单不写生成时间（否则两次导出字节不同）", () => {
  const code = readFileSync(service, "utf8");
  assert.match(code, /ARCHIVE_VERSION = "requirement-worklist-archive-v1"/);
  assert.match(code, /FIXED_ZIP_DATE = \(2000, 1, 1, 0, 0, 0\)/);
  assert.match(code, /grouped\.setdefault\(code, \[\]\)\.append\(item\)/);
  assert.match(code, /_FALLBACK_TABLE = "未登记监管表"/);
  // 生成时间写进清单 = 同一份清单两次导出字节不同（round 24 已经踩过这个坑）。
  assert.doesNotMatch(code, /"generated_at"/);
  assert.doesNotMatch(code, /datetime\.now|time\.time\(/);
  // 只读：不写库、不冻结、不建候选。
  for (const forbidden of ["db.add(", "db.commit(", "freeze_draft", "create_script_requirements"]) {
    assert.ok(!code.includes(forbidden), `分装服务不应出现 ${forbidden}`);
  }
});

test("端点只读且三个身份头都加入 CORS expose_headers", () => {
  const endpoint = readFileSync(api, "utf8");
  assert.match(endpoint, /@router\.get\("\/projects\/\{project_id\}\/requirements-worklist\/archive"\)/);
  assert.match(endpoint, /build_worklist_archive\(payload\)/);
  assert.match(endpoint, /filename\*=UTF-8''\{quote\(file_name\)\}/, "中文文件名必须走 filename* 才能被浏览器识别");
  const headers = readFileSync(main, "utf8");
  for (const header of [
    "X-Requirement-Worklist-Tables",
    "X-Requirement-Worklist-Items",
    "X-Requirement-Worklist-File-Sha256",
  ]) {
    assert.ok(headers.includes(header), `${header} 必须加进 expose_headers，否则浏览器读不到`);
  }
});
