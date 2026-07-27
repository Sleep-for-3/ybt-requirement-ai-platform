import assert from "node:assert/strict";
import test from "node:test";

import { describeKnowledgeJob, isTerminalJob } from "../lib/background-job.mjs";

test("knowledge ingestion progress is visible until the job completes", () => {
  assert.equal(
    describeKnowledgeJob({ status: "queued", progress: 0 }),
    "文件已上传，等待后台索引"
  );
  assert.equal(
    describeKnowledgeJob({
      status: "running",
      progress: 46,
      current_step: "知识索引 400/1000"
    }),
    "知识索引 400/1000（46%）"
  );
  assert.equal(
    describeKnowledgeJob({ status: "completed", progress: 100 }),
    "解析和索引完成"
  );
  assert.equal(isTerminalJob({ status: "running" }), false);
  assert.equal(isTerminalJob({ status: "completed" }), true);
});

test("knowledge ingestion failure exposes the worker error", () => {
  assert.equal(
    describeKnowledgeJob({
      status: "failed",
      progress: 100,
      error_message: "Unsupported knowledge document format"
    }),
    "索引失败：Unsupported knowledge document format"
  );
});
