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
  assert.equal(registry.size(), 0);
  assert.equal(timers.pending.length, 0);
  assert.deepEqual(failures, ["后台任务状态暂时无法更新"]);
});

test("all supported terminal states stop polling", () => {
  for (const status of ["completed", "failed", "partially_completed", "cancelled", "timed_out"]) {
    assert.equal(isTerminalJobStatus(status), true);
  }
  assert.equal(isTerminalJobStatus("running"), false);
});
