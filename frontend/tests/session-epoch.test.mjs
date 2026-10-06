/**
 * C01 回归：会话代次（session epoch）。
 *
 * 这些用例驱动**真实** `lib/api.ts`（不是独立的 epoch 小工具）：通过替换全局 fetch 与
 * sessionStorage/location，按任务书的四个触发序列断言实际 API 客户端行为。
 *
 * 环境由测试本身提供（无真实 HTTP / 无后端 / 无真实模型）。
 */
import assert from "node:assert/strict";
import { register } from "node:module";
import test from "node:test";

// 产品源码允许省略扩展名的相对导入（`./query-client`），Node 原生 ESM 不解析这类说明符。
// 在测试文件内注册解析钩子，使标准的 `node --test tests/*.test.mjs` 无需额外参数即可运行，
// 也让本用例能驱动**真实** lib/api.ts 而不是替身。
register("./support/ts-resolve-hook.mjs", import.meta.url);

const ACCESS_KEY = "ybt:access-token";
const REFRESH_KEY = "ybt:refresh-token";

/** 最小 sessionStorage 替身（真实实现由 jsdom 提供，这里只需读写语义）。 */
function memoryStorage() {
  const map = new Map();
  return {
    getItem: (key) => (map.has(key) ? map.get(key) : null),
    setItem: (key, value) => map.set(key, String(value)),
    removeItem: (key) => map.delete(key),
    get size() { return map.size; },
  };
}

/** 可编排的 fetch 替身：按 (method path) 记录调用并可返回延迟 Promise。 */
function fetchScript(routes) {
  const calls = [];
  return {
    calls,
    fetch: (url, init = {}) => {
      // API_BASE 本身含 `/api`，因此把前缀归一化掉，路由键才与实际业务路径一致。
      const path = String(url)
        .replace(/^https?:\/\/[^/]+/, "")
        .replace(/^\/api(?=\/|$)/, "");
      const method = init.method || "GET";
      calls.push({ authorization: (init.headers || {}).Authorization, method, path });
      const handler = routes[`${method} ${path}`] ?? routes[path];
      if (!handler) throw new Error(`unrouted ${method} ${path}`);
      return handler({ calls, init, path });
    },
  };
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: { get: () => null },
  };
}

/** 延迟响应：由测试显式 resolve，用来制造“晚到”的顺序。 */
function deferredResponse(status, body) {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  return {
    release: () => release(),
    response: gate.then(() => jsonResponse(status, body)),
  };
}

async function loadApiModule({ fetchImpl, storage, location }) {
  const previous = {
    fetch: globalThis.fetch,
    sessionStorage: globalThis.sessionStorage,
    window: globalThis.window,
  };
  globalThis.fetch = fetchImpl;
  globalThis.window = { location, sessionStorage: storage };
  // 浏览器里 `sessionStorage` 是全局对象；api.ts 直接引用它，所以测试要提供同形环境。
  globalThis.sessionStorage = storage;
  // 每次都以独立查询串加载，避免 ESM 模块缓存把上一个用例的会话代次带进来。
  const module = await import(`../lib/api.ts?case=${Math.random()}`);
  return {
    module,
    restore() {
      globalThis.fetch = previous.fetch;
      if (previous.window === undefined) delete globalThis.window;
      else globalThis.window = previous.window;
      if (previous.sessionStorage === undefined) delete globalThis.sessionStorage;
      else globalThis.sessionStorage = previous.sessionStorage;
    },
  };
}

function fakeLocation() {
  const replaced = [];
  return { replaced, replace: (path) => replaced.push(path) };
}

