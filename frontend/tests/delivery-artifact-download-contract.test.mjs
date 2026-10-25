import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const page = readFileSync(
  new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url),
  "utf8",
);

test("项目看板提供最近导出产物的下载入口", () => {
  assert.match(page, /aria-label=\{`下载最近导出产物 \$\{item\.target_table_code \|\| item\.name\}`\}/);
  assert.match(page, /下载产物 #\$\{item\.last_artifact\.id\}/);
  assert.match(page, /item\.last_artifact \? \(/);
});

test("下载走已存产物端点，不重新渲染", () => {
  assert.match(page, /import \{[^}]*apiDownload[^}]*\} from "@\/lib\/api";/s);
  assert.match(
    page,
    /apiDownload\(\s*`\/projects\/\$\{projectId\}\/requirements\/\$\{item\.requirement_id\}\/render-artifacts\/\$\{item\.last_artifact\.id\}\/download`,\s*\)/,
  );
  assert.doesNotMatch(page, /render-artifacts\/\$\{item\.last_artifact\.id\}\/preview/);
  assert.doesNotMatch(page, /\/exports\?source_kind/);
});

test("下载中禁用按钮，避免同一份产物重复请求", () => {
  assert.match(page, /disabled=\{downloadingId === item\.requirement_id\}/);
  assert.match(page, /下载中…/);
  assert.match(page, /if \(!item\.last_artifact \|\| downloadingId !== null\) return;/);
});

test("失败要把'文件被清理或校验失败'与'没导出过'区分开", () => {
  assert.match(page, /下载产物失败：文件可能已被清理或完整性校验未通过，请在导出面板重新导出。/);
  assert.match(page, /aria-label="产物下载结果"/);
  assert.match(page, /setArtifactNotice\(/);
});
