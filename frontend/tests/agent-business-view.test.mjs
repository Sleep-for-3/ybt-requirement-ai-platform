import assert from "node:assert/strict";
import test from "node:test";

import {
  TASK_BUSINESS_STATE_LABELS,
  TASK_FILTERS,
  artifactStatusLabel,
  artifactTypeLabel,
  artifactViews,
  businessObjectLabel,
  citationViews,
  conclusionView,
  filterTaskRows,
  isTaskTerminal,
  taskBusinessStateLabel,
  taskBusinessStateTone,
  taskDetailView,
  taskFilterCounts,
  taskRowView,
  taskTitle,
} from "../app/agent/view-model.ts";

const INTERNAL_ENUMS = [
  "created",
  "planning",
  "running",
  "waiting_human",
  "blocked",
  "completed",
  "failed",
  "cancelled",
];

function row(overrides = {}) {
  return {
    id: 1,
    status: "completed",
    objective: "互联网贷款协议表都有哪些主要字段？",
    object_label: "互联网贷款协议表",
    created_at: "2026-11-05T08:00:00+08:00",
    updated_at: "2026-11-05T09:00:00+08:00",
    result_brief: { kind: "none", headline: "任务已结束，暂无可展示结果。" },
    pending_action: null,
    ...overrides,
  };
}

function snapshot({
  task: taskOverrides = {},
  artifacts = [],
  steps = [],
  gaps = [],
  counts = {},
} = {}) {
  return {
    task: {
      id: 1,
      status: "completed",
      objective: "互联网贷款协议表都有哪些主要字段？",
      object_label: "互联网贷款协议表",
      created_at: "2026-11-05T08:00:00+08:00",
      counts: { steps: steps.length, evidence: 0, ...counts },
      ...taskOverrides,
    },
    steps,
    artifacts,
    gaps,
  };
}

function answerArtifact({ summary = {}, status = "confirmed", id = 11 } = {}) {
  return {
    id,
    artifact_type: "knowledge_answer",
    title: "问答：互联网贷款协议表都有哪些主要字段？",
    status,
    summary: {
      body: "按项目元数据目录，该表包含 4 个字段。",
      answer_status: "grounded",
      ...summary,
    },
  };
}

test("任务状态映射为业务中文，且不暴露内部枚举", () => {
  for (const status of INTERNAL_ENUMS) {
    const label = taskBusinessStateLabel(status);
    assert.ok(label.length > 0, `${status} 缺少中文标签`);
    assert.ok(!INTERNAL_ENUMS.includes(label), `${status} 直接显示了内部枚举 ${label}`);
    assert.ok(TASK_BUSINESS_STATE_LABELS[status], `${status} 未登记在映射表`);
    assert.ok(taskBusinessStateTone(status));
  }
  assert.equal(taskBusinessStateLabel("waiting_human"), "等待人工处理");
  assert.equal(taskBusinessStateLabel("failed"), "处理失败");
  assert.equal(taskBusinessStateLabel(null), "状态待确认");
  assert.equal(taskBusinessStateLabel("unknown_new_status"), "状态待确认");
  // 终态判定与轮询逻辑一致：只有结束状态停止刷新。
  assert.equal(isTaskTerminal("completed"), true);
  assert.equal(isTaskTerminal("cancelled"), true);
  assert.equal(isTaskTerminal("failed"), false);
  assert.equal(isTaskTerminal("waiting_human"), false);
  assert.equal(isTaskTerminal("running"), false);
});

test("完成但无结果的任务给出明确空态文案与过程入口", () => {
  const view = conclusionView(snapshot({ task: { status: "completed" } }));
  assert.equal(view.kind, "none");
  assert.equal(view.primaryAction.key, "process");
  assert.equal(view.secondaryActions[0].key, "retry");
  assert.ok(view.body.includes("没有可展示的结论"), view.body);
  assert.ok(view.sourceLabel.includes("无结论"), view.sourceLabel);
  assert.equal(view.reviewTaskId, null);

  const detail = taskDetailView(snapshot({ task: { status: "completed" } }));
  assert.equal(detail.title, "互联网贷款协议表都有哪些主要字段？");
  assert.equal(detail.objectLabel, "互联网贷款协议表");
  assert.equal(detail.stateLabel, "已完成");
});

