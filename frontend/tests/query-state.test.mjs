/**
 * W07: 403 / 500 / dropped connection must never render as "暂无记录".
 */
import test from "node:test";
import assert from "node:assert/strict";

import { ApiError } from "../lib/http-response.mjs";
import {
  QUERY_KIND,
  classifyQueryState,
  isRetryable,
  lastSuccessLabel,
  withLastSuccess,
} from "../lib/query-state.mjs";

test("加载中、成功、空结果分别归类", () => {
  assert.equal(classifyQueryState({ isPending: true }).kind, QUERY_KIND.loading);
  assert.equal(classifyQueryState({ hasData: true, itemCount: 3 }).kind, QUERY_KIND.ready);
  assert.equal(classifyQueryState({ hasData: true, itemCount: 0 }).kind, QUERY_KIND.empty);
});

test("403 归类为无权限而不是空结果", () => {
  const state = classifyQueryState({ isError: true, error: new ApiError("当前账号无权执行此操作", 403) });
  assert.equal(state.kind, QUERY_KIND.forbidden);
  assert.equal(state.status, 403);
  assert.notEqual(state.kind, QUERY_KIND.empty);
  assert.equal(isRetryable(state.kind), false);
});

test("断网归类为 offline 且可重试", () => {
  const state = classifyQueryState({ isError: true, error: new TypeError("Failed to fetch") });
  assert.equal(state.kind, QUERY_KIND.offline);
  assert.equal(state.status, 0);
  assert.equal(isRetryable(state.kind), true);
});

test("500 归类为 error 且可重试，绝不是空结果", () => {
  const state = classifyQueryState({ isError: true, error: new ApiError("服务器处理失败", 500) });
  assert.equal(state.kind, QUERY_KIND.error);
  assert.equal(state.status, 500);
  assert.equal(isRetryable(state.kind), true);
  for (const status of [403, 500, 503]) {
    const kind = classifyQueryState({ isError: true, error: new ApiError("x", status) }).kind;
    assert.notEqual(kind, QUERY_KIND.empty, String(status));
  }
});

test("错误优先于空数据：即使 hasData 为假也不能判为空结果", () => {
  const state = classifyQueryState({ isError: true, error: new ApiError("请求失败", 500), hasData: false, itemCount: 0 });
  assert.equal(state.kind, QUERY_KIND.error);
});

test("失败不会清掉最后一次成功的数据与时间", () => {
  const first = withLastSuccess(null, { data: [1, 2, 3], at: "2026-10-04T09:00:00+08:00" });
  assert.deepEqual(first.data, [1, 2, 3]);
  assert.equal(lastSuccessLabel(first), "数据更新于 2026-10-04T09:00:00+08:00");

  // a later failure carries no payload and must keep the previous snapshot
  const afterFailure = withLastSuccess(first, { data: null });
  assert.equal(afterFailure, first);

  const afterRefresh = withLastSuccess(first, { data: [4], at: "2026-10-04T10:00:00+08:00" });
  assert.deepEqual(afterRefresh.data, [4]);
  assert.equal(afterRefresh.at, "2026-10-04T10:00:00+08:00");
});

test("没有成功记录时不编造更新时间", () => {
  assert.equal(lastSuccessLabel(null), "");
  assert.equal(withLastSuccess(null, undefined), null);
});
