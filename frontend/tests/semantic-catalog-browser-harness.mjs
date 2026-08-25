import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import http from "node:http";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const TEST_DIR = path.dirname(fileURLToPath(import.meta.url));
const REPOSITORY_ROOT = path.resolve(TEST_DIR, "..", "..");
const FRONTEND_ROOT = path.join(REPOSITORY_ROOT, "frontend");
const NEXT_BIN = path.join(FRONTEND_ROOT, "node_modules", "next", "dist", "bin", "next");
const DEFAULT_TIMEOUT_MS = 12_000;
const STARTUP_TIMEOUT_MS = 60_000;
const API_RESPONSE_HEADERS = [
  { name: "Content-Type", value: "application/json; charset=utf-8" },
  { name: "Access-Control-Allow-Origin", value: "*" },
  { name: "Access-Control-Allow-Headers", value: "Content-Type, Authorization" },
  { name: "Cache-Control", value: "no-store" }
];

/**
 * Start the real Next route and an isolated installed browser. The returned
 * driver owns every process, CDP target, paused API request, and temp profile.
 */
export async function createSemanticCatalogBrowser(options = {}) {
  const server = await startNextServer(options.serverTimeoutMs || STARTUP_TIMEOUT_MS);
  let browser = null;
  try {
    browser = await startBrowser(server.port);
    const cdp = await connectTarget(browser.version.webSocketDebuggerUrl);
    const driver = new SemanticCatalogBrowser({ server, browser, cdp, timeoutMs: options.timeoutMs || DEFAULT_TIMEOUT_MS });
    await driver.initialize();
    return driver;
  } catch (error) {
    await closeRuntime({ server, browser, cdp: null });
    throw error;
  }
}

class SemanticCatalogBrowser {
  constructor({ server, browser, cdp, timeoutMs }) {
    this.server = server;
    this.browser = browser;
    this.cdp = cdp.connection;
    this.sessionId = cdp.sessionId;
    this.targetId = cdp.targetId;
    this.timeoutMs = timeoutMs;
    this.closed = false;
    this.records = [];
    this.handlers = new Map();
    this.setDefaultHandlers();
    this.cdp.on("Fetch.requestPaused", (message) => {
      if (message.sessionId !== this.sessionId) return;
      void this.handlePausedRequest(message.params);
    });
  }

  setDefaultHandlers() {
    this.handlers = new Map([
      ["projects", () => jsonResponse([
        { id: 1, name: "项目 A", bank_name: "测试机构" },
        { id: 2, name: "项目 B", bank_name: "测试机构" }
      ])],
      ["catalog", () => jsonResponse({ detail: "未配置语义目录测试响应" }, 500)],
      ["detail-shell", () => jsonResponse({ detail: "未配置语义详情测试响应" }, 500)],
      ["detail-region", () => jsonResponse({ detail: "未配置语义详情区域测试响应" }, 500)]
    ]);
  }

  async initialize() {
    await this.cdp.send("Page.enable", {}, this.sessionId);
    await this.cdp.send("Runtime.enable", {}, this.sessionId);
    await this.cdp.send("Accessibility.enable", {}, this.sessionId);
    await this.cdp.send("Fetch.enable", {
      patterns: [{ urlPattern: "http://localhost:8000/api/*", requestStage: "Request" }]
    }, this.sessionId);
  }

  setApiHandler(kind, handler) {
    assert.equal(typeof handler, "function", `handler for ${kind} must be a function`);
    this.handlers.set(kind, handler);
  }

  async resetScenario() {
    await this.failPendingRequests();
    this.records = [];
    this.setDefaultHandlers();
  }

