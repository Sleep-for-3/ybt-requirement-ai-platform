import assert from "node:assert/strict";
import test from "node:test";

import { createJobPollingRegistry, isTerminalJobStatus } from "../lib/job-polling.mjs";

function fakeTimers() {
  const pending = [];
  return {
    clearTimer: (token) => {
      const item = pending.find((candidate) => candidate.token === token);
      if (item) item.cancelled = true;
    },
    flush: async () => {
      const item = pending.shift();
      if (item && !item.cancelled) await item.callback();
    },
    pending,
    setTimer: (callback, delay) => {
      const token = Symbol("timer");
      pending.push({ callback, cancelled: false, delay, token });
      return token;
    }
  };
}

test("one job id owns one poller and terminal state stops polling", async () => {
  const timers = fakeTimers();
  const responses = [
    { id: 9, status: "running" },
    { id: 9, status: "completed" }
  ];
  let requests = 0;
  const registry = createJobPollingRegistry({
    ...timers,
    fetchJob: async () => {
      requests += 1;
      return responses.shift();
    }
  });
  const first = [];
  const second = [];

  const unsubscribeFirst = registry.subscribe(9, (value) => first.push(value));
  const unsubscribeSecond = registry.subscribe(9, (value) => second.push(value));
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(requests, 1);
  assert.equal(registry.size(), 1);
  assert.equal(timers.pending.length, 1);
  await timers.flush();
  assert.equal(requests, 2);
  assert.equal(registry.size(), 0);
  assert.equal(timers.pending.length, 0);
  assert.equal(first.at(-1).status, "completed");
  assert.equal(second.at(-1).status, "completed");
  unsubscribeFirst();
  unsubscribeSecond();
});

test("unsubscribing the last listener stops future polling", async () => {
  const timers = fakeTimers();
  let requests = 0;
  const registry = createJobPollingRegistry({
    ...timers,
    fetchJob: async () => {
      requests += 1;
      return { id: 12, status: "running" };
    }
  });

  const unsubscribe = registry.subscribe(12, () => undefined);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(timers.pending.length, 1);
  unsubscribe();
  await timers.flush();
  assert.equal(requests, 1);
  assert.equal(registry.size(), 0);
});

test("temporary network errors retry finitely with backoff", async () => {
  const timers = fakeTimers();
  const failures = [];
  let requests = 0;
  const registry = createJobPollingRegistry({
    ...timers,
    maxErrors: 2,
    fetchJob: async () => {
      requests += 1;
      throw new TypeError("Failed to fetch");
    },
    onPollingError: (error) => failures.push(error.message)
  });

  registry.subscribe(15, () => undefined);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(timers.pending[0].delay, 3000);
  await timers.flush();
  assert.equal(requests, 2);
  // C11：达到 maxErrors 后**停止轮询但保留订阅**（旧契约是删除条目，
  // 导致网络恢复后再也无法查询、界面永久停在旧状态且没有错误提示）。
  assert.equal(registry.size(), 1);
  assert.equal(registry.isStalled(15), true);
  assert.equal(timers.pending.length, 0);
  assert.deepEqual(failures, ["后台任务状态暂时无法更新"]);

  // C11：同一个订阅者在重连后能重新发起拉取（fetchJob 在本用例里始终失败，
  // 因此它会再次进入 stalled，但重试确实发生了 —— 旧实现在这里是 0 次）。
  const before = requests;
  const unsubscribe = registry.subscribe(15, () => undefined);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(requests > before, true, "重新订阅必须重新拉取");
  unsubscribe();
  unsubscribe();
});

test("all supported terminal states stop polling", () => {
  for (const status of ["completed", "failed", "partially_completed", "cancelled", "timed_out"]) {
    assert.equal(isTerminalJobStatus(status), true);
  }
  assert.equal(isTerminalJobStatus("running"), false);
});

test("polling pauses while the document is hidden and resumes when visible", async () => {
  const timers = fakeTimers();
  let hidden = false;
  let visibilityListener = () => undefined;
  let requests = 0;
  const registry = createJobPollingRegistry({
    ...timers,
    fetchJob: async () => {
      requests += 1;
      return { id: 21, status: "running" };
    },
    isHidden: () => hidden,
    subscribeVisibility: (listener) => {
      visibilityListener = listener;
      return () => { visibilityListener = () => undefined; };
    }
  });

  registry.subscribe(21, () => undefined);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(requests, 1);
  assert.equal(timers.pending.length, 1);

  hidden = true;
  visibilityListener();
  await timers.flush();
  assert.equal(requests, 1);

  hidden = false;
  visibilityListener();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(requests, 2);
});

