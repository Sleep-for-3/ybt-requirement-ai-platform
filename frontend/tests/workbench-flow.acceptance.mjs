import assert from "node:assert/strict";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { chromium } from "playwright";

const [base, project, credentials, output] = process.argv.slice(2);
assert.equal(new URL(base).hostname, "127.0.0.1", "Use an isolated local frontend");
assert.match(project, /^\d+$/);
const { username, password } = JSON.parse(await readFile(credentials, "utf8"));
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: "msedge" });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
page.setDefaultTimeout(60_000);
const checks = [];
async function screenshot(name) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, name);
  if (name.startsWith("asset-search")) {
    const bounds = await page.getByRole("dialog", { name: "搜索当前项目资产" }).evaluate(dialog => {
      const surface = dialog.querySelector("section").getBoundingClientRect();
      const input = dialog.querySelector("input").getBoundingClientRect();
      const title = dialog.querySelector("h2").getBoundingClientRect();
      return { top: surface.top, bottom: surface.bottom, inputTop: input.top, titleTop: title.top, height: innerHeight };
    });
    assert.ok(bounds.top >= 0 && bounds.bottom <= bounds.height && bounds.inputTop >= 0 && bounds.titleTop >= 0, `${name}: search controls inside viewport`);
  }
  await page.screenshot({ path: `${output}/${name}.png` });
  checks.push(name);
}
try {
  await page.goto(`${base}/login`, { waitUntil: "load", timeout: 120_000 });
  await page.locator("[name=username]").fill(username);
  await page.locator("[name=password]").fill(password);
  await page.locator("button[type=submit]").click();
  await page.waitForURL(url => !url.pathname.startsWith("/login"));
  await page.goto(`${base}/agent?projectId=${project}`, { waitUntil: "domcontentloaded", timeout: 120_000 });
  const form = page.getByRole("form", { name: "新建任务" });
  const objective = form.getByRole("textbox");
  await form.getByRole("button", { name: /示例/ }).first().click();
  assert.ok(await objective.inputValue());
  assert.equal(new URL(page.url()).searchParams.get("taskId"), null);
  const goal = "What is the permitted UXDEMO Customer Reporting status code?";
  await objective.fill(goal);
  const createButton = form.getByRole("button", { name: "开始分析" });
  const createPattern = new RegExp(`/projects/${project}/agent/tasks$`);
  let blockedSubmissions = 0;
  let releaseCreate;
  const createHeld = new Promise(resolve => { releaseCreate = resolve; });
  const blockCreate = async route => {
    if (route.request().method() !== "POST") return route.continue();
    blockedSubmissions += 1;
    await createHeld;
    await route.abort();
  };
  await page.route(createPattern, blockCreate);
  try {
    await createButton.click();
    const pending = form.getByRole("button", { name: /正在创建/ });
    await pending.waitFor();
    assert.equal(await pending.isDisabled(), true);
    await form.evaluate(el => el.requestSubmit());
    const failure = page.waitForEvent("requestfailed", { predicate: r => r.method() === "POST" && createPattern.test(r.url()) });
    releaseCreate();
    await failure;
    await createButton.waitFor();
    assert.equal(await objective.inputValue(), goal);
    assert.equal(blockedSubmissions, 1);
    checks.push("create-network-failure-retains-input-and-prevents-duplicate");
  } finally {
    releaseCreate();
    await page.unroute(createPattern, blockCreate);
  }
  await screenshot("task-list-1440");
  const sent = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/projects/${project}/agent/tasks`));
  await form.getByRole("button", { name: "开始分析" }).click();
  const response = await sent;
  assert.ok(response.ok());
  checks.push({ created: (await response.json()).task.id });
  const citation = page.getByRole("button", { name: /查看原文|打开原文/ }).first();
  await citation.click();
  const drawer = page.getByRole("dialog", { name: "文档证据" });
  await drawer.getByRole("link", { name: "下载原文" }).waitFor();
  await screenshot("citation-1440");
  await page.keyboard.press("Escape");
  assert.equal(await citation.evaluate(el => el === document.activeElement), true);
  await page.getByRole("link", { name: "后台执行记录" }).click();
  const batch = page.getByText(/第 1 批/).first();
  await batch.waitFor();
  await screenshot("job-1440");
  await page.reload({ waitUntil: "domcontentloaded" });
  await batch.waitFor();
  await page.setViewportSize({ width: 390, height: 844 });
  await screenshot("job-390");
  await page.getByRole("link", { name: /打开分析任务/ }).click();
  await page.getByRole("link", { name: "后台执行记录" }).waitFor();
  await screenshot("task-detail-390");
  await page.getByRole("link", { name: "返回任务中心" }).click();
  await form.waitFor();
  await objective.waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.querySelector('form[aria-label="新建任务"] textarea')?.disabled);
  await screenshot("task-list-390");

  const search = page.getByRole("button", { name: "搜索当前项目资产" });
  await search.focus();
  await page.keyboard.press("Control+k");
  const searchDialog = page.getByRole("dialog", { name: "搜索当前项目资产" });
  const keyword = searchDialog.getByRole("textbox", { name: "资产关键词" });
  await keyword.fill("U");
  await searchDialog.getByText("请输入至少 2 个字符。").waitFor();
  await keyword.fill("UXDEMO");
  await searchDialog.locator("mark").first().waitFor();
  await screenshot("asset-search-390");
  await page.keyboard.press("Escape");
  assert.equal(await search.evaluate(el => el === document.activeElement), true);
  await page.setViewportSize({ width: 1440, height: 900 });
  await search.click();
  await keyword.fill("UXDEMO");
  await searchDialog.locator("mark").first().waitFor();
  await screenshot("asset-search-1440");
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Shift+Tab");
  assert.equal(await searchDialog.evaluate(el => el.contains(document.activeElement)), true);
  await page.keyboard.press("Tab");
  await page.keyboard.press("Tab");
  await page.keyboard.press("ArrowDown");
  const selectedHref = await page.locator(":focus").getAttribute("href");
  assert.ok(selectedHref?.startsWith("/fields"));
  await page.keyboard.press("Enter");
  await page.waitForURL(url => url.pathname.startsWith("/fields"));
  await search.click();
  await searchDialog.getByText("最近访问", { exact: true }).waitFor();
  await searchDialog.getByRole("link").first().waitFor();
  await keyword.fill("UXDEMO NO SUCH ASSET 67A9");
  assert.equal(await searchDialog.getByRole("link").count(), 0);
  await searchDialog.getByText("当前项目没有匹配结果。").waitFor();
  const searchPattern = new RegExp(`/projects/${project}/global-search\\?`);
  let releaseSearch;
  const searchHeld = new Promise(resolve => { releaseSearch = resolve; });
  let oldRequestFetched;
  const oldFetched = new Promise(resolve => { oldRequestFetched = resolve; });
  const interceptSearch = async route => {
    const q = new URL(route.request().url()).searchParams.get("q");
    if (q === "UXDEMO") {
      const actual = await route.fetch();
      oldRequestFetched(actual.ok());
      await searchHeld;
      await route.fulfill({ response: actual }).catch(() => {});
    } else if (q === "UXDEMO NETWORK FAILURE") {
      await route.abort();
    } else {
      await route.continue();
    }
  };
  await page.route(searchPattern, interceptSearch);
  try {
    await keyword.fill("UXDEMO");
    await searchDialog.getByText("正在搜索…", { exact: true }).waitFor();
    assert.equal(await Promise.race([oldFetched, page.waitForTimeout(15_000).then(() => false)]), true);
    await keyword.fill("UXDEMO NO SUCH ASSET 7F1B");
    await searchDialog.getByText("当前项目没有匹配结果。").waitFor();
    releaseSearch();
    await page.unrouteAll({ behavior: "wait" });
    assert.equal(await searchDialog.getByRole("link").count(), 0);
    await page.route(searchPattern, interceptSearch);
    await keyword.fill("UXDEMO NETWORK FAILURE");
    await searchDialog.getByRole("alert").filter({ hasText: "搜索失败" }).waitFor();
    assert.equal(await searchDialog.getByRole("link").count(), 0);
    checks.push("search-loading-stale-response-and-network-failure");
  } finally {
    releaseSearch();
    await page.unroute(searchPattern, interceptSearch);
  }
  await page.keyboard.press("Escape");
  checks.push("search-recents-and-empty-result");

  if (process.env.UX_OTHER_PROJECT) {
    const selector = page.getByRole("combobox", { name: "当前项目" });
    let releaseProjectRequest;
    const held = new Promise(resolve => { releaseProjectRequest = resolve; });
    const delayProjectResponse = async route => {
      const response = await route.fetch();
      await held;
      await route.fulfill({ response }).catch(() => {});
    };
    await page.route(searchPattern, delayProjectResponse);
    try {
      await search.click();
      const old = page.waitForRequest(r => searchPattern.test(r.url()) && new URL(r.url()).searchParams.get("q") === "UXDEMO_STATUS");
      await keyword.fill("UXDEMO_STATUS");
      await old;
      await selector.selectOption(process.env.UX_OTHER_PROJECT);
      await searchDialog.waitFor({ state: "hidden" });
      releaseProjectRequest();
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await search.click();
      await keyword.fill("UXDEMO_STATUS");
      await searchDialog.getByText("当前项目没有匹配结果。").waitFor();
      assert.equal(await searchDialog.getByRole("link").count(), 0);
      await page.keyboard.press("Escape");
      await selector.selectOption(project);
      checks.push("search-project-switch-discards-old-results");
    } finally {
      releaseProjectRequest();
      await page.unroute(searchPattern, delayProjectResponse);
    }
  }

  if (process.env.UX_REQUIREMENT_QUERY) {
    await page.goto(`${base}/workspace?projectId=${project}&${process.env.UX_REQUIREMENT_QUERY}`, { waitUntil: "domcontentloaded", timeout: 120_000 });
    const selected = page.getByRole("heading", { level: 1, name: "UXDEMO Synthetic Requirement" });
    await selected.waitFor();
    assert.equal(await page.getByRole("button", { name: "展开", exact: true }).first().getAttribute("aria-expanded"), "false");
    await page.getByRole("tab", { name: "原文", exact: true }).click();
    await screenshot("requirement-document-1440");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("tab", { name: "依据", exact: true }).click();
    await page.getByRole("button", { name: "查看 1 条证据" }).click();
    const evidence = page.getByRole("dialog", { name: "字段证据" });
    await evidence.getByRole("button", { name: /打开依据原文/ }).click();
    await drawer.getByRole("link", { name: "下载原文" }).waitFor();
    await screenshot("requirement-source-390");
    await page.keyboard.press("Escape");
    await evidence.waitFor();
    await page.keyboard.press("Escape");
    await evidence.waitFor({ state: "hidden" });
    assert.equal(await page.getByRole("tab", { name: "依据", exact: true }).getAttribute("aria-selected"), "true");
    await page.getByRole("tab", { name: "条目", exact: true }).click();
    await page.getByRole("region", { name: "需求独立内容" }).waitFor();
    const initialize = page.getByRole("button", { name: "建立独立内容" });
    if (await initialize.isVisible()) {
      const write = page.waitForResponse(r => r.request().method() === "POST" && /\/requirements\/\d+\/revisions$/.test(r.url()));
      await initialize.click();
      assert.ok((await write).ok());
      checks.push("initialized-requirement-content");
    }
    await screenshot("requirement-item-390");
    if (process.env.UX_SAVE_REQUIREMENT === "1") {
      const remark = page.getByRole("textbox", { name: "需求业务备注" });
      const text = `合成演示：已核对政策原文及报告状态码，记录时间 ${new Date().toISOString()}。`;
      await remark.fill(text);
      const write = page.waitForResponse(r => r.request().method() === "PUT" && /\/requirements\/\d+\/fields\/\d+$/.test(r.url()));
      await page.getByRole("button", { name: "保存本需求口径" }).click();
      assert.ok((await write).ok());
      await page.reload({ waitUntil: "domcontentloaded" });
      await remark.waitFor();
      assert.equal(await remark.inputValue(), text);
      checks.push("requirement-evidence-then-save-and-reload");
    }
  }
  if (process.env.UX_CONTROLLED_FAILURE === "1") {
    await page.goto(`${base}/agent?projectId=${project}`);
    await objective.fill("UXDEMO controlled failure: What is the permitted customer reporting status code?");
    await form.getByRole("combobox").selectOption("knowledge_question");
    const create = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/projects/${project}/agent/tasks`));
    await form.getByRole("button", { name: "开始分析" }).click();
    const task = (await (await create).json()).task;
    await page.getByRole("heading", { name: "正在处理中" }).waitFor();
    await screenshot("controlled-running-390");
    await page.getByRole("heading", { name: "模型暂时不可用" }).waitFor();
    const history = page.getByRole("link", { name: "后台执行记录" });
    const failedHref = await history.getAttribute("href");
    await history.click();
    await page.getByRole("alert").filter({ hasText: "模型暂时不可用" }).waitFor();
    await screenshot("controlled-failure-job-390");
    await page.getByRole("link", { name: "打开分析任务处理失败" }).click();
    const retry = page.getByRole("button", { name: "重新运行", exact: true }).first();
    await retry.waitFor();
    await screenshot("controlled-failure-detail-390");
    const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/agent/tasks/${task.id}/retry`));
    await retry.click();
    assert.ok((await response).ok());
    await page.getByRole("button", { name: /查看原文|打开原文/ }).first().waitFor();
    const recoveredHref = await history.getAttribute("href");
    assert.notEqual(recoveredHref, failedHref);
    await history.click();
    await page.getByText(/第 2 批/).first().waitFor();
    await screenshot("controlled-recovered-job-390");
    await page.goto(new URL(failedHref, base).href);
    await page.getByRole("alert").filter({ hasText: "模型暂时不可用" }).waitFor();
    checks.push({ recovered: task.id, failedHref, recoveredHref });
  }
  await page.goto(`${base}/agent?projectId=${project}`);
  await page.waitForFunction(() => !document.querySelector('form[aria-label="新建任务"] textarea')?.disabled);
  await objective.fill("请核对一表通客户报送状态字段的允许码值、适用范围及对应制度依据，列出仍需人工确认的内容。");
  await page.setViewportSize({ width: 1440, height: 900 });
  await screenshot("task-list-ready-1440");
  await page.setViewportSize({ width: 390, height: 844 });
  await screenshot("task-list-ready-390");
  await page.getByRole("button", { name: /^已完成（/ }).click();
  await page.getByRole("textbox", { name: "搜索任务" }).fill("What");
  const action = page.locator("[data-task-action]").first();
  await action.waitFor();
  const focusedTask = await action.getAttribute("data-task-action");
  const listUrl = page.url();
  await action.focus();
  await page.keyboard.press("Enter");
  await page.getByRole("link", { name: "返回任务中心" }).click();
  await page.waitForURL(listUrl);
  assert.equal(await page.getByRole("textbox", { name: "搜索任务" }).inputValue(), "What");
  await page.waitForFunction(id => document.activeElement?.getAttribute("data-task-action") === id, focusedTask);
  checks.push("list-filter-query-page-and-keyboard-focus-restored");
} catch (error) {
  await page.screenshot({ path: `${output}/failure.png` }).catch(() => {});
  const message = error.message.replaceAll(username, "[redacted]").replaceAll(password, "[redacted]");
  checks.push({ error: message });
  throw new Error(message);
} finally {
  await writeFile(`${output}/results.json`, JSON.stringify(checks, null, 2));
  await browser.close();
}