  async handlePausedRequest(params) {
    const record = createApiRecord(params);
    if (!record) {
      await this.continueRequest(params.requestId);
      return;
    }
    this.records.push(record);
    const handler = this.handlers.get(record.kind);
    if (!handler) {
      await this.respond(record, jsonResponse({ detail: `未处理的 API 请求：${record.url}` }, 500));
      return;
    }
    try {
      const response = await handler(record);
      if (response?.hold === true) return;
      await this.respond(record, response || jsonResponse(null));
    } catch (error) {
      await this.respond(record, jsonResponse({ detail: error instanceof Error ? error.message : "测试响应失败" }, 500));
    }
  }

  async continueRequest(requestId) {
    try {
      await this.cdp.send("Fetch.continueRequest", { requestId }, this.sessionId);
    } catch {
      // A route transition may cancel a request between the pause event and this continuation.
    }
  }

  async respond(record, response = jsonResponse(null)) {
    if (!record || record.settled) return;
    record.settled = true;
    const status = Number(response.status || 200);
    const body = response.body === undefined ? null : response.body;
    const encoded = Buffer.from(typeof body === "string" ? body : JSON.stringify(body)).toString("base64");
    try {
      await this.cdp.send("Fetch.fulfillRequest", {
        requestId: record.requestId,
        responseCode: status,
        responseHeaders: API_RESPONSE_HEADERS,
        body: encoded
      }, this.sessionId);
    } catch (error) {
      record.error = error;
      if (!record.aborted) throw error;
    }
  }

  async failPendingRequests() {
    const pending = this.records.filter((record) => !record.settled);
    await Promise.allSettled(pending.map(async (record) => {
      record.settled = true;
      record.aborted = true;
      try {
        await this.cdp.send("Fetch.failRequest", { requestId: record.requestId, errorReason: "Aborted" }, this.sessionId);
      } catch {
        // The browser may have already cancelled an aborted Fetch interception.
      }
    }));
  }

  async waitForRequest(predicate, timeoutMs = this.timeoutMs) {
    const started = Date.now();
    let lastError = null;
    while (Date.now() - started < timeoutMs) {
      const record = this.records.find((item) => !item.claimed && predicate(item));
      if (record) {
        record.claimed = true;
        return record;
      }
      await delay(25);
    }
    lastError = new Error(`Timed out waiting for API request after ${timeoutMs}ms`);
    throw lastError;
  }

  async waitFor(predicate, timeoutMs = this.timeoutMs, description = "condition") {
    const started = Date.now();
    let lastError;
    while (Date.now() - started < timeoutMs) {
      try {
        const result = await predicate();
        if (result) return result;
      } catch (error) {
        lastError = error;
      }
      await delay(25);
    }
    throw new Error(`Timed out waiting for ${description}${lastError ? `: ${lastError.message}` : ""}`);
  }

  async navigate(relativePath) {
    const url = new URL(relativePath, `http://127.0.0.1:${this.server.port}`).toString();
    await this.cdp.send("Page.navigate", { url }, this.sessionId);
    await this.waitFor(() => this.evaluate("location.pathname"), this.timeoutMs, `navigation to ${relativePath}`);
    await this.waitFor(() => this.evaluate("document.readyState === 'complete' || document.readyState === 'interactive'"), this.timeoutMs, "document readiness");
  }

  /**
   * Keep a paused Fetch interception fulfillable after a route transition. The
   * production code still creates and passes AbortSignals through apiGet; this
   * browser-only switch makes the completion order adversarial instead of
   * letting Chromium discard the response before the reducer sees it.
   */
  async preserveDeferredCompletions() {
    await this.evaluate(`(() => {
      if (window.__semanticCatalogDeferredAbortPatched) return true;
      const original = AbortController.prototype.abort;
      AbortController.prototype.abort = function abortForDeferredBrowserTest(reason) {
        this.__semanticCatalogAbortRequested = reason || true;
      };
      window.__semanticCatalogDeferredAbortPatched = { original };
      return true;
    })()`);
  }