test("运行中/失败/取消各自保留自己的主操作，不被历史产出覆盖", () => {
  const artifact = answerArtifact();
  const running = conclusionView(snapshot({ task: { status: "running" }, artifacts: [artifact] }));
  assert.equal(running.primaryAction.key, "refresh");
  assert.ok(running.body.includes("自动刷新"), running.body);

  const failed = conclusionView(snapshot({
    task: { status: "failed", error_code: "timeout" },
    steps: [{ id: 1, step_key: "run", tool_key: "run_sql", status: "failed", error_code: "timeout" }],
  }));
  assert.equal(failed.primaryAction.key, "retry");
  assert.ok(!failed.body.toLowerCase().includes("select"), failed.body);

  const cancelled = conclusionView(snapshot({ task: { status: "cancelled" } }));
  assert.equal(cancelled.primaryAction.key, "retry");

  const waiting = conclusionView(snapshot({
    task: { status: "waiting_human" },
    steps: [{
      id: 2,
      step_key: "clarify_subject",
      tool_key: "clarify_subject",
      status: "waiting_human",
      summary: { title: "确认分析对象", reason: "存在多个候选对象", requirement: "请选择其中一个" },
    }],
  }));
  assert.equal(waiting.primaryAction.key, "handle");
  assert.ok(waiting.heading.startsWith("等待你处理"), waiting.heading);
});

test("依据强度按引用/回答状态推导，并给出可读信号", () => {
  const cited = conclusionView(snapshot({
    artifacts: [answerArtifact({
      summary: {
        citations: [{ title: "商业银行互联网贷款管理暂行办法 第二十七条", quote: "应在协议中明确各方权责", source_type: "policy_clause" }],
      },
    })],
  }));
  assert.equal(cited.basisKind, "cited");
  assert.ok(cited.signals.some((item) => item.label.includes("引用")), JSON.stringify(cited.signals));

  const insufficient = conclusionView(snapshot({
    artifacts: [answerArtifact({ summary: { answer_status: "insufficient_evidence" } })],
  }));
  assert.equal(insufficient.basisKind, "insufficient");
  assert.ok(insufficient.signals.some((item) => item.label === "依据不足"));
  assert.ok(insufficient.sourceLabel.includes("证据不足"), insufficient.sourceLabel);
  assert.ok(insufficient.secondaryActions.some((item) => item.key === "retry"));

  const metadataOnly = conclusionView(snapshot({
    artifacts: [answerArtifact({ summary: { answer_status: "metadata_only" } })],
  }));
  assert.equal(metadataOnly.basisKind, "metadata_only");
  assert.ok(metadataOnly.signals.some((item) => item.label.includes("元数据")));
  assert.ok(metadataOnly.sourceLabel.includes("元数据目录"), metadataOnly.sourceLabel);

  // 运行中的任务不应被判成“无可追溯引用”。
  const running = conclusionView(snapshot({ task: { status: "running" }, artifacts: [answerArtifact()] }));
  assert.ok(!running.signals.some((item) => item.label === "无可追溯引用"), JSON.stringify(running.signals));

  // 完成且有产出但没有引用 → 明确提示无引用，而不是沉默。
  const missing = conclusionView(snapshot({
    artifacts: [answerArtifact({ summary: { answer_status: "" } })],
  }));
  assert.equal(missing.basisKind, "missing");
  assert.ok(missing.signals.some((item) => item.label === "无可追溯引用"));
});

