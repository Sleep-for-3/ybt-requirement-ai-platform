import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const lib = path.join(root, "lib", "requirement-worklist.ts");
const page = path.join(root, "app", "projects", "[projectId]", "readiness", "page.tsx");
const service = path.resolve(root, "..", "backend", "app", "services", "requirement_field_worklist.py");
const api = path.resolve(root, "..", "backend", "app", "api", "requirements.py");

const worklist = await import(pathToFileURL(lib).href);

const payload = {
  worklist_version: "requirement-field-worklist-v1",
  project_id: 9,
  requirement_count: 3,
  requirements_with_work: 2,
  reason_labels: {
    business_definition_missing: "缺少业务口径正文",
    mart_mapping_missing: "没有固定集市映射",
    open_gap: "仍有未关闭的字段级缺口",
    pending_candidate: "有已生成但未采纳的候选",
  },
  reason_totals: { business_definition_missing: 2, mart_mapping_missing: 1, open_gap: 3, pending_candidate: 4 },
  field_count: 5,
  returned: 5,
  truncated: false,
  items: [
    {
      requirement_id: 10,
      requirement_name: "T_8_1 监管字段需求",
      target_table_code: "T_8_1",
      target_table_name: "贷款借据",
      field_id: 2315,
      field_code: "H010001",
      field_name: "借据ID",
      reasons: ["business_definition_missing", "open_gap"],
      reason_labels: ["缺少业务口径正文", "仍有未关闭的字段级缺口"],
      open_gap_count: 3,
      pending_candidate_count: 0,
      primary_reason: "business_definition_missing",
    },
    {
      requirement_id: 11,
      requirement_name: "T_1_2 监管字段需求",
      target_table_code: "T_1_2",
      target_table_name: "机构关系",
      field_id: 487,
      field_code: "A020001",
      field_name: "机构ID",
      reasons: ["pending_candidate"],
      reason_labels: ["有已生成但未采纳的候选"],
      open_gap_count: 0,
      pending_candidate_count: 2,
      primary_reason: "pending_candidate",
    },
  ],
  note: "这份清单只是把四处已有的待办归并到字段维度。",
};

test("待办清单头条与原因计数都取服务端给的值", () => {
  const headline = worklist.worklistHeadline(payload);
  assert.match(headline, /^5 个字段还有待办（涉及 2 \/ 3 条需求）：/);
  assert.match(headline, /缺少业务口径正文 2/);
  assert.match(headline, /有已生成但未采纳的候选 4/);
  // 计数必须是服务端 reason_totals，而不是按 items 里的行数重数（items 只演示了 2 行）。
  assert.equal(worklist.worklistReasonCount(payload, "pending_candidate"), 4);
  assert.match(worklist.worklistFieldText(payload.items[0]), /^H010001 借据ID$/);
});

test("按原因筛选只过滤、不改计数", () => {
  const onlyGaps = worklist.filterWorklist(payload.items, "open_gap");
  assert.equal(onlyGaps.length, 1);
  assert.equal(onlyGaps[0].field_id, 2315);
  assert.equal(worklist.filterWorklist(payload.items, "all").length, 2);
  const onlyPending = worklist.filterWorklist(payload.items, "pending_candidate");
  assert.equal(onlyPending.length, 1);
  assert.equal(onlyPending[0].field_id, 487);
});

test("CSV 带 BOM、CRLF、全字段引号，并对公式前缀做防注入", () => {
  const csv = worklist.worklistCsv(payload, [
    payload.items[0],
    { ...payload.items[1], field_name: "=HYPERLINK(\"x\")" },
  ]);
  assert.ok(csv.startsWith("\ufeff"), "必须带 UTF-8 BOM，否则 Excel 会把中文显示成乱码");
  assert.ok(csv.includes("\r\n"), "必须用 CRLF，否则 Excel 会把多行当成一行");
  assert.ok(csv.includes('"T_8_1","贷款借据","T_8_1 监管字段需求","H010001","借据ID"'));
  assert.ok(csv.includes('"缺少业务口径正文；仍有未关闭的字段级缺口"'), "多个待办事项应并列写在同一格");
  assert.ok(csv.includes("\"'=HYPERLINK"), "= 开头的单元格要前置单引号，避免被 Excel 当公式执行");
});