  async evaluate(expression) {
    const result = await this.cdp.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
      userGesture: true
    }, this.sessionId);
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || "Runtime.evaluate failed");
    }
    return result.result?.value;
  }

  async text(selector = "body") {
    return this.evaluate(`document.querySelector(${JSON.stringify(selector)})?.innerText || ""`);
  }

  async domText(selector = "body") {
    return this.evaluate(`document.querySelector(${JSON.stringify(selector)})?.textContent || ""`);
  }

  async outerHTML(selector = "html") {
    return this.evaluate(`document.querySelector(${JSON.stringify(selector)})?.outerHTML || ""`);
  }

  async attribute(selector, name) {
    return this.evaluate(`document.querySelector(${JSON.stringify(selector)})?.getAttribute(${JSON.stringify(name)})`);
  }

  async exists(selector) {
    return Boolean(await this.evaluate(`Boolean(document.querySelector(${JSON.stringify(selector)}))`));
  }

  async waitForSelector(selector, timeoutMs = this.timeoutMs) {
    return this.waitFor(() => this.exists(selector), timeoutMs, `selector ${selector}`);
  }

  async waitForText(value, timeoutMs = this.timeoutMs) {
    return this.waitFor(async () => (await this.text()).includes(value), timeoutMs, `text ${value}`);
  }

  async waitForAbsentText(value, timeoutMs = this.timeoutMs) {
    return this.waitFor(async () => !(await this.domText()).includes(value), timeoutMs, `absence of text ${value}`);
  }

  async waitForUrl(predicate, timeoutMs = this.timeoutMs) {
    return this.waitFor(async () => predicate(String(await this.evaluate("location.href"))), timeoutMs, "URL state");
  }

  async click(selector) {
    const clicked = await this.evaluate(`(() => { const element = document.querySelector(${JSON.stringify(selector)}); if (!element) return false; element.click(); return true; })()`);
    assert.equal(clicked, true, `could not click ${selector}`);
  }

  async clickText(value) {
    const clicked = await this.evaluate(`(() => {
      const wanted = ${JSON.stringify(value)};
      const elements = [...document.querySelectorAll("button, a")];
      const element = elements.find((candidate) => (candidate.innerText || candidate.textContent || "").trim() === wanted)
        || elements.find((candidate) => (candidate.innerText || candidate.textContent || "").includes(wanted));
      if (!element) return false;
      element.click();
      return true;
    })()`);
    assert.equal(clicked, true, `could not click text ${value}`);
  }

  async select(selector, value) {
    const changed = await this.evaluate(`(() => {
      const element = document.querySelector(${JSON.stringify(selector)});
      if (!element) return false;
      const setter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value")?.set;
      if (setter) setter.call(element, ${JSON.stringify(String(value))});
      else element.value = ${JSON.stringify(String(value))};
      element.dispatchEvent(new Event("change", { bubbles: true }));
      return element.value === ${JSON.stringify(String(value))};
    })()`);
    assert.equal(changed, true, `could not select ${value} in ${selector}`);
  }

  async key(selector, key) {
    const focused = await this.evaluate(`(() => { const element = document.querySelector(${JSON.stringify(selector)}); if (!element) return false; element.focus(); return document.activeElement === element; })()`);
    assert.equal(focused, true, `could not focus ${selector}`);
    await this.dispatchKey(key);
  }

  async keyText(value, key) {
    const focused = await this.evaluate(`(() => {
      const wanted = ${JSON.stringify(value)};
      const element = [...document.querySelectorAll("button, a")].find((candidate) => (candidate.innerText || candidate.textContent || "").trim() === wanted);
      if (!element) return false;
      element.focus();
      return document.activeElement === element;
    })()`);
    assert.equal(focused, true, `could not focus button text ${value}`);
    await this.dispatchKey(key);
  }

  async dispatchKey(key) {
    const code = key.length === 1 ? `Key${key.toUpperCase()}` : key;
    const virtualKeyCodes = { Enter: 13, Home: 36, End: 35, ArrowLeft: 37, ArrowUp: 38, ArrowRight: 39, ArrowDown: 40, Escape: 27, Space: 32 };
    await this.cdp.send("Input.dispatchKeyEvent", {
      type: "keyDown",
      key,
      code,
      windowsVirtualKeyCode: virtualKeyCodes[key] || 0
    }, this.sessionId);
    await this.cdp.send("Input.dispatchKeyEvent", {
      type: "keyUp",
      key,
      code,
      windowsVirtualKeyCode: virtualKeyCodes[key] || 0
    }, this.sessionId);
  }

  async activeElement() {
    return this.evaluate("({ id: document.activeElement?.id || '', role: document.activeElement?.getAttribute('role') || '', text: document.activeElement?.innerText || document.activeElement?.textContent || '' })");
  }

  async elements(selector) {
    return this.evaluate(`Array.from(document.querySelectorAll(${JSON.stringify(selector)})).map((element) => ({ id: element.id, text: (element.innerText || element.textContent || "").trim(), disabled: Boolean(element.disabled), expanded: element.getAttribute("aria-expanded"), selected: element.getAttribute("aria-selected"), controls: element.getAttribute("aria-controls"), href: element.getAttribute("href") }))`);
  }

  async buttonState(label, selector = "button") {
    return this.evaluate(`(() => {
      const wanted = ${JSON.stringify(label)};
      const element = [...document.querySelectorAll(${JSON.stringify(selector)})].find((candidate) => (candidate.innerText || candidate.textContent || "").trim() === wanted);
      return element ? { disabled: Boolean(element.disabled), ariaDisabled: element.getAttribute("aria-disabled"), id: element.id } : null;
    })()`);
  }

  async links() {
    return this.evaluate("Array.from(document.querySelectorAll('a')).map((element) => ({ text: (element.innerText || element.textContent || '').trim(), href: element.getAttribute('href') }))");
  }

  async accessibilityTree() {
    const result = await this.cdp.send("Accessibility.getFullAXTree", {}, this.sessionId);
    return result.nodes || [];
  }

  async accessibilityText() {
    return JSON.stringify(await this.accessibilityTree());
  }

  async close() {
    if (this.closed) return;
    this.closed = true;
    await closeRuntime({
      server: this.server,
      browser: this.browser,
      cdp: { connection: this.cdp, sessionId: this.sessionId, targetId: this.targetId }
    });
  }
}

