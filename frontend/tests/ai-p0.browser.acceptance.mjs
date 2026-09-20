import assert from "node:assert/strict";
import {createServer} from "node:http";
import {mkdir, writeFile} from "node:fs/promises";
import path from "node:path";
import {fileURLToPath} from "node:url";
import next from "next";
import {chromium} from "playwright";

const frontendDir = fileURLToPath(new URL("..", import.meta.url));
const distDir = process.env.NEXT_DIST_DIR || ".next-ai-p0-acceptance";
const outputDir = path.resolve(process.env.AI_P0_ACCEPTANCE_OUTPUT || path.join(frontendDir, "..", "docs", "ux", "acceptance", "ai-p0-browser-20260920"));
const apiTransport = process.env.AI_P0_API_TRANSPORT || "mock";
const projectId = Number(process.env.AI_P0_PROJECT_ID || (apiTransport === "real" ? 1 : 7));

const project = {id: projectId, name: "P0 浏览器隔离项目", bank_name: "P0 隔离银行", institution_id: 1, project_status: "active"};
const authMe = {
  id: 1,
  username: "p0-browser",
  display_name: "P0 浏览器验收员",
  email: "p0-browser@example.invalid",
  status: "active",
  institution_memberships: [{institution_id: 1, role: "institution_admin", status: "active"}],
  project_memberships: [{project_id: projectId, project_role: "project_manager", status: "active"}],
  effective_permissions: ["knowledge.manage", "lineage.view", "lineage.review", "technical.edit"],
  effective_project_permissions: {[String(projectId)]: ["knowledge.manage", "lineage.view", "lineage.review", "technical.edit"]},
  capabilities: {can_view_admin: true, can_view_institution_cockpit: true, can_view_permission_matrix: true, can_manage_users: true, can_view_all_projects: true},
};

const graph = {
  project_id: projectId,
  tables: [
    {id: "table:1", name: "来源客户表", technical_name: "ods.customer", layer: "贴源层", fields: ["field:1"], classification: null, physical_assignments: []},
    {id: "table:2", name: "监管报送表", technical_name: "mart.ybt_target", layer: "监管目标", fields: ["field:2"], classification: null, physical_assignments: []},
  ],
  nodes: [
    {id: "field:1", table_key: "table:1", entity_type: "catalog_field", canonical_entity_id: 1, unresolved_flag: false, display: {business_name: "客户名称", technical_name: "customer_name"}},
    {id: "field:2", table_key: "table:2", entity_type: "target_field", canonical_entity_id: 2, unresolved_flag: false, display: {business_name: "客户名称报送项", technical_name: "customer_name"}},
  ],
  edges: [{
    id: "1",
    source_node_id: "field:1",
    target_node_id: "field:2",
    edge_type: "insert",
    relation_source: "script",
    transformation_expression: "TRIM(customer_name)",
    join_condition: "customer.id = account.customer_id",
    filter_condition: "customer.status = 'A'",
    code_mapping_rule: "status A -> 正常",
    aggregation_rule: "MAX(update_time)",
    evidence_refs: [{type: "script", source_name: "batch.sql", version_no: 3, quoted_content: "INSERT INTO mart.ybt_target ..."}],
    rules: {has_join: true, has_filter: true, has_code_mapping: true},
  }],
  root_ids: ["field:2"],
  revision_id: 101,
  truncated: false,
  omitted_frontier_count: 0,
  facts_mode: "frozen",
  limits: {max_nodes: 100, depth: 4},
  warnings: [],
};

const promptVersions = [{
  id: 1,
  prompt_key: "lineage_edge_explanation",
  version_no: 2,
  system_prompt: "仅依据固定脚本事实和制度证据解释。",
  user_prompt_template: "证据：{evidence}",
  enabled: true,
  created_by: "p0-browser",
  created_at: "2026-09-20T08:00:00Z",
  runtime_binding: {editable: false, activation: "latest_enabled", system_prompt: "仅依据固定脚本事实和制度证据解释。", user_prompt_template: "证据：{evidence}", note: "用户模板尚未参与通用运行时渲染。"},
}];

const evaluationCases = [{
  id: 9,
  case_name: "反馈回归：血缘解释",
  case_type: "feedback_regression",
  query_text: "解释客户名称来源",
  expected_source_system: "核心系统",
  expected_table_name: "ods.customer",
  expected_field_name: "customer_name",
  expected_answer_keywords_json: ["来源", "规则"],
  enabled: true,
}];

let feedbackConverted = false;
const feedback = [{
  id: 21,
  feedback_type: "correction",
  target_type: "lineage_edge",
  target_id: 1,
  rating: "negative",
  comment: "来源说明需要补充过滤条件",
  execution_kind: "mock_model",
  output_hash: "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
}];

