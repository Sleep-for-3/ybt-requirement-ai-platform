// 交付复核清单契约：能按状态/关键字筛、只读元数据、不把"复核不了"说成"不能交付"。
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const pageUrl = new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url);
const libUrl = new URL("../lib/replay-manifest.ts", import.meta.url);
const serviceUrl = new URL("../../backend/app/services/requirement_replay_manifest.py", import.meta.url);
const apiUrl = new URL("../../backend/app/api/requirements.py", import.meta.url);

async function read(url) {
  return readFile(url, "utf8");
}

test("看板有复核清单入口，调的是只读端点", async () => {
  const page = await read(pageUrl);
  assert.match(page, /aria-label="打开复核清单"/);
  assert.match(page, /aria-label="交付复核清单"/);
  assert.match(page, /\/projects\/\$\{projectId\}\/replay-manifest\?/);
  assert.match(page, /apiGet<ReplayManifestPayload>/);
});

test("清单有三种状态的筛选与关键字查询", async () => {
  const page = await read(pageUrl);
  assert.match(page, /aria-label="复核状态全部"/);
  assert.match(page, /aria-label=\{`复核状态 \$\{option\.label\}`\}/);
  assert.match(page, /aria-label="复核清单关键字"/);
  assert.match(page, /aria-label="按关键字查复核清单"/);
  // 行级属性：浏览器脚本与人工核对都靠它定位"哪一份产物、什么状态"。
  assert.match(page, /data-artifact-id=\{item\.artifact_id\}/);
  assert.match(page, /data-replay-state=\{item\.replay_state\}/);
  assert.match(page, /params\.set\("state", nextState\)/);
});

test("文案把「复核不了」说清楚：不是通过，也不是不能交付", async () => {
  const [page, lib] = await Promise.all([read(pageUrl), read(libUrl)]);
  assert.match(page, /aria-label="复核清单免责"/);
  assert.match(lib, /不读文件、不重放、不写库/);
  assert.match(lib, /「仅旧渲染器」不等于不能交付/);
  const joined = `${page}\n${lib}`;
  assert.doesNotMatch(joined, /全部通过/);
  assert.doesNotMatch(joined, /可以交付了/);
  assert.doesNotMatch(joined, /自动补齐/);
});

test("服务端只读、facets 用全量算、判定与交付审计同一套", async () => {
  const service = await read(serviceUrl);
  assert.match(service, /MANIFEST_VERSION = "requirement-replay-manifest-v1"/);
  assert.match(service, /from app\.services\.requirement_export_stability import/);
  assert.match(service, /def manifest_state\(/);
  assert.match(service, /def build_replay_manifest\(/);
  // facets 必须在筛选之前累计，否则"历史产物共几份"会随筛选漂移。
  const facetIndex = service.indexOf("for entry in entries:");
  const filterIndex = service.indexOf('if state_filter and entry["replay_state"] != state_filter:');
  assert.ok(facetIndex >= 0 && filterIndex > facetIndex, "facets 应先于筛选累计");
  assert.doesNotMatch(service, /db\.add\(/);
  assert.doesNotMatch(service, /db\.commit\(/);
  assert.doesNotMatch(service, /\.delete\(/);
  assert.match(service, /不读文件、不重放、不写库/);
});

test("端点鉴权、非法筛选 422、limit 有上限", async () => {
  const api = await read(apiUrl);
  assert.match(api, /@router\.get\("\/projects\/\{project_id\}\/replay-manifest"\)/);
  assert.match(api, /require_project_permission\(project_id, "project\.view"\)/);
  assert.match(api, /manifest_filter_invalid/);
  assert.match(api, /limit: int = Query\(100, ge=0, le=500\)/);
});
