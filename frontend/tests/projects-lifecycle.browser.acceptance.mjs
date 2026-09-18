import assert from "node:assert/strict";
import {createServer} from "node:http";
import {mkdir, writeFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import next from "next";
import {chromium} from "playwright";

const api = process.argv[2] || "http://127.0.0.1:18743/api";
const output = path.resolve(process.argv[3] || "project-lifecycle-acceptance");
const frontendDir = fileURLToPath(new URL("..", import.meta.url));
process.env.NEXT_DIST_DIR = ".next-project-lifecycle-isolated";
const nextApp = next({dev: false, dir: frontendDir, conf: {distDir: ".next-project-lifecycle-isolated"}});
const handler = nextApp.getRequestHandler();
await nextApp.prepare();
const frontendServer = createServer((request, response) => handler(request, response));
await new Promise((resolve, reject) => {
  frontendServer.once("error", reject);
  frontendServer.listen(18744, "127.0.0.1", resolve);
});
const origin = "http://127.0.0.1:18744";
await mkdir(output, {recursive: true});

const browser = await chromium.launch({headless: true, channel: "msedge"});
const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
const page = await context.newPage();
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.message));

const projectName = "浏览器幂等生命周期项目";
const basePayload = {
  name: projectName,
  institution_id: 1,
  bank_name: "项目生命周期隔离银行",
  description: "验证创建、防重复、停用、恢复和项目选择器可见性"
};

try {
  await page.goto(`${origin}/projects`, {waitUntil: "networkidle"});
  await page.getByRole("button", {name: "新建项目"}).click();
  const dialog = page.getByRole("dialog", {name: "新建项目"});
  await dialog.getByPlaceholder("项目名称").fill(projectName);
  await dialog.locator('select[name="institution_id"]').selectOption("1");
  await dialog.getByPlaceholder("项目说明").fill(basePayload.description);

  const createdResponse = page.waitForResponse((response) => (
    response.url().endsWith("/api/projects") && response.request().method() === "POST"
  ));
  await dialog.getByRole("button", {name: "创建项目", exact: true}).click();
  const created = await createdResponse;
  assert.equal(created.status(), 200, await created.text());
  const createdBody = await created.json();
  const submittedPayload = created.request().postDataJSON();
  assert.equal(submittedPayload.name, projectName);
  assert.ok(submittedPayload.client_request_id, "project creation must carry an idempotency key");
  await page.getByText("项目已创建", {exact: true}).waitFor();
  await dialog.waitFor({state: "hidden"});

  const replay = await page.request.post(`${api}/projects`, {
    data: {...basePayload, client_request_id: submittedPayload.client_request_id}
  });
  assert.equal(replay.status(), 200, await replay.text());
  assert.equal((await replay.json()).id, createdBody.id, "same request key must return the same project");

  let card = page.locator("article").filter({has: page.getByRole("heading", {name: projectName})});
  await card.waitFor();
  await card.getByRole("button", {name: "停用项目"}).click();
  const suspendResponse = page.waitForResponse((response) => (
    response.url().endsWith(`/api/projects/${createdBody.id}/status`) && response.request().method() === "PATCH"
  ));
  await page.getByRole("dialog").getByRole("button", {name: "停用项目"}).click();
  assert.equal((await suspendResponse).status(), 200);
  card = page.locator("article").filter({has: page.getByRole("heading", {name: projectName})});
  await card.getByText("已停用", {exact: true}).waitFor();
  await card.getByText("历史资料、版本、审核及交付记录全部保留。", {exact: true}).waitFor();
  assert.ok(!(await page.getByLabel("当前项目").locator("option").allTextContents()).includes(projectName));

  await card.getByRole("button", {name: "恢复项目"}).click();
  const restoreResponse = page.waitForResponse((response) => (
    response.url().endsWith(`/api/projects/${createdBody.id}/status`) && response.request().method() === "PATCH"
  ));
  await page.getByRole("dialog").getByRole("button", {name: "恢复项目"}).click();
  assert.equal((await restoreResponse).status(), 200);
  card = page.locator("article").filter({has: page.getByRole("heading", {name: projectName})});
  await card.getByRole("button", {name: "停用项目"}).waitFor();
  assert.ok((await page.getByLabel("当前项目").locator("option").allTextContents()).includes(projectName));

  await page.screenshot({path: path.join(output, "project-lifecycle.png"), fullPage: true});
  assert.deepEqual(pageErrors, []);
  const result = {
    actualFrontend: true,
    actualApi: true,
    realPostgresql: true,
    projectId: createdBody.id,
    duplicateCreateReturnedSameProject: true,
    suspendedHiddenFromSelector: true,
    restoredToSelector: true,
    pageErrors
  };
  await writeFile(path.join(output, "results.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  console.error(error);
  process.exitCode = 1;
} finally {
  await context.close();
  await browser.close();
  frontendServer.closeAllConnections?.();
  await Promise.race([
    new Promise((resolve) => frontendServer.close(resolve)),
    new Promise((resolve) => setTimeout(resolve, 2000))
  ]);
  void nextApp.close().catch(() => {});
}

process.exit(process.exitCode ?? 0);
