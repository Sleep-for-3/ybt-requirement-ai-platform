import assert from "node:assert/strict";
import test from "node:test";

import { createAsyncActionRunner } from "../lib/async-action.mjs";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, reject, resolve };
}

test("an action locks immediately and duplicate clicks share no second request", async () => {
  const request = deferred();
  let calls = 0;
  const states = [];
  const runner = createAsyncActionRunner({
    onStateChange: (state) => states.push(state)
  });

  const first = runner.run(async () => {
    calls += 1;
    return request.promise;
  });
  const duplicate = await runner.run(async () => {
    calls += 1;
    return "duplicate";
  });

  assert.equal(runner.isRunning(), true);
  assert.equal(calls, 1);
  assert.deepEqual(duplicate, { executed: false });
  assert.equal(states[0].status, "submitting");

  request.resolve("created");
  assert.deepEqual(await first, { executed: true, value: "created" });
  assert.equal(runner.isRunning(), false);
});

test("success and failure callbacks run and finally always restores idle", async () => {
  const events = [];
  const runner = createAsyncActionRunner({
    onError: (error) => events.push(`error:${error.message}`),
    onFinally: () => events.push("finally"),
    onStateChange: (state) => events.push(state.status),
    onSuccess: (value) => events.push(`success:${value}`)
  });

  await runner.run(async () => "ok");
  await assert.rejects(
    runner.run(async () => {
      throw new Error("broken");
    }),
    /broken/
  );

  assert.deepEqual(events, [
    "submitting",
    "success:ok",
    "success",
    "finally",
    "idle",
    "submitting",
    "error:broken",
    "failed",
    "finally",
    "idle"
  ]);
});

test("a cancelled confirmation never invokes the protected action", async () => {
  let calls = 0;
  const runner = createAsyncActionRunner();

  const result = await runner.runConfirmed(
    async () => false,
    async () => {
      calls += 1;
    }
  );

  assert.equal(calls, 0);
  assert.deepEqual(result, { executed: false });
});
