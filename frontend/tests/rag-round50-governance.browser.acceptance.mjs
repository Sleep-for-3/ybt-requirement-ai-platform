import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright";

const baseUrl = process.env.RAG_ROUND50_FRONTEND || "http://127.0.0.1:18688";
const fixtureBuildIdentity = {
  app_commit: "round50-current-source",
  build_time: "2026-11-17T00:00:00+08:00",
  schema_head: "synthetic-round50",
};
const output = path.resolve(process.argv[2]);
await mkdir(output, { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(30000);
const checks = [];
const apiResponses = [];
const unexpectedExternalRequests = [];

const taskSnapshot = (taskId) => ({
  task: {
    id: taskId,
    project_id: 3,
    objective: "合成验收：确认撤回资料与不可用原文的展示边界",
    status: "completed",
    created_at: "2026-11-17T00:00:00Z",
    finished_at: "2026-11-17T00:01:00Z",
    counts: { evidence: 1, artifacts: 1, steps: 1 },
    model_metadata: {},
  },
  steps: [],
  artifacts: [{
    id: 901,
    artifact_type: "knowledge_answer",
    title: "合成依据核验",
    status: "confirmed",
    summary: {
      answer: "合成结论：该版本已撤回，仅用于历史核验。",
      answer_status: "grounded",
      citations: [{
        title: "合成撤回版本材料",
        document_id: 903,
        document_version_id: 904,
        source_type: "knowledge",
        source_kind: "reference_material",
        quote: "合成解析证据仍可阅读。",
        usage: "cited",
        locator: { paragraph_index: 1 },
      }],
    },
  }],
});

await page.addInitScript(() => {
  sessionStorage.setItem("ybt:access-token", "synthetic-round50-access");
  sessionStorage.setItem("ybt:refresh-token", "synthetic-round50-refresh");
});

await page.route("**/*", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  if (!["127.0.0.1", "localhost"].includes(url.hostname)) {
    unexpectedExternalRequests.push(url.origin);
    await route.abort();
    return;
  }
  if (!url.pathname.includes("/api/")) {
    await route.continue();
    return;
  }

  const pathName = url.pathname.slice(url.pathname.indexOf("/api/") + 4).replace(/^\/+/, "");
  let status = 200;
  let body = {};
  if (pathName === "version") {
    body = {
      component: "api",
      ...fixtureBuildIdentity,
    };
  } else if (pathName === "auth/me") {
    body = {
      user_id: 950,
      username: "round50-synthetic-viewer",
      display_name: "合成只读用户",
      project_memberships: [{ project_id: 3, project_role: "project_viewer", status: "active" }],
      effective_project_permissions: { "3": ["project.view", "task.read", "knowledge.search"] },
      institution_memberships: [],
      capabilities: {},
    };
  } else if (pathName === "projects") {
    body = [{ id: 3, name: "Round50 隔离合成项目", project_status: "active" }];
  } else if (pathName === "projects/3/jobs/summary") {
    body = { active_count: 0, items: [] };
  } else if (pathName === "projects/3/agent/tasks") {
    body = [{
      id: 88,
      project_id: 3,
      objective: "合成撤回版本核验",
      status: "completed",
      created_at: "2026-11-17T00:00:00Z",
      result_brief: { kind: "answer", headline: "仅供历史核验" },
      counts: { evidence: 1 },
    }];
  } else if (pathName === "agent/tasks/77") {
    status = 404;
    body = { detail: "Resource not found" };
  } else if (pathName === "agent/tasks/88") {
    body = taskSnapshot(88);
  } else if (pathName === "projects/3/agent/tasks/88/diagnostics") {
    status = 403;
    body = { detail: "Resource not found" };
  } else if (pathName === "knowledge/documents/903/preview") {
    body = {
      document_id: 903,
      project_id: 3,
      document_version_id: 904,
      version_no: 2,
      file_name: "synthetic-withdrawn.txt",
      file_type: "txt",
      parse_status: "success",
      lifecycle_status: "withdrawn",
      warnings: ["该版本已撤回，仅供历史核验，不应作为现行依据。"],
      blocks: [{
        block_id: "knowledge-unit-905",
        block_type: "paragraph",
        knowledge_unit_id: 905,
        text: "合成解析证据仍可阅读。",
        locator: { paragraph_index: 1 },
      }],
    };
  } else if (pathName === "knowledge/documents/903/content") {
    status = 404;
    body = { detail: "Resource not found" };
  } else if (pathName.startsWith("auth/")) {
    body = { success: true };
  } else {
    body = [];
  }

  apiResponses.push({ path: pathName, method: request.method(), status });
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
});

try {
  await page.goto(`${baseUrl}/agent?projectId=3`);
  await page.getByRole("combobox", { name: "当前项目" }).waitFor();
  await page.getByText("合成撤回版本核验", { exact: true }).waitFor();
  await page.getByRole("button", { name: "新建任务" }).click();
  const createTaskButton = page.getByRole("button", { name: /创建并执行任务/ });
  await createTaskButton.waitFor();
  assert.equal(await createTaskButton.isDisabled(), true);
  await page.getByText("当前账号没有创建任务的权限，请联系项目负责人。", { exact: true }).waitFor();
  checks.push("synthetic_read_only_project_loaded_without_real_api");
  checks.push("read_only_create_task_entry_is_visible_but_submission_is_disabled");

  await page.goto(`${baseUrl}/agent?taskId=77&projectId=3`);
  await page.getByText("结果加载失败", { exact: true }).waitFor();
  await page.getByText("资源不存在或不可见", { exact: true }).waitFor();
  assert.equal(await page.getByText(/private storage|Resource not found|\/srv\//i).count(), 0);
  await page.screenshot({ path: path.join(output, "cross-project-hidden-404.png"), fullPage: true });
  checks.push("cross_project_task_404_is_safe_and_actionable");

  await page.goto(`${baseUrl}/agent?taskId=88&projectId=3`);
  await page.getByRole("button", { name: /查看原文/ }).waitFor();
  await page.getByRole("button", { name: /查看原文/ }).click();
  const dialog = page.getByRole("dialog", { name: "文档证据" });
  await dialog.waitFor();
  await dialog.getByText("该版本已撤回，仅供历史核验，不应作为现行依据。", { exact: true }).waitFor();
  await dialog.getByText("原文暂不可用；下方仍可核验已解析证据。", { exact: true }).waitFor();
  await dialog.getByText("合成解析证据仍可阅读。", { exact: true }).waitFor();
  await page.screenshot({ path: path.join(output, "withdrawn-source-unavailable-desktop.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, "withdrawn-source-unavailable-mobile.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await dialog.waitFor({ state: "hidden" });
  checks.push("withdrawn_warning_and_unavailable_original_keep_parsed_evidence");
  checks.push("governance_error_states_fit_mobile_and_dialog_closes");

  assert.deepEqual(unexpectedExternalRequests, []);
  assert.equal(apiResponses.some((item) => item.status >= 500), false);
} catch (error) {
  await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  throw error;
} finally {
  await writeFile(path.join(output, "results.json"), JSON.stringify({
    evidence_tier: "isolated_production_frontend_with_synthetic_intercepted_api",
    source_is_synthetic: true,
    holdout: false,
    checks,
    api_responses: apiResponses,
    unexpected_external_requests: unexpectedExternalRequests,
    external_provider_requests: 0,
    application_data_mutations: 0,
  }, null, 2));
  await browser.close();
}
