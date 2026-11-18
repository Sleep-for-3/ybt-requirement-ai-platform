import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { createServer } from "node:http";
import path from "node:path";
import next from "next";
import { chromium } from "playwright";

const baseUrl = process.env.FRONTEND_URL || "http://127.0.0.1:18139";
const output = path.resolve(process.argv[2]);
const dev = process.argv.includes("--dev");
const distDir = dev ? ".next-round61-ux-dev" : ".next-round61-ux";
if (dev) {
  process.env.NEXT_PUBLIC_APP_COMMIT = "synthetic-ux-acceptance";
  process.env.NEXT_PUBLIC_BUILD_TIME = "2026-11-18T00:00:00Z";
}
process.env.NEXT_DIST_DIR = distDir;
const app = next({ dev, dir: process.cwd(), conf: { distDir } });
await mkdir(output, { recursive: true });
await app.prepare();
const server = createServer(app.getRequestHandler());
await new Promise((resolve) => server.listen(18139, "127.0.0.1", resolve));

const projectId = 3;
const tasks = [
  { id: 61, project_id: projectId, objective: "运行中状态图标验收", status: "running", counts: {}, created_at: "2026-11-18T00:00:00Z" },
  { id: 62, project_id: projectId, objective: "已完成状态图标验收", status: "completed", counts: {}, created_at: "2026-11-17T00:00:00Z" },
  { id: 63, project_id: projectId, objective: "失败状态图标验收", status: "failed", counts: {}, created_at: "2026-11-16T00:00:00Z" },
];
const checks = [];
let failure = null;
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultTimeout(30000);
page.setDefaultNavigationTimeout(120000);
await page.addInitScript(() => sessionStorage.setItem("ybt:access-token", "synthetic-ux-acceptance"));
await page.route("**/api/**", async (route) => {
  const url = new URL(route.request().url());
  const pathname = url.pathname.replace(/^\/api/, "");
  const headers = {
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "*",
    "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
  };
  if (route.request().method() === "OPTIONS") {
    await route.fulfill({ status: 204, headers });
    return;
  }
  let body = {};
  if (pathname === "/auth/me") {
    body = {
      username: "synthetic-reviewer",
      effective_project_permissions: { [projectId]: ["task.read", "task.manage"] },
      project_memberships: [{ project_id: projectId, project_role: "owner", status: "active" }],
    };
  } else if (pathname === "/projects") {
    body = [{ id: projectId, name: "隔离任务台验收项目", project_status: "active", institution_id: 1 }];
  } else if (pathname === `/projects/${projectId}/jobs/summary`) {
    body = { active_count: 0, jobs: [] };
  } else if (pathname === "/version") {
    body = { component: "api", app_commit: "synthetic-ux-acceptance", build_time: "2026-11-18T00:00:00Z" };
  } else if (pathname === `/projects/${projectId}/agent/tasks`) {
    body = tasks;
  }
  await route.fulfill({ status: 200, contentType: "application/json", headers, body: JSON.stringify(body) });
});

try {
  await page.goto(`${baseUrl}/agent?projectId=${projectId}`, { waitUntil: "domcontentloaded" });
  await page.getByRole("region", { name: "任务列表" }).getByText(tasks[0].objective).waitFor();
  for (const label of ["处理中", "已完成", "处理失败"]) {
    const badge = page.getByLabel(`状态：${label}`, { exact: true }).first();
    await badge.waitFor();
    assert.equal(await badge.locator("svg[aria-hidden='true']").count(), 1, `${label} badge must contain one semantic icon`);
  }
  checks.push("task_statuses_include_text_color_and_icon");
  assert.equal(await page.getByText("找到任务 → 看懂结论 → 查看依据或产出 → 完成下一步处理", { exact: true }).count(), 0);
  checks.push("task_center_has_no_process_instruction_banner");
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, "tasks-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: path.join(output, "tasks-mobile.png"), fullPage: true });
  checks.push("desktop_and_390px_layout_have_no_horizontal_overflow");
} catch (error) {
  failure = { name: error.name, message: String(error.message).slice(0, 800) };
  await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true }).catch(() => {});
  process.exitCode = 1;
} finally {
  await writeFile(path.join(output, "results.json"), JSON.stringify({
    evidence_tier: "production_frontend_browser_synthetic_api",
    checks,
    failure,
  }, null, 2));
  await browser.close();
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  await app.close();
}