function createApiRecord(params) {
  let url;
  try {
    url = new URL(params.request.url);
  } catch {
    return null;
  }
  if (url.origin !== "http://localhost:8000" || !url.pathname.startsWith("/api/")) return null;
  const parts = url.pathname.split("/").filter(Boolean);
  if (parts[0] !== "api" || parts[1] !== "projects") return null;
  const record = {
    requestId: params.requestId,
    url: url.toString(),
    method: params.request.method,
    query: Object.fromEntries(url.searchParams.entries()),
    searchParams: url.searchParams,
    request: params.request,
    settled: false,
    claimed: false,
    aborted: false,
    error: null
  };
  if (parts.length === 2) return Object.assign(record, { kind: "projects", projectId: null, conceptId: null, region: null });
  const projectId = Number(parts[2]);
  if (!Number.isSafeInteger(projectId) || projectId <= 0 || parts[3] !== "semantic-catalog") return null;
  if (parts.length === 4) return Object.assign(record, { kind: "catalog", projectId, conceptId: null, region: null });
  const conceptId = Number(parts[4]);
  if (!Number.isSafeInteger(conceptId) || conceptId <= 0) return null;
  if (parts.length === 5) return Object.assign(record, { kind: "detail-shell", projectId, conceptId, region: "shell" });
  if (parts.length === 6) return Object.assign(record, { kind: "detail-region", projectId, conceptId, region: parts[5] });
  return null;
}

function jsonResponse(body, status = 200) {
  return { status, body };
}