test("待复核草稿可定位到真实复核任务", () => {
  const pending = answerArtifact({ status: "pending_review", summary: { review_task_id: 2 } });
  const view = conclusionView(snapshot({ artifacts: [pending] }));
  assert.equal(view.primaryAction.key, "review");
  assert.equal(view.reviewTaskId, 2);
  assert.ok(view.sourceLabel.includes("等待复核"), view.sourceLabel);

  const detail = taskDetailView(snapshot({ artifacts: [pending] }));
  assert.equal(detail.artifacts[0].reviewTaskId, 2);
  assert.equal(detail.artifacts[0].statusTone, "warning");
  assert.equal(detail.needsReview, true);
});

test("老数据/缺字段有中文兜底，不出现 undefined 或 [object Object]", () => {
  const legacy = snapshot({
    task: { status: "completed", objective: null, object_label: null },
    artifacts: [{ id: 3, artifact_type: null, title: null, status: null, summary: null }],
  });
  const detail = taskDetailView(legacy);
  assert.equal(detail.title, "未命名任务");
  assert.equal(detail.objectLabel, "未指定业务对象");
  assert.equal(businessObjectLabel(""), "未指定业务对象");

  const visible = [
    detail.title,
    detail.objectLabel,
    detail.stateLabel,
    detail.updatedLabel,
    detail.conclusion.heading,
    detail.conclusion.body,
    detail.conclusion.sourceLabel,
    ...detail.artifacts.map((item) => `${item.typeLabel}${item.title}${item.statusLabel}${item.summary}`),
  ].join("|");
  assert.ok(!visible.includes("undefined"), visible);
  assert.ok(!visible.includes("null"), visible);
  assert.ok(!visible.includes("[object Object]"), visible);

  assert.deepEqual(artifactViews(null), []);
  assert.deepEqual(citationViews(undefined), []);
  assert.equal(taskTitle(""), "未命名任务");
  assert.equal(taskTitle("  "), "未命名任务");
});

test("长标题按词边界截断并显式省略，详情页保留全文", () => {
  const short = "互联网贷款协议表都有哪些主要字段？";
  assert.equal(taskTitle(short), short);

  const long = "分析 hyf_ln_pa_online_info 字段变更对下游报表以及相关报送口径的整体影响范围";
  const cut = taskTitle(long);
  assert.ok(cut.endsWith("…"), cut);
  assert.ok(cut.length <= 43, `${cut.length}`);

  const detail = taskDetailView(snapshot({ task: { objective: long } }));
  assert.equal(detail.title, long, "详情页标题必须完整显示");
});

test("列表行按状态给出唯一主操作与业务字段", () => {
  const rows = [
    row({ id: 1, status: "waiting_human", pending_action: { mine: true } }),
    row({ id: 2, status: "failed" }),
    row({ id: 3, status: "running" }),
    row({ id: 4, status: "completed", result_brief: { kind: "answer", headline: "结论如下" } }),
    row({ id: 5, status: "completed", result_brief: { kind: "none", headline: "任务已结束，暂无可展示结果。" } }),
  ];
  const byId = Object.fromEntries(rows.map((item) => [item.id, taskRowView(item)]));
  assert.equal(byId[1].action.key, "handle");
  assert.equal(byId[2].action.key, "result");
  assert.equal(byId[3].action.key, "progress");
  assert.equal(byId[4].action.key, "result");
  assert.equal(byId[5].action.key, "process");
  for (const view of Object.values(byId)) {
    assert.ok(view.title && view.stateLabel && view.objectLabel && view.updatedLabel);
    assert.ok(!INTERNAL_ENUMS.includes(view.stateLabel), view.stateLabel);
  }
  // 无结果的行必须给出可读文案，而不是空白。
  assert.ok(byId[5].summary.includes("暂无可展示结果"), byId[5].summary);
  assert.ok(byId[5].signals.includes("无结论"), JSON.stringify(byId[5].signals));
});