test("C01 并发 401 仍共享同一次续期", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access-old");
  storage.setItem(REFRESH_KEY, "A-refresh-old");
  const location = fakeLocation();
  const refresh = deferredResponse(200, { access_token: "A-access-new", refresh_token: "A-refresh-new" });
  let refreshCalls = 0;
  // 两个受保护请求都先返回 401；续期完成后（storage 已换新令牌）再返回 200。
  const guarded = () => (storage.getItem(ACCESS_KEY) === "A-access-new"
    ? jsonResponse(200, { ok: true })
    : jsonResponse(401, {}));
  const scripted = fetchScript({
    "POST /auth/refresh": () => { refreshCalls += 1; return refresh.response; },
    "/one": guarded,
    "/two": guarded,
  });
  const { module, restore } = await loadApiModule({
    fetchImpl: scripted.fetch, location, storage,
  });
  try {
    const pending = Promise.all([
      module.apiGet("/one").catch((error) => error),
      module.apiGet("/two").catch((error) => error),
    ]);
    await new Promise((resolve) => setTimeout(resolve, 10));
    refresh.release();
    await pending;
    assert.equal(refreshCalls, 1, "并发 401 只应续期一次（否则刷新令牌会被轮换两次后自失效）");
    assert.equal(storage.getItem(ACCESS_KEY), "A-access-new");
    assert.equal(storage.getItem(REFRESH_KEY), "A-refresh-new");
  } finally {
    restore();
  }
});

test("C01 退出后晚到的续期不得写回旧账号令牌", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access-old");
  storage.setItem(REFRESH_KEY, "A-refresh-old");
  const location = fakeLocation();
  const refresh = deferredResponse(200, { access_token: "A-access-new", refresh_token: "A-refresh-new" });
  let refreshStarted = false;
  const scripted = fetchScript({
    "POST /auth/refresh": () => { refreshStarted = true; return refresh.response; },
    "/guarded": () => (refreshStarted ? jsonResponse(200, { ok: true }) : jsonResponse(401, {})),
  });
  const { module, restore } = await loadApiModule({
    fetchImpl: scripted.fetch, location, storage,
  });
  try {
    const pending = module.apiGet("/guarded").catch((error) => error);
    await new Promise((resolve) => setTimeout(resolve, 10));
    assert.equal(refreshStarted, true, "应已发起续期");

    // 用户在续期返回前退出登录。
    await module.logoutSession();
    assert.equal(storage.getItem(ACCESS_KEY), null, "退出后本地不应再有访问令牌");

    refresh.release();
    await pending;
    await new Promise((resolve) => setTimeout(resolve, 20));

    assert.equal(storage.getItem(ACCESS_KEY), null, "晚到的续期不得写回访问令牌");
    assert.equal(storage.getItem(REFRESH_KEY), null, "晚到的续期不得写回刷新令牌");
  } finally {
    restore();
  }
});

test("C01 A→B 切换后，A 的晚到续期不得覆盖 B 的会话", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access-old");
  storage.setItem(REFRESH_KEY, "A-refresh-old");
  const location = fakeLocation();
  const refresh = deferredResponse(200, { access_token: "A-access-new", refresh_token: "A-refresh-new" });
  let refreshStarted = false;
  const scripted = fetchScript({
    "POST /auth/refresh": () => { refreshStarted = true; return refresh.response; },
    "/guarded": () => (refreshStarted ? jsonResponse(200, { ok: true }) : jsonResponse(401, {})),
  });
  const { module, restore } = await loadApiModule({
    fetchImpl: scripted.fetch, location, storage,
  });
  try {
    const pending = module.apiGet("/guarded").catch((error) => error);
    await new Promise((resolve) => setTimeout(resolve, 10));

    // 退出 A 并登录 B。
    module.clearSession();
    module.saveSession("B-access", "B-refresh");

    refresh.release();
    await pending;
    await new Promise((resolve) => setTimeout(resolve, 20));

    assert.equal(storage.getItem(ACCESS_KEY), "B-access", "B 的访问令牌不得被 A 的晚到续期覆盖");
    assert.equal(storage.getItem(REFRESH_KEY), "B-refresh", "B 的刷新令牌不得被 A 的晚到续期覆盖");
  } finally {
    restore();
  }
});

test("C01 旧请求晚到的 401 不得清掉新会话或跳登录页", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "B-access");
  storage.setItem(REFRESH_KEY, "B-refresh");
  const location = fakeLocation();
  const { module, restore } = await loadApiModule({
    fetchImpl: fetchScript({}).fetch, location, storage,
  });
  try {
    // 模拟“属于旧代次”的 401 环境：isCurrentSession 返回 false。
    const environment = {
      isCurrentSession: () => false,
      location,
      sessionStorage: storage,
    };
    const { throwApiError } = await import("../lib/http-response.mjs");
    await assert.rejects(
      () => throwApiError(jsonResponse(401, { detail: "expired" }), "/old", environment),
      (error) => error.status === 401
    );
    assert.equal(storage.getItem(ACCESS_KEY), "B-access", "旧会话 401 不得清掉新会话令牌");
    assert.deepEqual(location.replaced, [], "旧会话 401 不得跳转登录页");
    assert.ok(module.hasSession(), "新会话仍应存在");
  } finally {
    restore();
  }
});

