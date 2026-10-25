import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const libPath = new URL("../lib/delivery-status.ts", import.meta.url);
const pagePath = new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url);
const servicePath = new URL(
  "../../backend/app/services/requirement_delivery_status.py",
  import.meta.url,
);

test("待采纳候选数来自服务端，页面自己不算", async () => {
  const lib = await readFile(libPath, "utf8");
  assert.match(lib, /pending_candidate_count\?: number;/);
  assert.match(lib, /count > 0 \? `\$\{count\} 条待采纳` : "无待采纳"/);
  const service = await readFile(servicePath, "utf8");
  assert.match(service, /RequirementGenerationItem\.status == "completed"/);
  assert.match(service, /RequirementGenerationItem\.decision\.is_\(None\)/);
  assert.match(service, /RequirementGenerationItem\.decision == "pending"/);
  assert.match(service, /"pending_candidate_count": pending_candidates\.get\(row\.id, 0\)/);
});

test("看板有「待采纳」列，并能直接跳到工作台那条需求", async () => {
  const page = await readFile(pagePath, "utf8");
  assert.match(page, /<th className="py-1 pr-3 font-medium">待采纳<\/th>/);
  assert.match(page, /pendingCandidateText\(item\)/);
  assert.match(page, /aria-label=\{`去工作台采纳 \$\{item\.target_table_code \|\| item\.name\} 的候选`\}/);
  // 深链必须带表、场景与需求三者：同表可能有多条需求，只带 requirementId 会打开另一条。
  assert.match(page, /\/workspace\?projectId=\$\{projectId\}&tableId=\$\{item\.target_table_id/);
  assert.match(page, /&scenarioId=\$\{item\.scenario_id/);
  assert.match(page, /&requirementId=\$\{item\.requirement_id\}/);
  // 页面不得自行按条目统计候选数（数据只有服务端知道）；读服务端字段渲染是允许的。
  assert.doesNotMatch(page, /items\.filter\([^)]*decision/);
  assert.doesNotMatch(page, /待采纳.*\.length/);
});

test("阻断/失败条目与已采纳条目都不算待采纳", async () => {
  const service = await readFile(servicePath, "utf8");
  const start = service.indexOf("pending_candidates: dict[int, int] = {}");
  assert.ok(start > 0, "服务里找不到待采纳聚合");
  const block = service.slice(start, start + 1400);
  assert.match(block, /status == "completed"/);
  assert.doesNotMatch(block, /status in \("completed", "blocked"\)/);
  assert.doesNotMatch(block, /decision == "adopted"/);
});

test("待采纳数与缺口数分列两栏，不互相顶替", async () => {
  const page = await readFile(pagePath, "utf8");
  const pendingIndex = page.indexOf(">待采纳</th>");
  const gapIndex = page.indexOf(">打开缺口</th>");
  assert.ok(pendingIndex > 0 && gapIndex > 0);
  assert.ok(pendingIndex < gapIndex, "待采纳列应在打开缺口列之前");
});

test("待采纳深链会直接把第一条待采纳候选打开（只一次）", async () => {
  const page = await readFile(pagePath, "utf8");
  const workspace = await readFile(
    new URL("../components/requirement-workspace/RequirementWorkspace.tsx", import.meta.url),
    "utf8",
  );
  const panel = await readFile(
    new URL("../components/requirement-workspace/RequirementGenerationPanel.tsx", import.meta.url),
    "utf8",
  );
  // 看板链接带意图参数，否则落点只会打开需求、用户还要自己找轮次。
  assert.match(page, /&pendingCandidate=1`/);
  assert.match(workspace, /params\.get\("pendingCandidate"\) === "1"/);
  assert.match(workspace, /autoOpenPending=\{autoOpenPendingCandidate\}/);
  // 面板：一次性守卫 + 先切"待采用" + 打开第一条待采纳候选。
  assert.match(panel, /autoOpenPending\?:boolean;/);
  assert.match(panel, /const autoOpenApplied=useRef\(false\);/);
  assert.match(panel, /if\(!autoOpenPending\|\|autoOpenApplied\.current\)return;/);
  assert.match(panel, /setItemFilter\("pending"\);/);
  assert.match(panel, /const first=pendingCandidates\[0\];/);
  assert.match(panel, /setCandidateId\(first\.id\);/);
});