async function startNextServer(timeoutMs) {
  assert.ok(NEXT_BIN, "Next runtime path must be known");
  const port = await freePort();
  const output = [];
  const child = spawn(process.execPath, [NEXT_BIN, "dev", "--hostname", "127.0.0.1", "--port", String(port)], {
    cwd: FRONTEND_ROOT,
    env: {
      ...process.env,
      NEXT_PUBLIC_API_BASE_URL: "http://localhost:8000/api",
      NEXT_TELEMETRY_DISABLED: "1"
    },
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true
  });
  child.stdout?.on("data", (chunk) => appendOutput(output, chunk));
  child.stderr?.on("data", (chunk) => appendOutput(output, chunk));
  const started = Date.now();
  while (Date.now() - started < timeoutMs) {
    if (child.exitCode !== null) {
      throw new Error(`Next dev server exited with ${child.exitCode}:\n${output.join("")}`);
    }
    try {
      const response = await httpRequest(`http://127.0.0.1:${port}/semantics?projectId=1`, 1_500);
      if (response.statusCode >= 200 && response.statusCode < 400) return { child, port, output };
    } catch {
      // The route is still compiling or the loopback listener is not ready.
    }
    await delay(100);
  }
  await terminateProcess(child);
  throw new Error(`Timed out waiting for Next dev server on loopback port ${port}:\n${output.join("")}`);
}

async function startBrowser() {
  const executable = findBrowser();
  const profile = await mkdtemp(path.join(os.tmpdir(), "semantic-catalog-browser-"));
  const port = await freePort();
  const child = spawn(executable, [
    "--headless=new",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--disable-default-apps",
    "--no-first-run",
    "--no-default-browser-check",
    "--remote-allow-origins=*",
    "--remote-debugging-address=127.0.0.1",
    `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`,
    "--window-size=1440,1000",
    "about:blank"
  ], { stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  const output = [];
  child.stdout?.on("data", (chunk) => appendOutput(output, chunk));
  child.stderr?.on("data", (chunk) => appendOutput(output, chunk));
  const started = Date.now();
  while (Date.now() - started < 20_000) {
    if (child.exitCode !== null) {
      await rm(profile, { recursive: true, force: true }).catch(() => undefined);
      throw new Error(`Headless browser exited with ${child.exitCode}:\n${output.join("")}`);
    }
    try {
      const version = JSON.parse((await httpRequest(`http://127.0.0.1:${port}/json/version`, 1_000)).body);
      if (version.webSocketDebuggerUrl) return { child, port, profile, version, output };
    } catch {
      // Remote debugging endpoint is not ready yet.
    }
    await delay(50);
  }
  await terminateProcess(child);
  await rm(profile, { recursive: true, force: true }).catch(() => undefined);
  throw new Error(`Timed out waiting for installed Edge/Chrome CDP endpoint on ${port}:\n${output.join("")}`);
}

async function connectTarget(browserWebSocketUrl) {
  const connection = await CdpConnection.connect(browserWebSocketUrl);
  const target = await connection.send("Target.createTarget", { url: "about:blank" });
  const attached = await connection.send("Target.attachToTarget", { targetId: target.targetId, flatten: true });
  return { connection, targetId: target.targetId, sessionId: attached.sessionId };
}

class CdpConnection {
  static async connect(url) {
    const socket = new WebSocket(url);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(new Error(`Timed out opening CDP websocket ${url}`)), 10_000);
      socket.addEventListener("open", () => { clearTimeout(timer); resolve(); }, { once: true });
      socket.addEventListener("error", (event) => { clearTimeout(timer); reject(new Error(`CDP websocket error: ${event.message || "unknown"}`)); }, { once: true });
    });
    return new CdpConnection(socket);
  }

  constructor(socket) {
    this.socket = socket;
    this.nextId = 0;
    this.pending = new Map();
    this.listeners = new Map();
    socket.addEventListener("message", (event) => { void this.handleMessage(event.data); });
    socket.addEventListener("close", () => {
      for (const pending of this.pending.values()) pending.reject(new Error("CDP websocket closed"));
      this.pending.clear();
    });
  }

  on(method, listener) {
    const listeners = this.listeners.get(method) || new Set();
    listeners.add(listener);
    this.listeners.set(method, listeners);
  }

  async handleMessage(data) {
    const text = typeof data === "string" ? data : data instanceof Blob ? await data.text() : Buffer.from(data).toString("utf8");
    const message = JSON.parse(text);
    if (message.id) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(`${message.error.message || "CDP command failed"} (${message.error.code || "unknown"})`));
      else pending.resolve(message.result || {});
      return;
    }
    const listeners = this.listeners.get(message.method);
    if (!listeners) return;
    for (const listener of listeners) listener(message);
  }

  send(method, params = {}, sessionId) {
    const id = ++this.nextId;
    const message = { id, method, params };
    if (sessionId) message.sessionId = sessionId;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      try {
        this.socket.send(JSON.stringify(message));
      } catch (error) {
        this.pending.delete(id);
        reject(error);
      }
    });
  }

  async close() {
    try { this.socket.close(); } catch { /* already closed */ }
  }
}