test("C01 同会话 401 仍按原行为清会话并跳登录", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access");
  storage.setItem(REFRESH_KEY, "A-refresh");
  const location = fakeLocation();
  const { throwApiError } = await import("../lib/http-response.mjs");
  const environment = { isCurrentSession: () => true, location, sessionStorage: storage };
  // 原行为保持：跳转后返回永不 settle 的 Promise（页面即将整体跳转）。
  void throwApiError(jsonResponse(401, {}), "/x", environment);
  await new Promise((resolve) => setTimeout(resolve, 10));
  assert.equal(storage.getItem(ACCESS_KEY), null);
  assert.deepEqual(location.replaced, ["/login"]);
});

test("C01 退出调用服务端 logout 吊销刷新令牌（网络异常不阻塞本地退出）", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access");
  storage.setItem(REFRESH_KEY, "A-refresh");
  const location = fakeLocation();
  const scripted = fetchScript({
    "POST /auth/logout": () => jsonResponse(200, { status: "logged_out" }),
  });
  const { module, restore } = await loadApiModule({
    fetchImpl: scripted.fetch, location, storage,
  });
  try {
    await module.logoutSession();
    assert.equal(storage.getItem(ACCESS_KEY), null);
    assert.equal(storage.getItem(REFRESH_KEY), null);
    const logoutCalls = scripted.calls.filter((call) => call.path === "/auth/logout");
    assert.equal(logoutCalls.length, 1, "退出应调用一次服务端 logout");
    assert.equal(scripted.calls.filter((call) => call.authorization).length, 0,
      "logout 用刷新令牌吊销，不携带访问令牌");
  } finally {
    restore();
  }
});

test("C01 服务端 logout 抛错时本地退出仍已完成", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access");
  storage.setItem(REFRESH_KEY, "A-refresh");
  const { module, restore } = await loadApiModule({
    fetchImpl: () => { throw new TypeError("network down"); },
    location: fakeLocation(),
    storage,
  });
  try {
    await module.logoutSession();
    assert.equal(storage.getItem(ACCESS_KEY), null);
    assert.equal(storage.getItem(REFRESH_KEY), null);
  } finally {
    restore();
  }
});

// ---------------------------------------------------------------------------------------------
// R01：正常续期成功后原请求必须真正重放并返回业务结果。
//
// 复核指出原 C01 用例把请求拒绝 catch 成普通值，只检查 token 与续期次数，**没有断言业务成功**：
// 即使“正常 401 → refresh 200 后仍返回 401”也照样通过。以下用例断言**返回值本身**。
// ---------------------------------------------------------------------------------------------

/** 带 blob/headers 的响应，用于下载类接口。 */
function binaryResponse(status, { body = null, fileName = null } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    blob: async () => body,
    json: async () => body,
    text: async () => JSON.stringify(body),
    headers: { get: (name) => (name.toLowerCase() === "content-disposition" && fileName ? `attachment; filename="${fileName}"` : null) },
  };
}

test("R01 普通 GET 401 续期成功后原请求成功返回业务数据", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access-old");
  storage.setItem(REFRESH_KEY, "A-refresh-old");
  const location = fakeLocation();
  let refreshCalls = 0;
  const scripted = fetchScript({
    "POST /auth/refresh": () => {
      refreshCalls += 1;
      return jsonResponse(200, { access_token: "A-access-new", refresh_token: "A-refresh-new" });
    },
    "/jobs/7": () => (storage.getItem(ACCESS_KEY) === "A-access-new"
      ? jsonResponse(200, { id: 7, status: "running" })
      : jsonResponse(401, { detail: "expired" })),
  });
  const { module, restore } = await loadApiModule({ fetchImpl: scripted.fetch, location, storage });
  try {
    const job = await module.apiGet("/jobs/7");
    // 业务结果（而不是“没有抛错”或“token 变了”）。
    assert.deepEqual(job, { id: 7, status: "running" }, "续期成功后必须拿到原请求的业务数据");
    assert.equal(refreshCalls, 1, "正常续期只应发生一次");
    assert.equal(scripted.calls.filter((call) => call.path === "/jobs/7").length, 2,
      "原请求应被重放（首次 401 + 重放成功）");
    assert.equal(scripted.calls.at(-1).authorization, "Bearer A-access-new", "重放必须携带新令牌");
  } finally {
    restore();
  }
});

