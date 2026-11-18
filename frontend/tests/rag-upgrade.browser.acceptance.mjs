import assert from "node:assert/strict";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { createHash } from "node:crypto";
import { chromium } from "playwright";

const fixture = JSON.parse(await readFile(process.argv[2], "utf8"));
const output = path.resolve(process.argv[3] || "../.local-run/rag-browser");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
page.setDefaultNavigationTimeout(120000);
const results = [];
const evidenceRequests = [];
page.on("response", response => {
  if (/\/knowledge\/documents\/\d+\/(preview|content)\?/.test(response.url())) {
    evidenceRequests.push({ url: response.url(), status: response.status() });
  }
});
const frontend = process.env.RAG_ACCEPT_FRONTEND || "http://127.0.0.1:18094";
try {
  await page.goto(`${frontend}/login`);
  await page.getByLabel("用户名", { exact: true }).fill(fixture.username);
  await page.getByLabel("密码", { exact: true }).fill("invalid-test-password");
  const badLogin = page.waitForResponse(response => response.url().endsWith("/auth/login"));
  await page.getByRole("button", { name: "登录", exact: true }).click();
  assert.equal((await badLogin).status(), 401);
  await page.getByText("用户名或密码错误", { exact: true }).waitFor();
  results.push("wrong_credentials_401");
  await page.getByLabel("密码", { exact: true }).fill(fixture.password);
  const login = page.waitForResponse(response => response.url().endsWith("/auth/login"));
  await page.getByRole("button", { name: "登录", exact: true }).click();
  assert.equal((await login).status(), 200);
  await page.waitForURL("**/projects");
  results.push("form_login_200");
  await page.goto(`${frontend}/knowledge/ask?mode=regulatory&projectId=${fixture.project_id}`);
  await page.getByRole("combobox", { name: "当前项目" }).selectOption(String(fixture.project_id));
  await page.getByLabel("你的问题").fill("合作方式字段F250007如何填报？");
  const ask = page.waitForResponse(response => response.url().endsWith("/knowledge/ask"));
  await page.getByRole("button", { name: "提交问题", exact: true }).click();
  const answer = await ask;
  assert.equal(answer.status(), 200);
  const body = await answer.json();
  assert.ok(body.citations.length > 0, "isolated document must be retrievable");
  assert.ok(["C", "D"].includes(body.trustworthiness.grade));
  assert.equal(body.verification_status, "not_run");
  await page.getByText("对话记录（1）", { exact: true }).waitFor();
  results.push("ask_and_unverified_trust_ceiling");
  await page.getByLabel("你的问题").fill("那它的码值呢？");
  const followupRequest = page.waitForRequest(request => request.url().endsWith("/knowledge/ask"));
  const followupResponse = page.waitForResponse(response => response.url().endsWith("/knowledge/ask"));
  await page.getByRole("button", { name: "提交问题", exact: true }).click();
  assert.equal((await followupRequest).postDataJSON().history.length, 2);
  assert.equal((await followupResponse).status(), 200);
  await page.getByText("对话记录（2）", { exact: true }).waitFor();
  results.push("history_sent_as_complete_pair");
  await page.getByRole("button", { name: "清空对话" }).click();
  await page.getByText("对话记录（0）", { exact: true }).waitFor();
  results.push("clear_history");
  await page.getByRole("combobox", { name: "当前项目" }).selectOption(String(fixture.other_project_id));
  await page.getByText("对话记录（0）", { exact: true }).waitFor();
  await page.goto(`${frontend}/agent?taskId=${fixture.task_id}&projectId=${fixture.other_project_id}`);
  await page.getByRole("combobox", { name: "当前项目" }).selectOption(String(fixture.other_project_id));
  await page.getByRole("button", { name: /打开原文|查看原文/ }).first().click({ timeout: 60000 });
  const drawer = page.getByRole("dialog", { name: "文档证据" });
  await drawer.getByText(/acceptance-policy.md/).waitFor({ timeout: 30000 });
  await drawer.getByRole("link", { name: "下载原文" }).waitFor();
  assert.ok(evidenceRequests.some(row => row.status === 200 && row.url.includes("/content?")));
  for (const request of evidenceRequests.filter(row => row.url.includes("/content?") || row.url.includes("/preview?"))) {
    const url = new URL(request.url);
    assert.equal(url.searchParams.get("project_id"), String(fixture.project_id));
    assert.equal(url.searchParams.get("version_id"), String(fixture.version_id));
    assert.equal(request.status, 200);
  }
  results.push("cross_project_task_uses_owner_and_frozen_original");
  if (fixture.source_sha256) {
    // Chromium can omit bodies from response events after blob consumption.
    // Read the exact blob offered by the rendered download link.
    const downloadUrl = await drawer.getByRole("link", { name: "下载原文" }).getAttribute("href");
    const original = await page.evaluate(async url => {
      const response = await fetch(url);
      return { status: response.status, bytes: [...new Uint8Array(await response.arrayBuffer())] };
    }, downloadUrl);
    assert.equal(original.status, 200);
    assert.equal(createHash("sha256").update(Buffer.from(original.bytes)).digest("hex"), fixture.source_sha256);
    await drawer.getByText(Buffer.from(original.bytes).toString("utf8"), { exact: true }).waitFor();
    results.push("download_bytes_match_answer_version_sha256");
  }
  await page.screenshot({ path: path.join(output, "evidence-desktop.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(output, "evidence-mobile.png"), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  results.push("mobile_no_horizontal_overflow");
  await writeFile(path.join(output, "results.json"), JSON.stringify({
    evidence_tier: fixture.evidence_tier || "browser_sqlite_mock", results, evidenceRequests,
  }, null, 2));
  console.log(JSON.stringify({ passed: results.length, results }));
} catch (error) {
  await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true });
  await writeFile(path.join(output, "failure.txt"), await page.locator("body").innerText());
  throw error;
} finally {
  await browser.close();
}
