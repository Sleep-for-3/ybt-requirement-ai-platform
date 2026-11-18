import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const baseUrl = process.env.FRONTEND_URL;
const output = path.resolve(process.argv[2] || "../.local-run/rag-long-run/round-20261116-32/browser");
const buildIdentity = { app_commit: "round32-browser-fixture", build_time: "2026-11-16T20:00:00+08:00" };
assert.ok(baseUrl, "Set FRONTEND_URL to the isolated local production server.");
await mkdir(output, { recursive: false });

const task = {
  id: 31,
  project_id: 3,
  institution_id: 1,
  objective: "核对业务字段的填报依据",
  scenario_key: "knowledge_question",
  status: "completed",
  counts: { evidence: 1, skipped: 1, failed: 0 },
  created_at: "2026-11-16T10:00:00Z",
  finished_at: "2026-11-16T10:00:05Z",
};
const snapshot = {
  task,
  plan: { id: 1, version_no: 1, status: "completed", planner_source: "rule", steps: [] },
  steps: [
    {
      id: 1,
      step_key: "history",
      order_index: 0,
      tool_key: "search_decision_cases",
      reason: "历史案例作为补充资料",
      status: "skipped",
      required: false,
      gap_codes: ["no_historical_case", "optional_dependency_missing"],
      summary: {
        case_count: 0,
        cases: [],
        gaps: [{ code: "no_historical_case", message: "没有找到与该主体/场景匹配的历史人工决策案例；不得以历史经验替代监管依据。" }],
      },
    },
    {
      id: 2,
      step_key: "answer",
      order_index: 1,
      tool_key: "answer_knowledge_question",
      reason: "依据当前授权资料回答",
      status: "completed",
      required: true,
      gap_codes: [],
      summary: { answer: "已依据当前资料整理回答。" },
    },
  ],
  gaps: [
    { step_key: "history", code: "no_historical_case", message: "没有找到历史案例。" },
    { step_key: "answer", code: "optional_dependency_missing", message: "可选历史案例未提供。" },
  ],
  artifacts: [
    { id: 1, artifact_type: "answer", title: "问答结论", status: "completed", summary: { answer: "已依据当前资料整理回答。" } },
  ],
  decisions: [],
};

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const checks = [];
const apiRequests = [];
let failure = null;

await page.addInitScript(() => sessionStorage.setItem("ybt:access-token", "browser-acceptance-token"));
await page.route("**/api/**", async (route) => {
  const url = new URL(route.request().url());
  apiRequests.push({ origin: url.origin, path: url.pathname });
  const pathname = url.pathname.replace(/^\/api/, "");
  let body = {};
  if (pathname === "/auth/me") {
    body = {
      username: "browser-acceptance",
      display_name: "验收用户",
      project_memberships: [{ project_id: 3, project_role: "owner", status: "active" }],
      effective_project_permissions: { "3": ["task.read", "task.manage", "final.review"] },
    };
  } else if (pathname === "/projects") {
    body = [{ id: 3, name: "隔离浏览器验收项目", project_status: "active", institution_id: 1 }];
  } else if (pathname === "/projects/3/jobs/summary") {
    body = { active_count: 0, jobs: [] };
  } else if (pathname === "/version") {
    body = { component: "api", ...buildIdentity, schema_head: null };
  } else if (pathname === "/projects/3/agent/tasks") {
    body = [{ ...task, current_step_key: "answer", plan_version: 1 }];
  } else if (pathname === "/agent/tasks/31") {
    body = snapshot;
  }
  await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
});

try {
  await page.goto(`${baseUrl}/agent?projectId=3&taskId=31`);
  await page.getByText(task.objective, { exact: true }).waitFor({ timeout: 30000 });
  await page.getByRole("region", { name: "结论依据" }).waitFor();
  assert.equal(await page.getByText(/依据缺口（\d+）/).count(), 0);
  assert.equal(await page.getByText("可选历史案例未提供。", { exact: true }).count(), 0);
  checks.push("optional_case_absent_from_primary_evidence_gaps");

  await page.getByRole("button", { name: /^执行过程（/ }).click();
  await page.getByText("查找历史案例补充", { exact: true }).waitFor();
  await page.getByText("没有找到与该主体/场景匹配的历史人工决策案例；不得以历史经验替代监管依据。", { exact: true }).waitFor();
  assert.equal(await page.getByText("search_decision_cases", { exact: true }).count(), 0);
  checks.push("step_reason_and_safe_business_label_visible");

  await page.screenshot({ path: path.join(output, "optional-history-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, "optional-history-mobile.png"), fullPage: true });
  checks.push("mobile_390px_no_horizontal_overflow");
} catch (error) {
  failure = { name: error.name, message: String(error.message).slice(0, 800) };
  await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(
    path.join(output, "results.json"),
    JSON.stringify({ evidence_tier: "production_frontend_browser_mocked_api", checks, failure, apiRequests }, null, 2),
  );
  await browser.close();
}