test("页面只做展示与筛选：入口、弹层、CSV、计数来源都受约束", () => {
  const source = readFileSync(page, "utf8");
  assert.match(source, /aria-label="打开待办派工清单"/);
  assert.match(source, /\/projects\/\$\{projectId\}\/requirements-worklist\?limit=3000/);
  assert.match(source, /aria-label="待办派工清单" role="dialog"/);
  assert.match(source, /worklistHeadline\(worklist\)/);
  assert.match(source, /worklistReasonCount\(worklist, reason\)/);
  assert.match(source, /filterWorklist\(worklist\.items, worklistFilter\)/);
  assert.match(source, /worklistCsv\(worklist, items\)/);
  // 不能在前端按行重数：那样看板与导出会出现两套数字。
  assert.doesNotMatch(source, /reason_totals\[[^\]]+\]\s*=\s*[^=]/);
  assert.doesNotMatch(source, /items\.filter\([^)]*\)\.length\s*\}\s*条?待办/);
});

test("每一行都能直接落到工作台的那个字段（缺 id 时不给错链接）", () => {
  const linked = worklist.worklistFieldHref(9, {
    ...payload.items[0],
    target_table_id: 101,
    scenario_id: 2,
  });
  assert.ok(linked, "带齐 tableId/scenarioId/fieldId 时必须给链接");
  const parsed = new URL(linked, "http://localhost:3010");
  assert.equal(parsed.pathname, "/workspace");
  assert.equal(parsed.searchParams.get("projectId"), "9");
  // 同表可能有多条需求：只带 requirementId 会打开另一条需求的同名字段。
  assert.equal(parsed.searchParams.get("tableId"), "101");
  assert.equal(parsed.searchParams.get("scenarioId"), "2");
  assert.equal(parsed.searchParams.get("requirementId"), "10");
  assert.equal(parsed.searchParams.get("fieldId"), "2315");
  assert.equal(worklist.worklistFieldHref(9, payload.items[0]), null, "缺 table/scenario id 时不能拼链接");
  const source = readFileSync(page, "utf8");
  assert.match(source, /worklistFieldHref\(projectId, item\)/, "页面必须用同一函数拼深链");
  assert.match(source, /aria-label=\{`去工作台处理 \$\{worklistFieldText\(item\)\}`\}/);
  assert.match(source, /无法定位/, "缺 id 时显示无法定位，而不是给一个会打开错需求的链接");
});

test("服务端只读聚合，不冻结、不生成、不关缺口", () => {
  const code = readFileSync(service, "utf8");
  assert.match(code, /WORKLIST_VERSION = "requirement-field-worklist-v3"/);
  assert.match(code, /"field_count": len\(items\)/);
  assert.match(code, /"truncated": len\(returned\) < len\(items\)/);
  for (const forbidden of ["db.add(", "db.commit(", "freeze_draft", "create_script_requirements", "status\"\] = \"resolved"]) {
    assert.ok(!code.includes(forbidden), `服务端不应出现 ${forbidden}`);
  }
  const endpoint = readFileSync(api, "utf8");
  assert.match(endpoint, /@router\.get\("\/projects\/\{project_id\}\/requirements-worklist"\)/);
  assert.match(endpoint, /build_field_worklist\(db, project_id, limit=limit\)/);
});

test("处置与缺口矛盾必须在清单里可见", async () => {
  const libText = readFileSync(lib, "utf8");
  const pageText = readFileSync(page, "utf8");

  assert.match(libText, /export function gapConsistencyText/);
  assert.match(libText, /done_with_gaps: "badge-danger"/, "矛盾状态必须用危险色");
  assert.match(libText, /登记"已处置"不会关闭缺口/, "口径必须写在 lib 注释里");
  assert.match(pageText, /GAP_CONSISTENCY_BADGE\[item\.gap_consistency\?\.state/, "行内徽标要取服务端状态");
  assert.match(pageText, /处置与缺口：处置中/, "弹层头条要给出四态计数");
  assert.match(pageText, /已处置但缺口未清/, "计数文案必须点名矛盾");
  assert.doesNotMatch(pageText, /gap_consistency\.state\s*=\s*item\.open_gap_count/, "不能让前端自己推断状态");
});
