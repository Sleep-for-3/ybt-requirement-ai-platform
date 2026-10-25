/**
 * 字段覆盖核对契约：三类要分开讲、只读不补字段、界面不能暗示"一键补齐"。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const page = readFileSync(join(root, "app", "projects", "[projectId]", "readiness", "page.tsx"), "utf8");
const lib = readFileSync(join(root, "lib", "field-coverage.ts"), "utf8");
const service = readFileSync(
  join(root, "..", "backend", "app", "services", "requirement_field_coverage.py"),
  "utf8",
);
const api = readFileSync(join(root, "..", "backend", "app", "api", "requirements.py"), "utf8");

test("界面按三类分开展示未覆盖字段，并带只读声明", () => {
  assert.match(page, /aria-label="字段覆盖核对"/);
  assert.match(page, /fieldCoverageHeadline\(fieldCoveragePayload\)/);
  assert.match(page, /FIELD_COVERAGE_BUCKETS\.map\(/);
  assert.match(page, /data-coverage-bucket=\{bucket\}/);
  assert.match(page, /fieldCoverageRowText\(row\)/);
  assert.match(page, /\{FIELD_COVERAGE_DISCLAIMER\}/);
  assert.match(page, /field-coverage\?sample=200/);
  // 不能出现"一键补齐/自动补字段"这类诱导文案。
  assert.doesNotMatch(page, /一键补齐|自动补字段|补全缺失字段/);
});

test("三类标签由服务端给、前端只按 bucket 渲染，说明文字区分三类", () => {
  assert.match(lib, /export const FIELD_COVERAGE_BUCKETS: FieldCoverageBucket\[\] = \["mapped", "script_only", "unreferenced"\]/);
  assert.match(lib, /bucket_labels: Record<FieldCoverageBucket, string>/);
  assert.match(lib, /bucket_hints: Record<FieldCoverageBucket, string>/);
  assert.match(lib, /模板要求填、有集市映射/);
  assert.match(lib, /FIELD_COVERAGE_DISCLAIMER = "覆盖核对只列事实：不改需求、不补字段/);
  // 三类的说明文字由服务端口径给出，前端不自己编。
  assert.match(service, /"mapped": "模板要求填，且有集市映射"/);
  assert.match(service, /"script_only": "脚本血缘里出现过，但没纳入需求"/);
  assert.match(service, /"unreferenced": "既无集市映射、也无脚本血缘"/);
});

test("服务端只读：按 scope、集市映射、脚本血缘三处事实分类，且不写库", () => {
  assert.match(service, /COVERAGE_VERSION = "requirement-field-coverage-v1"/);
  assert.match(service, /MartToYbtMapping\.target_field_id\.in_\(field_ids\)/);
  assert.match(service, /LineageNode\.target_field_id\.in_\(field_ids\)/);
  assert.doesNotMatch(service, /db\.add\(|db\.commit\(|db\.flush\(|\.delete\(/);
  assert.match(api, /@router\.get\("\/projects\/\{project_id\}\/requirements\/\{requirement_id\}\/field-coverage"\)/);
  assert.match(api, /except CoverageError as error:/);
});
