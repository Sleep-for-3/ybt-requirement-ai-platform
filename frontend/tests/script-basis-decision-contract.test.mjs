import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const libPath = new URL("../lib/script-basis-freshness.ts", import.meta.url);
const pagePath = new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url);
const servicePath = new URL(
  "../../backend/app/services/requirement_script_basis_decision.py",
  import.meta.url,
);

test("三种处置决定都有，且需要原因的两档被标出来", async () => {
  const lib = await readFile(libPath, "utf8");
  assert.match(lib, /key: "follow_planned"/);
  assert.match(lib, /key: "defer"/);
  assert.match(lib, /key: "reject_change"/);
  assert.match(lib, /key: "defer",\s+label: "复核后暂不跟随",\s+requiresNote: true/);
  assert.match(lib, /key: "reject_change",\s+label: "认为新脚本有误，需回退",\s+requiresNote: true/);
  assert.match(lib, /key: "follow_planned",\s+label: "已排期跟随新脚本",\s+requiresNote: false/);
});

test("决定文案带时间与原因——谁在什么时候决定暂不跟随就是审计事实", async () => {
  const lib = await readFile(libPath, "utf8");
  assert.match(lib, /decision\.decision_label \|\| decision\.decision/);
  assert.match(lib, /decision\.decided_at \? `（\$\{formatDecisionTime\(decision\.decided_at\)\}）`/);
  assert.match(lib, /decision\.note \? `：\$\{decision\.note\}`/);
  assert.match(lib, /return "时间未知"/);
});

test("看板登记决定后重新拉取新鲜度，且不改任何内容", async () => {
  const page = await readFile(pagePath, "utf8");
  assert.match(page, /\/requirements\/" \+ freshnessFor\.requirement_id \+ "\/script-basis-decisions/);
  assert.match(page, /script_file_id: version\.script_file_id/);
  assert.match(page, /frozen_version_id: version\.version_id/);
  assert.match(page, /latest_version_id: version\.latest_version_id/);
  assert.match(page, /必须写明原因/);
  assert.match(page, /await reloadFreshness\(\)/);
  assert.match(page, /DECISION_BADGE\[version\.decision\.decision\]/);
  // 只登记决定：页面不得在这里发起冻结或生成。
  assert.doesNotMatch(page, /recordDecision[\s\S]{0,400}freeze-and-export/);
});

test("服务端只登记决定，不重冻结、不改正文、不关缺口", async () => {
  const service = await readFile(servicePath, "utf8");
  assert.match(service, /DECISION_CHOICES = \("follow_planned", "defer", "reject_change"\)/);
  assert.match(service, /NOTE_REQUIRED = \("defer", "reject_change"\)/);
  assert.match(service, /if decision in NOTE_REQUIRED and not \(note or ""\)\.strip\(\)/);
  assert.doesNotMatch(service, /freeze_draft/);
  assert.doesNotMatch(service, /create_script_requirements/);
  assert.doesNotMatch(service, /status = "resolved"/);
});