test("R01 普通 POST 401 续期成功后成功且业务写入只发生一次", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access-old");
  storage.setItem(REFRESH_KEY, "A-refresh-old");
  const location = fakeLocation();
  const bodies = [];
  const scripted = fetchScript({
    "POST /auth/refresh": () => jsonResponse(200, { access_token: "A-access-new", refresh_token: "A-refresh-new" }),
    "POST /requirements": ({ init }) => {
      bodies.push(init.body);
      return storage.getItem(ACCESS_KEY) === "A-access-new"
        ? jsonResponse(200, { request_id: 31, status: "queued" })
        : jsonResponse(401, { detail: "expired" });
    },
  });
  const { module, restore } = await loadApiModule({ fetchImpl: scripted.fetch, location, storage });
  try {
    const created = await module.apiPost("/requirements", { project_id: 11 });
    assert.deepEqual(created, { request_id: 31, status: "queued" }, "POST 重放后必须返回业务结果");
    // 首次携带令牌被拒（服务端未落库），重放才成功：请求体必须一致。
    assert.equal(bodies.length, 2);
    assert.equal(bodies[0], bodies[1], "重放必须使用同一请求体");
  } finally {
    restore();
  }
});

test("R01 下载接口 401 续期成功后返回文件而不是报错", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access-old");
  storage.setItem(REFRESH_KEY, "A-refresh-old");
  const location = fakeLocation();
  const scripted = fetchScript({
    "POST /auth/refresh": () => jsonResponse(200, { access_token: "A-access-new", refresh_token: "A-refresh-new" }),
    "GET /deliverables/1/export": () => (storage.getItem(ACCESS_KEY) === "A-access-new"
      ? binaryResponse(200, { body: "xlsx-bytes", fileName: "交付包.xlsx" })
      : jsonResponse(401, { detail: "expired" })),
  });
  const { module, restore } = await loadApiModule({ fetchImpl: scripted.fetch, location, storage });
  try {
    const file = await module.apiDownload("/deliverables/1/export");
    assert.equal(file.blob, "xlsx-bytes", "下载重放后必须拿到文件内容");
    assert.equal(file.fileName, "交付包.xlsx", "必须保留服务端的文件名");
  } finally {
    restore();
  }
});

test("R01 两条并发 401 均成功且只续期一次", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access-old");
  storage.setItem(REFRESH_KEY, "A-refresh-old");
  const location = fakeLocation();
  let refreshCalls = 0;
  const scripted = fetchScript({
    "POST /auth/refresh": () => {
      refreshCalls += 1;
      return jsonResponse(200, { access_token: "A-access-new", refresh_token: "A-refresh-new" });
    },
    "/jobs/101": () => (storage.getItem(ACCESS_KEY) === "A-access-new"
      ? jsonResponse(200, { id: 101, status: "completed" })
      : jsonResponse(401, { detail: "expired" })),
    "/jobs/102": () => (storage.getItem(ACCESS_KEY) === "A-access-new"
      ? jsonResponse(200, { id: 102, status: "failed" })
      : jsonResponse(401, { detail: "expired" })),
  });
  const { module, restore } = await loadApiModule({ fetchImpl: scripted.fetch, location, storage });
  try {
    const [a, b] = await Promise.all([module.apiGet("/jobs/101"), module.apiGet("/jobs/102")]);
    assert.deepEqual(a, { id: 101, status: "completed" }, "并发中的第一条也必须成功");
    assert.deepEqual(b, { id: 102, status: "failed" }, "并发中的第二条也必须成功");
    assert.equal(refreshCalls, 1, "并发 401 只应续期一次");
  } finally {
    restore();
  }
});

