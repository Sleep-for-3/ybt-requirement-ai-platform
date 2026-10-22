// Real browser smoke for Round 6 requirement-version pinning (C10).
// Verifies, through the real Next.js page and real API:
//   1. the ask page sends requirement_id + requirement_content_version;
//   2. the page only claims "fixed version" when the API echoes the pinned versions;
//   3. a requirement revision without pins fails closed with an explicit message.
import { mkdir, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(join(ROOT, "frontend", "package.json"));
const { chromium } = require("playwright");

const WEB = process.env.VNEXT_WEB || "http://127.0.0.1:3010";
const API = process.env.VNEXT_API || "http://127.0.0.1:8011/api";
const PASSWORD = "Vnext2#P0C2026";
const USERNAME = "p0c-biz";
const PROJECT_ID = 7;
const PINNED = { requirementId: 6, contentVersion: 2, title: "产品期限组合键管理办法", version: "2026-v1" };
const UNPINNED = { requirementId: 5, contentVersion: 12 };

const steps = [];
const apiCalls = [];
// 问答响应单独留存：失败关闭（400/422）只能通过真实状态码与页面拒绝文案判定，
// 不能靠"有没有出现提示"来猜。
const askResponses = [];
const consoleErrors = [];
function record(name, ok, detail = "") {
  steps.push({ name, ok, detail, at: new Date().toISOString() });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
}

async function login() {
  const response = await fetch(`${API}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: USERNAME, password: PASSWORD }),
  });
  if (!response.ok) throw new Error(`login failed: ${response.status}`);
  const payload = await response.json();
  return { access: payload.access_token, refresh: payload.refresh_token };
}

async function openAsk(browser, tokens, requirementId, contentVersion) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(
    ([access, refresh]) => {
      window.sessionStorage.setItem("ybt:access-token", access);
      window.sessionStorage.setItem("ybt:refresh-token", refresh);
    },
    [tokens.access, tokens.refresh],
  );
  const page = await context.newPage();
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text().slice(0, 300));
  });
  page.on("request", (request) => {
    if (request.url().includes("/knowledge/ask") && request.method() === "POST") {
      apiCalls.push({ url: request.url(), body: request.postData() });
    } else if (request.url().includes("/api/projects/7/requirements")) {
      apiCalls.push({ url: request.url(), method: request.method() });
    }
  });
  page.on("response", async (response) => {
    if (!/knowledge\/ask$/.test(response.url())) return;
    const entry = {
      url: response.url(),
      status: response.status(),
      body: response.request().postData()?.slice(0, 2000) ?? null,
      detail: "",
    };
    try {
      entry.detail = (await response.text()).slice(0, 600);
    } catch {
      entry.detail = "";
    }
    askResponses.push(entry);
  });
  const url = `${WEB}/knowledge/ask?mode=regulatory&projectId=${PROJECT_ID}`
    + `&requirementId=${requirementId}&contentVersion=${contentVersion}`;
  await page.goto(url, { waitUntil: "networkidle", timeout: 120000 });
  await page.waitForSelector("textarea", { timeout: 120000 });
  return { context, page };
}

async function ask(page, question) {
  const box = page.locator("textarea").first();
  await box.click();
  await box.fill(question);
  await box.dispatchEvent("input");
  const submit = page.getByRole("button", { name: /^提交问题$/ });
  await submit.waitFor({ state: "visible", timeout: 60000 });
  // React 受控输入在部分时序下需要一次真实键入才会让状态生效，因此这里等可点击再点。
  for (let attempt = 0; attempt < 10; attempt += 1) {
    if (await submit.isEnabled()) break;
    await page.waitForTimeout(500);
    const value = await box.inputValue();
    if (!value.trim()) await box.type(question);
  }
  if (!(await submit.isEnabled())) {
    const value = await box.inputValue();
    throw new Error(`submit stayed disabled (textarea=${JSON.stringify(value.slice(0, 40))}, url=${page.url()})`);
  }
  await submit.click();
}

async function main() {
  const tokens = await login();
  record("login", true, USERNAME);
  const screenshotDir = join(ROOT, "docs", "audit", "vnext2-r6-pin");
  await mkdir(screenshotDir, { recursive: true });
  const browser = await chromium.launch();
  globalThis.__browser = browser;

  // Case A: pinned revision — the page must echo the exact pinned version.
  {
    const { context, page } = await openAsk(browser, tokens, PINNED.requirementId, PINNED.contentVersion);
    await ask(page, "产品期限与产品标识是如何构成业务键的？");
    const banner = page.getByRole("status").filter({ hasText: /本次回答固定使用/ });
    let ok = false;
    try {
      await banner.first().waitFor({ state: "visible", timeout: 420000 });
      ok = true;
    } catch {
      ok = false;
    }
    if (ok) {
      const text = (await banner.first().innerText()).trim();
      ok = text.includes(`需求 v${PINNED.contentVersion}`)
        && text.includes(`${PINNED.title}=${PINNED.version}`);
      record("ask:pinned-banner", ok, text.slice(0, 200));
    } else {
      record("ask:pinned-banner", false, "未出现版本钉扎说明");
    }
    await page.screenshot({ path: join(screenshotDir, "ask-pinned.png"), fullPage: true });
    await context.close();
  }

  // Case B: revision without pins — must fail closed, never claim a fixed version.
  {
    const { context, page } = await openAsk(browser, tokens, UNPINNED.requirementId, UNPINNED.contentVersion);
    await ask(page, "客户证件类型的报送范围是什么？");
    const alert = page.getByRole("alert");
    let alertText = "";
    // 全局常驻的无障碍提示容器也是 role="alert"（内容可能为空），因此必须取所有非空提示，
    // 不能盲取第一个，否则会读到空的常驻容器而误判为"没有提示"。
    try {
      await alert.first().waitFor({ state: "visible", timeout: 300000 });
      for (let attempt = 0; attempt < 40; attempt += 1) {
        const texts = (await alert.allInnerTexts()).map((text) => text.trim()).filter(Boolean);
        alertText = texts.join(" | ");
        if (alertText) break;
        await page.waitForTimeout(250);
      }
    } catch {
      alertText = "";
    }
    // 响应回调是异步的（要读取响应体），提示先出现时状态码可能还没入账，因此短轮询等它落地。
    for (let attempt = 0; attempt < 40; attempt += 1) {
      if (askResponses.some((call) => call.status >= 400 && call.status < 500)) break;
      await page.waitForTimeout(250);
    }
    const rejected = askResponses.filter((call) => call.status === 422 || call.status === 400).at(-1);
    // 既要有服务端保守拒绝（422/400），也要把可执行的原因原样呈现给用户。
    const closed = Boolean(rejected)
      && /未固定任何制度版本|无法按冻结版本判定/.test(alertText)
      && /未固定任何制度版本|无法按冻结版本判定/.test(rejected?.detail ?? "");
    record("ask:unpinned-fails-closed", closed,
      `HTTP ${rejected?.status ?? "?"} · ${(alertText || rejected?.detail || "无拒绝提示").slice(0, 200)}`);
    // 没有回答时不得出现"固定使用某版本"或"回答未回显固定版本"这类针对回答的断言。
    const claim = page.getByRole("status").filter({ hasText: /本次回答固定使用|未回显固定版本/ });
    const claimVisible = await claim.first().isVisible().catch(() => false);
    record("ask:unpinned-no-fake-pin-claim", !claimVisible,
      claimVisible ? (await claim.first().innerText()).trim().slice(0, 160) : "未渲染任何版本固定声明");
    await page.screenshot({ path: join(screenshotDir, "ask-unpinned.png"), fullPage: true });
    await context.close();
  }

  await browser.close();

  const askCall = askResponses.find((call) => call.status === 200 && call.body);
  let bodyOk = false;
  if (askCall) {
    try {
      const body = JSON.parse(askCall.body);
      bodyOk = body.requirement_id === PINNED.requirementId
        && body.requirement_content_version === PINNED.contentVersion;
      record("ask:request-carries-pin", bodyOk, askCall.body.slice(0, 160));
    } catch {
      record("ask:request-carries-pin", false, "请求体不是 JSON");
    }
  } else {
    record("ask:request-carries-pin", false, "未捕获问答请求");
  }
  // 浏览器会把任何 4xx 都记成 "Failed to load resource"，这是页面已正确处理的业务拒绝，
  // 不是脚本错误；只把真正的 JS 异常算作失败。
  const realConsoleErrors = consoleErrors.filter(
    (line) => !/Failed to load resource: the server responded with a status of 4\d\d/.test(line),
  );
  record("console:no-errors", realConsoleErrors.length === 0, realConsoleErrors.slice(0, 3).join(" | "));

  const ok = steps.every((step) => step.ok);
  const report = {
    generated_at: new Date().toISOString(),
    evidence_level: "REAL_COMPONENT",
    truth_level: "UNVERIFIED",
    web: WEB,
    api: API,
    pinned: PINNED,
    unpinned: UNPINNED,
    ok,
    steps,
    apiCalls,
    consoleErrors,
    note: "合成演示需求；真实模型网关 deepseek-v4.1-flash；不代表银行专家确认的监管口径。",
  };
  await writeFile(join(ROOT, "docs", "audit", "VNEXT2_R6_PIN_BROWSER-20261023.json"),
    `${JSON.stringify(report, null, 2)}\n`, "utf8");
  console.log(`\n${ok ? "ALL PASS" : "FAILURES"} — ${steps.filter((s) => s.ok).length}/${steps.length}`);
  if (!ok) process.exitCode = 1;
}

main().catch(async (error) => {
  await globalThis.__browser?.close?.().catch(() => {});
  console.error(error);
  steps.push({ name: "fatal", ok: false, detail: String(error).slice(0, 500) });
  await writeFile(join(ROOT, "docs", "audit", "VNEXT2_R6_PIN_BROWSER-20261023.json"),
    `${JSON.stringify({ ok: false, steps, apiCalls, consoleErrors, error: String(error) }, null, 2)}\n`, "utf8");
  process.exitCode = 1;
});
