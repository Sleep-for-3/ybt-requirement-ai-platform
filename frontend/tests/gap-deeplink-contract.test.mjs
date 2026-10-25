import { readFileSync } from "node:fs";
import { strict as assert } from "node:assert";
import test from "node:test";

const root = new URL("../", import.meta.url);
const page = readFileSync(new URL("app/projects/[projectId]/readiness/page.tsx", root), "utf8");
const preview = readFileSync(new URL("components/requirement-workspace/DocumentPreview.tsx", root), "utf8");
const workspace = readFileSync(new URL("components/requirement-workspace/RequirementWorkspace.tsx", root), "utf8");
const service = readFileSync(new URL("../backend/app/services/requirement_delivery_status.py", root), "utf8");

test("gap dialog deep-links into the workspace with every id the workspace needs", () => {
  assert.ok(page.includes("在工作台打开"), "缺口摘要里必须有去工作台处理的入口");
  // 工作台是按 tableId + scenarioId + requirementId 还原需求的；少一个就会打开另一条需求。
  // 看板里有多条 /workspace 深链（待采纳、缺口摘要…），必须找到**带 fieldId 的那一条**：
  // 只比较第一条会把"缺口定位"接成"打开需求但不定位字段"。
  const hrefs = Array.from(page.matchAll(/`\/workspace\?projectId=\$\{projectId\}[^`]*`/g)).map(
    (match) => match[0],
  );
  assert.ok(hrefs.length > 0, "必须拼出 /workspace?... 深链");
  const pattern = hrefs.find((value) => value.includes("fieldId="));
  assert.ok(pattern, `没有任何一条深链带 fieldId：${hrefs.join(" | ")}`);
  for (const key of ["projectId", "tableId", "scenarioId", "requirementId", "fieldId"]) {
    assert.ok(pattern.includes(`${key}=`), `深链缺少 ${key}`);
  }
  assert.ok(page.includes("canDeepLink"), "缺 table/scenario 时不能给出不可用的链接");
  assert.ok(page.includes("无法定位"), "不能定位时要如实说明，而不是给一个打开错需求的链接");
});

test("backend exposes the ids used by the deep link", () => {
  assert.ok(service.includes('"target_table_id": target_table.get("id")'), "缺口摘要要带目标表 id");
  assert.ok(service.includes('"scenario_id": scenario.get("id")'), "缺口摘要要带场景 id");
});

test("workspace applies the deep-linked field once and focuses it", () => {
  assert.ok(workspace.includes('positiveId("fieldId")'), "工作台仍从 URL 读字段");
  assert.ok(workspace.includes("initialFocusFieldId"), "要把深链字段传给文档预览");
  assert.ok(preview.includes("initialFocusFieldId"), "文档预览要接收深链字段");
  assert.ok(preview.includes("initialFocusApplied"), "深链只应用一次，否则会反复把用户拉回该字段");
  assert.ok(preview.includes("focusField(initialFocusFieldId)"), "必须调用 focusField 才有高亮与滚动");
});