test("R01 旧 A 请求晚到 401 不得启动 B 的续期，也不得动 B 的会话", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access-old");
  storage.setItem(REFRESH_KEY, "A-refresh-old");
  const location = fakeLocation();
  const gate = deferredResponse(401, { detail: "expired" });
  const refreshBodies = [];
  const scripted = fetchScript({
    "POST /auth/refresh": ({ init }) => {
      refreshBodies.push(JSON.parse(init.body).refresh_token);
      return jsonResponse(200, { access_token: "WRONG", refresh_token: "WRONG" });
    },
    "/guarded": () => gate.response,
  });
  const { module, restore } = await loadApiModule({ fetchImpl: scripted.fetch, location, storage });
  try {
    const pending = module.apiGet("/guarded").catch((error) => error);
    await new Promise((resolve) => setTimeout(resolve, 10));

    // A 的请求还在飞的时候，用户切到 B。
    module.clearSession();
    module.saveSession("B-access", "B-refresh");

    gate.release();
    const error = await pending;

    assert.equal(error.status, 401, "旧请求本身应失败（它属于已作废的会话）");
    assert.deepEqual(refreshBodies, [], "旧 A 请求的晚到 401 绝不能启动 B 的续期");
    assert.equal(storage.getItem(ACCESS_KEY), "B-access", "B 的访问令牌不得被触碰");
    assert.equal(storage.getItem(REFRESH_KEY), "B-refresh", "B 的刷新令牌不得被触碰");
    assert.deepEqual(location.replaced, [], "旧会话 401 不得把用户踢到登录页");
  } finally {
    restore();
  }
});

test("R01 旧续期只能清理自己的飞行记录，不得影响新会话的续期", async () => {
  const storage = memoryStorage();
  storage.setItem(ACCESS_KEY, "A-access-old");
  storage.setItem(REFRESH_KEY, "A-refresh-old");
  const location = fakeLocation();
  const gateA = deferredResponse(200, { access_token: "A-access-new", refresh_token: "A-refresh-new" });
  let refreshCalls = 0;
  const scripted = fetchScript({
    "POST /auth/refresh": ({ init }) => {
      refreshCalls += 1;
      const body = JSON.parse(init.body).refresh_token;
      // A 的续期挂起；B 的续期（登录后新发）立即成功。
      return body === "A-refresh-old" ? gateA.response
        : jsonResponse(200, { access_token: "B-access-new", refresh_token: "B-refresh-new" });
    },
    "/guarded": () => (storage.getItem(ACCESS_KEY) === "A-access-new"
      ? jsonResponse(200, { ok: "A" })
      : jsonResponse(401, { detail: "expired" })),
  });
  const { module, restore } = await loadApiModule({ fetchImpl: scripted.fetch, location, storage });
  try {
    const pendingA = module.apiGet("/guarded").catch((error) => error);
    await new Promise((resolve) => setTimeout(resolve, 10));

    // 切到 B，并为 B 发起一次真实续期（B 的令牌已过期）。
    module.clearSession();
    module.saveSession("B-access-old", "B-refresh-old");
    const refreshedB = await module.refreshSession();
    assert.equal(refreshedB, true, "B 的续期应成功");
    assert.equal(storage.getItem(ACCESS_KEY), "B-access-new");

    // A 的续期现在才回来：只能丢弃自己的结果。
    gateA.release();
    await pendingA;
    await new Promise((resolve) => setTimeout(resolve, 10));

    assert.equal(storage.getItem(ACCESS_KEY), "B-access-new", "A 的晚到续期不得覆盖 B");
    assert.equal(storage.getItem(REFRESH_KEY), "B-refresh-new", "A 的晚到续期不得覆盖 B 的刷新令牌");
    // 关键：A 的收尾不得把 B 仍在使用的飞行记录清掉。
    const secondB = await module.refreshSession();
    assert.equal(secondB, true, "B 仍能复用/发起自己的续期");
    assert.equal(refreshCalls, 3, "A、B 各一次，外加本次 B 的再次续期");
  } finally {
    restore();
  }
});