async function closeRuntime({ server, browser, cdp }) {
  if (cdp?.connection) {
    try {
      if (cdp.sessionId) await cdp.connection.send("Fetch.disable", {}, cdp.sessionId);
    } catch { /* browser is already exiting */ }
    try {
      if (cdp.targetId) await cdp.connection.send("Target.closeTarget", { targetId: cdp.targetId });
    } catch { /* browser is already exiting */ }
    await cdp.connection.close();
  }
  if (browser) {
    await terminateProcess(browser.child);
    await rm(browser.profile, { recursive: true, force: true }).catch(() => undefined);
  }
  if (server) await terminateProcess(server.child);
}

function findBrowser() {
  const candidates = [];
  for (const command of process.platform === "win32" ? ["msedge", "chrome", "chromium"] : ["google-chrome", "chromium", "chromium-browser", "microsoft-edge"]) {
    const result = spawnSync(process.platform === "win32" ? "where.exe" : "which", [command], { encoding: "utf8", windowsHide: true });
    if (result.status === 0) candidates.push(...String(result.stdout || "").split(/\r?\n/).map((value) => value.trim()).filter(Boolean));
  }
  if (process.platform === "win32") {
    candidates.push(
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"
    );
  }
  const executable = candidates.find((candidate) => path.isAbsolute(candidate) && exists(candidate));
  if (!executable) throw new Error("No installed Edge/Chrome executable was found; the production browser suite cannot be skipped.");
  return executable;
}

function exists(value) {
  try { return Boolean(requireStat(value)); } catch { return false; }
}

function requireStat(value) {
  // Dynamic import would make browser discovery asynchronous; access is stable for these install paths.
  const fs = process.getBuiltinModule?.("node:fs") || null;
  if (!fs) return true;
  return fs.statSync(value);
}

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  await new Promise((resolve) => server.close(resolve));
  assert.ok(port > 0, "loopback port allocation failed");
  return port;
}

function httpRequest(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, (response) => {
      const chunks = [];
      response.on("data", (chunk) => chunks.push(chunk));
      response.on("end", () => resolve({ statusCode: response.statusCode || 0, body: Buffer.concat(chunks).toString("utf8") }));
    });
    request.setTimeout(timeoutMs, () => request.destroy(new Error("HTTP request timed out")));
    request.on("error", reject);
  });
}

async function terminateProcess(child) {
  if (!child || child.exitCode !== null) return;
  if (process.platform === "win32" && child.pid) {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore", windowsHide: true });
    return;
  }
  try { child.kill("SIGTERM"); } catch { return; }
  await Promise.race([onceExit(child), delay(3_000)]);
  if (child.exitCode === null) {
    try { child.kill("SIGKILL"); } catch { /* already exited */ }
  }
}

function onceExit(child) {
  return new Promise((resolve) => child.once("exit", resolve));
}

function appendOutput(output, chunk) {
  output.push(String(chunk));
  if (output.length > 80) output.splice(0, output.length - 80);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