test("terminal listeners run once even when visibility changes", async () => {
  const timers = fakeTimers();
  let visibilityListener = () => undefined;
  let terminalNotifications = 0;
  const registry = createJobPollingRegistry({
    ...timers,
    fetchJob: async () => ({ id: 22, status: "completed" }),
    isHidden: () => false,
    subscribeVisibility: (listener) => {
      visibilityListener = listener;
      return () => undefined;
    }
  });

  registry.subscribe(22, () => { terminalNotifications += 1; });
  await Promise.resolve();
  await Promise.resolve();
  visibilityListener();
  await Promise.resolve();

  assert.equal(terminalNotifications, 1);
  assert.equal(registry.size(), 0);
});

// --------------------------------------------------------------------------- C11

test("C11 三次断网后：有可见状态、重连可取到真实终态", async () => {
  const timers = fakeTimers();
  let onlineListener = () => undefined;
  let fail = true;
  let requests = 0;
  const failures = [];
  const seen = [];
  const registry = createJobPollingRegistry({
    ...timers,
    maxErrors: 3,
    fetchJob: async () => {
      requests += 1;
      if (fail) throw new TypeError("Failed to fetch");
      return { id: 31, status: "completed" };
    },
    onPollingError: (error, info) => failures.push([error.message, info && info.canResume]),
    subscribeOnline: (listener) => {
      onlineListener = listener;
      return () => { onlineListener = () => undefined; };
    }
  });

  registry.subscribe(31, (job) => seen.push(job.status));
  // 三次失败（maxErrors=3）后停轮询但有可见状态。
  for (let i = 0; i < 3; i += 1) {
    await Promise.resolve();
    await Promise.resolve();
    if (timers.pending.length > 0) await timers.flush();
  }
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(requests >= 3, true, `requests=${requests}`);
  assert.equal(registry.isStalled(31), true, "断网后必须有可见的停轮询状态");
  assert.deepEqual(failures, [["后台任务状态暂时无法更新", true]]);

  // 网络恢复：online 事件必须重新拉取并拿到真实终态。
  fail = false;
  onlineListener();
  // poll() 是异步链（fetch → 写 listener → 判终态），多给几个微任务轮次。
  for (let i = 0; i < 6; i += 1) await Promise.resolve();
  assert.deepEqual(seen, ["completed"]);
  assert.equal(registry.size(), 0);
});

test("C11 重复订阅不重复拉取", async () => {
  const timers = fakeTimers();
  let requests = 0;
  const registry = createJobPollingRegistry({
    ...timers,
    fetchJob: async () => {
      requests += 1;
      return { id: 32, status: "running" };
    }
  });

  const a = registry.subscribe(32, () => undefined);
  const b = registry.subscribe(32, () => undefined);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(requests, 1, "同一 jobId 的第二个订阅者不得再触发一次请求");
  assert.equal(timers.pending.length, 1);
  a();
  b();
});

test("C11 终态不再轮询", async () => {
  const timers = fakeTimers();
  let requests = 0;
  const registry = createJobPollingRegistry({
    ...timers,
    fetchJob: async () => {
      requests += 1;
      return { id: 33, status: "cancelled" };
    }
  });

  registry.subscribe(33, () => undefined);
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(requests, 1);
  assert.equal(timers.pending.length, 0, "终态后不得再排程");
  assert.equal(registry.size(), 0);
});

test("C11 取消订阅后晚到的结果被丢弃", async () => {
  const timers = fakeTimers();
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const seen = [];
  const registry = createJobPollingRegistry({
    ...timers,
    fetchJob: async () => {
      await gate;
      return { id: 34, status: "completed" };
    }
  });

  const unsubscribe = registry.subscribe(34, (job) => seen.push(job.status));
  await Promise.resolve();
  unsubscribe();
  release();
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
  assert.deepEqual(seen, [], "取消订阅后晚到的结果不得再通知旧界面");
  assert.equal(registry.size(), 0);
});