let explanationAttempts = 0;
const explanationSuccess = {
  edge_id: "1",
  revision_id: 101,
  status: "ready",
  facts: [{id: "fact:1", kind: "expression", label: "加工表达式", value: "TRIM(customer_name)"}],
  deterministic: {summary: "客户名称来自核心系统客户表，经过空值清理后写入监管报送表。", steps: ["读取核心系统客户名称", "清理首尾空格", "写入监管报送客户名称"], relation_label: "插入"},
  ai: {
    business_summary: "该报送字段以核心系统客户名称为权威来源，空值清理不改业务含义。",
    plain_language_steps: [{text: "来源字段来自核心系统客户表。", fact_ids: ["fact:1"]}],
    regulatory_interpretation: "本次事实没有绑定具体监管条款，不能把脚本现状升级为监管要求。",
    regulatory_status: "missing_basis",
    regulatory_evidence_ids: [],
    risks: [{text: "尚未确认客户名称的正式业务口径。", fact_ids: ["fact:1"]}],
    open_questions: ["客户名称是否需要保留历史名称？"],
    confidence_level: "high",
    unsupported_claim_count: 0,
  },
  regulatory_evidence: [],
  model: {provider: "mock", model: "mock-lineage", prompt_key: "lineage_edge_explanation", prompt_version: 2},
  execution_metadata: {execution_kind: "mock_model", provider: "mock", model_name: "mock-lineage", prompt_version: 2, context_complete: false, degraded_reason: null},
  message: "",
  disclaimer: "模型解释是候选建议，以人工确认结果为准。",
};

function responseHeaders() {
  return {
    "content-type": "application/json; charset=utf-8",
    "access-control-allow-origin": "*",
    "access-control-allow-headers": "*",
    "access-control-allow-methods": "GET,POST,PATCH,PUT,DELETE,OPTIONS",
  };
}

async function reply(route, body, status = 200) {
  await route.fulfill({status, headers: responseHeaders(), body: JSON.stringify(body)});
}

const nextApp = next({dev: false, dir: frontendDir, conf: {distDir}});
const handler = nextApp.getRequestHandler();
await nextApp.prepare();
const frontendServer = createServer((request, response) => handler(request, response));
await new Promise((resolve, reject) => {
  frontendServer.once("error", reject);
  frontendServer.listen(0, "127.0.0.1", resolve);
});
const frontendPort = frontendServer.address().port;
const origin = `http://127.0.0.1:${frontendPort}`;
await mkdir(outputDir, {recursive: true});

const browser = await chromium.launch({headless: true, channel: "msedge"}).catch(() => chromium.launch({headless: true}));
const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
await context.addInitScript(() => {
  window.sessionStorage.setItem("ybt:access-token", "isolated-browser-token");
  window.sessionStorage.setItem("ybt:refresh-token", "isolated-browser-refresh-token");
});

if (apiTransport !== "real") await context.route("**/api/**", async (route) => {
  const request = route.request();
  const url = new URL(request.url());
  const method = request.method();
  const pathname = url.pathname;
  if (method === "OPTIONS") return reply(route, {});
  if (method === "GET" && pathname === "/api/auth/me") return reply(route, authMe);
  if (method === "GET" && pathname === "/api/projects") return reply(route, [project]);
  if (method === "GET" && pathname === `/api/projects/${projectId}/jobs/summary`) return reply(route, {active_count: 0, failed_count: 0, completed_count: 0, total_count: 0});
  if (method === "GET" && pathname === "/api/prompt-versions") return reply(route, promptVersions);
  if (method === "GET" && pathname === `/api/projects/${projectId}/evaluations/cases`) return reply(route, feedbackConverted ? [...evaluationCases, {...evaluationCases[0], id: 10, case_name: "反馈回归：客户名称来源"}] : evaluationCases);
  if (method === "GET" && pathname === `/api/projects/${projectId}/feedback`) return reply(route, feedbackConverted ? [] : feedback);
  if (method === "POST" && pathname === `/api/projects/${projectId}/feedback/21/evaluation-case`) {
    feedbackConverted = true;
    return reply(route, {id: 10, case_type: "feedback_regression"});
  }
  if (method === "GET" && pathname === `/api/projects/${projectId}/lineage/assets`) {
    return reply(route, {items: [{kind: "catalog", id: 1, name: "来源客户表", technical_name: "ods.customer"}], truncated: false});
  }
  if (method === "GET" && pathname === `/api/projects/${projectId}/lineage/revisions`) {
    return reply(route, [{id: 101, revision_no: 3, status: "published", node_count: 2, edge_count: 1, published_at: "2026-09-20T08:00:00Z"}]);
  }
  if (method === "GET" && pathname === `/api/projects/${projectId}/lineage/table-graph`) return reply(route, graph);
  if (method === "POST" && pathname === `/api/projects/${projectId}/lineage/edge-explanations`) {
    explanationAttempts += 1;
    if (explanationAttempts === 1) {
      return reply(route, {
        detail: {
          code: "generation-blocked",
          reasons: ["上下文超过冻结预算"],
          context_budget: {unit: "characters", used: 920, limit: 800},
          context_gaps: ["缺少上游字段列表", "未解析目标字段顺序"],
        },
      }, 409);
    }
    return reply(route, explanationSuccess);
  }
  return reply(route, {detail: `未配置的隔离验收接口：${method} ${pathname}`}, 404);
});

