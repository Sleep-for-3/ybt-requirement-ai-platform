import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const panel = readFileSync(
  new URL("../components/requirement-workspace/RequirementTemplateExportPanel.tsx", import.meta.url),
  "utf8",
);
const backend = readFileSync(
  new URL(
    "../../backend/app/services/requirement_survey_structure_check.py",
    import.meta.url,
  ),
  "utf8",
);

test("结构自检读的是已落库产物，不能走预览或重新导出", () => {
  assert.ok(panel.includes("/render-artifacts/${item.id}/structure-check"), "必须调用 structure-check 端点");
  assert.ok(!/structure-check[\s\S]{0,200}exports/.test(panel), "结构自检不得触发导出");
  assert.ok(panel.includes('aria-label="结构自检"'), "缺少结构自检弹层");
});

test("xlsx 与 docx 都给结构自检入口，其他格式不给", () => {
  assert.ok(
    panel.includes('{item.format === "xlsx" || item.format === "docx" ? <button className="text-indigo-700 underline"'),
    "入口必须按 xlsx/docx 收窄（pdf 等没有版式契约）",
  );
  assert.ok(panel.includes('structureCheck.artifact.format === "docx"'), "弹层要按产物格式切换统计口径");
  assert.ok(panel.includes("section_titles"), "docx 统计要显示章节标题");
  assert.ok(panel.includes("field_section_count"), "docx 统计要显示字段块数量");
});

test("结论必须直说通过/未通过，并给出失败的检查项", () => {
  assert.ok(panel.includes("结构自检通过"), "缺少通过结论");
  assert.ok(panel.includes("结构自检未通过"), "缺少未通过结论");
  assert.ok(panel.includes("structureCheck.summary.blocking_failed"), "必须显示失败项计数");
  assert.ok(panel.includes("structureCheck.checks.map"), "必须逐项列出检查结果");
  assert.ok(
    !/structureCheck\.checks\.filter\(\(item\) => !item\.ok\)\.length/.test(panel),
    "失败项计数取服务端 summary，不在前端重新数一遍",
  );
});

test("必须写明只读、不重渲染、也不代表业务确认", () => {
  assert.ok(panel.includes("只读自检"), "缺少只读声明");
  assert.ok(panel.includes("不重渲染"), "必须说明不会重新渲染");
  assert.ok(panel.includes("不代表业务口径已被业务确认"), "必须说明自检不等于业务验收");
  assert.ok(panel.includes("（信息项）"), "信息项（如占位比例）要标出来，不能被当成阻断");
});

test("必须按渲染时的结构契约判定，并说明哪些项不参与阻断", () => {
  assert.ok(panel.includes('aria-label="结构契约"'), "弹层必须标出用的是哪份结构契约");
  assert.ok(panel.includes("按渲染时结构判定"), "必须说明判定口径是渲染时的结构");
  assert.ok(panel.includes("skipped_keys"), "必须展示不参与阻断判定的检查项");
  assert.ok(backend.includes("def contract_for_renderer("), "后端必须按渲染器版本选契约");
  assert.ok(
    backend.includes('_LEGACY_KEYS = ("cover", "table_meta", "groups", "header", "rows")'),
    "v7 及更早的契约只有基础五项",
  );
  assert.ok(backend.includes("generation >= 9"), "v9 起才要求来源说明");
  assert.ok(backend.includes("artifact_not_survey"), "不是调研表式必须拒绝打分，不能套别人的契约");
});

test("Word（内置版式）走 docx 契约，客户模板 Word 明确拒绝而不是套用", () => {
  const docxCheck = readFileSync(
    new URL("../../backend/app/services/requirement_docx_structure_check.py", import.meta.url),
    "utf8",
  );
  assert.ok(docxCheck.includes('DOCX_CHECK_VERSION = "docx-structure-check-v1"'), "docx 契约要有独立版本号");
  assert.ok(docxCheck.includes('BUILTIN_DOCX_RENDERER = "builtin-docx-v1"'), "只认内置版式渲染器");
  assert.ok(docxCheck.includes("artifact_not_builtin_layout"), "客户模板 Word 必须拒绝打分");
  const api = readFileSync(
    new URL("../../backend/app/api/requirements.py", import.meta.url),
    "utf8",
  );
  assert.ok(api.includes("check_docx_structure(payload"), "端点必须按格式分派到 docx 自检");
  assert.ok(panel.includes("内置版式 docx"), "前端失败文案要说明两种版式");
});