test("筛选与计数覆盖待我处理/进行中/已完成/需关注", () => {
  const rows = [
    row({ id: 1, status: "waiting_human", pending_action: { mine: true } }),
    row({ id: 2, status: "running" }),
    row({ id: 3, status: "completed", result_brief: { kind: "answer", headline: "结论如下" } }),
    row({ id: 4, status: "failed" }),
    row({ id: 5, status: "cancelled" }),
  ];
  const counts = taskFilterCounts(rows);
  assert.equal(counts.all, 5);
  assert.equal(counts.mine, 1);
  assert.equal(counts.active, 2);
  assert.equal(counts.done, 1);
  assert.equal(counts.issue, 1);

  assert.equal(filterTaskRows(rows, { key: "mine" }).length, 1);
  assert.equal(filterTaskRows(rows, { key: "issue" }).length, 1);
  assert.equal(filterTaskRows(null, { key: "all" }).length, 0);
  assert.ok(TASK_FILTERS.every((item) => item.label));
  // 搜索命中任务名/业务对象/结论摘要，未命中返回空。
  assert.equal(filterTaskRows(rows, { key: "all", keyword: "协议表" }).length, 5);
  assert.equal(filterTaskRows(rows, { key: "all", keyword: "不存在的关键词" }).length, 0);
});

test("产出物类型与审核状态都用中文，SQL 交付物仍有明确入口", () => {
  // SQL 变更说明是业务产出物：产出区必须用业务名称展示，而不是内部 type。
  assert.equal(artifactTypeLabel("sql_change"), "SQL 变更说明");
  assert.equal(artifactTypeLabel("knowledge_answer"), "问答结论");
  assert.equal(artifactTypeLabel("requirement_document"), "需求文档");
  assert.equal(artifactTypeLabel("unknown_type"), "产出物");
  assert.equal(artifactTypeLabel(null), "产出物");
  assert.equal(artifactTypeLabel(undefined), "产出物");
  // 审核状态在产出区用中文，未知状态有兜底。
  assert.equal(artifactStatusLabel("pending_review"), "待复核");
  assert.equal(artifactStatusLabel("confirmed"), "已确认");
  assert.equal(artifactStatusLabel("weird_status"), "状态待确认");
  // 产出物正文（SQL/草稿）可展开全文，由 artifactFullText 统一取 summary 正文。
  const [view] = artifactViews({
    artifacts: [{
      id: 9,
      artifact_type: "sql_change",
      title: "field_a 变更 SQL",
      status: "draft",
      summary: { body: "ALTER TABLE hyf_ln_pa_online_info ADD COLUMN field_a VARCHAR(64);" },
    }],
  });
  assert.equal(view.typeLabel, "SQL 变更说明");
  assert.equal(view.statusLabel, "草稿");
  assert.ok(view.fullText.includes("ALTER TABLE"), view.fullText);
});

test("引用视图保留文档版本与单元格定位，供查看原文使用", () => {
  const views = citationViews({
    artifacts: [{
      id: 1,
      summary: {
        citations: [{
          citation_id: "knowledge-unit-77",
          citation_type: "knowledge_document",
          source_type: "regulatory_qa",
          document_id: 6,
          document_version_id: 6,
          knowledge_unit_id: 77,
          label: "【知识库共享】一表通答疑汇总_[账号].xlsx",
          source_sheet_name: "一表通制度问答",
          source_cell_range: "A485:W485",
          quoted_content: "仅提供咨询服务的机构不属于互联网贷款合作机构。",
          locator: { block_id: "knowledge-unit-77", sheet_name: "一表通制度问答", cell_range: "A485:W485" },
        }],
      },
    }],
  });
  assert.equal(views.length, 1);
  assert.equal(views[0].documentId, 6);
  assert.equal(views[0].documentVersionId, 6);
  assert.equal(views[0].knowledgeUnitId, 77);
  assert.equal(views[0].locator.sheet_name, "一表通制度问答");
  assert.equal(views[0].locator.cell_range, "A485:W485");
  assert.equal(views[0].title, "【知识库共享】一表通答疑汇总_[账号].xlsx");
  assert.ok(views[0].quote.includes("仅提供咨询服务"));
  assert.equal(views[0].citation.document_version_id, 6, "原始引用对象必须原样带给抽屉");
});