const page = await context.newPage();
const pageErrors = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
const result = {
  actualFrontend: true,
  apiTransport,
  realModel: false,
  executedAt: new Date().toISOString(),
  checks: {},
  screenshots: {},
  pageErrors,
};

try {
  await page.goto(`${origin}/prompt-versions?projectId=${projectId}`, {waitUntil: "networkidle"});
  await page.getByText("当前页面不支持编辑、测试、发布或回滚。", {exact: true}).waitFor();
  await page.getByText("User prompt template · 只读，尚未渲染", {exact: true}).waitFor();
  assert.equal(await page.getByRole("button", {name: /编辑|发布|回滚|测试/}).count(), 0);
  result.checks.promptReadOnly = true;
  result.screenshots.promptReadOnly = path.join(outputDir, "prompt-readonly.png");
  await page.screenshot({path: result.screenshots.promptReadOnly, fullPage: true});

  await page.goto(`${origin}/lineage/nebula?projectId=${projectId}`, {waitUntil: "networkidle"});
  await page.locator("aside button").filter({hasText: /来源|客户|监管|报送/}).first().click();
  const graphEdge = page.locator(".react-flow__edge").first();
  await graphEdge.waitFor({state: "attached"});
  await graphEdge.dispatchEvent("click");
  if (apiTransport === "mock") {
    await page.getByText("生成已阻断：上下文超过冻结预算", {exact: false}).waitFor();
    await page.getByText(/920 \/ 800 characters/).waitFor();
    await page.getByText(/缺少上游字段列表/).waitFor();
    result.checks.structuredContextBlockVisible = true;
    result.screenshots.contextBlocked = path.join(outputDir, "context-blocked.png");
    await page.screenshot({path: result.screenshots.contextBlocked, fullPage: true});
    await page.getByRole("button", {name: /重试/}).click();
  }
  const explanationPanel = page.locator('aside[aria-label="血缘关系业务解释"]').filter({visible: true}).last();
  await explanationPanel.getByText("Mock 流程", {exact: true}).waitFor();
  result.executionLabel = "Mock 流程";
  await page.getByText("候选 · 未人工确认", {exact: true}).waitFor();
  await page.getByText("缺少制度依据", {exact: true}).waitFor();
  result.checks.missingPolicyBasisVisible = true;
  if (apiTransport === "mock") {
    assert.equal(explanationAttempts, 2);
    await page.getByText("上下文被截断，结论不完整", {exact: false}).waitFor();
    result.checks.contextTruncationVisible = true;
  } else {
    await page.getByText(/上下文完整|上下文被截断，结论不完整/).waitFor();
  }
  result.checks.contextCompletenessVisible = true;
  result.checks.executionLabelVisible = true;
  result.checks.mockLabelVisible = true;
  result.screenshots.lineageExplanation = path.join(outputDir, "lineage-explanation.png");
  await page.screenshot({path: result.screenshots.lineageExplanation, fullPage: true});

  await page.goto(`${origin}/evaluations?projectId=${projectId}`, {waitUntil: "networkidle"});
  await page.getByText("反馈回归队列", {exact: true}).waitFor();
  await page.getByText(/来源说明需要补充过滤条件/).first().waitFor();
  await page.getByText(/mock_model/).first().waitFor();
  await page.getByRole("button", {name: "转为评测样例"}).click();
  await page.getByText("反馈已转为回归样例", {exact: true}).waitFor();
  if (apiTransport === "mock") assert.equal(feedbackConverted, true);
  result.checks.feedbackToRegressionVisible = true;
  result.screenshots.feedbackRegression = path.join(outputDir, "feedback-regression.png");
  await page.screenshot({path: result.screenshots.feedbackRegression, fullPage: true});

  assert.deepEqual(pageErrors, []);
  result.passed = true;
  await writeFile(path.join(outputDir, "results.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  result.passed = false;
  result.error = error instanceof Error ? error.message : String(error);
  await writeFile(path.join(outputDir, "results.json"), JSON.stringify(result, null, 2));
  console.error(error);
  process.exitCode = 1;
} finally {
  await context.close();
  await browser.close();
  frontendServer.closeAllConnections?.();
  await Promise.race([new Promise((resolve) => frontendServer.close(resolve)), new Promise((resolve) => setTimeout(resolve, 2000))]);
  await Promise.race([nextApp.close().catch(() => {}), new Promise((resolve) => setTimeout(resolve, 2000))]);
}
process.exit(result.passed ? 0 : 1);
