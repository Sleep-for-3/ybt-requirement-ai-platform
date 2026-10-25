import { readFileSync } from "node:fs";
import { strict as assert } from "node:assert";
import test from "node:test";

const panel = readFileSync(new URL("../components/requirement-workspace/RequirementTemplateExportPanel.tsx", import.meta.url), "utf8");
const service = readFileSync(new URL("../../backend/app/services/requirement_artifact_preview.py", import.meta.url), "utf8");

test("export panel offers in-page preview for xlsx and docx artifacts", () => {
  assert.ok(panel.includes("在页面预览"), "必须提供页面内预览入口");
  assert.ok(
    panel.includes('item.format === "xlsx" || item.format === "docx"'),
    "xlsx 与 docx 都要能进页面预览，其余格式仍不放行",
  );
  assert.ok(panel.includes("/render-artifacts/${item.id}/preview"), "必须调用产物预览端点");
});

test("docx preview renders sections instead of forcing a download", () => {
  assert.ok(panel.includes('preview.format === "docx"'), "docx 必须走章节视图");
  assert.ok(panel.includes("preview.sections"), "必须渲染章节列表");
  assert.ok(panel.includes("section.paragraphs"), "必须渲染段落");
  assert.ok(panel.includes("section.tables"), "必须渲染表格摘要");
  assert.ok(panel.includes("Word 结构："), "必须说明这是 Word 结构视图");
  assert.ok(panel.includes("处内容被截断"), "截断必须显式说明，不能静默省略");
});

test("preview dialog states truncation and non-cached formulas instead of hiding them", () => {
  assert.ok(panel.includes('aria-label="产物预览"'), "预览必须是可识别的对话框");
  assert.ok(panel.includes("仅显示前"), "必须显式说明截断");
  assert.ok(panel.includes("个公式没有缓存值，显示为公式原文"), "未缓存公式不能显示成空白");
  assert.ok(panel.includes("下载原文件"), "预览里必须能取到同一份原文件");
});

test("preview reads stored bytes and never re-renders", () => {
  assert.ok(service.includes("load_workbook"), "xlsx 预览只解析产物字节");
  assert.ok(service.includes("Document("), "docx 预览只解析产物字节");
  assert.ok(!service.includes("export_"), "预览服务不得调用导出/渲染函数");
  assert.ok(!service.includes("render_requirement_artifact"), "预览不得回落到渲染器");
  assert.ok(service.includes("artifact-preview-v1"), "预览协议要带版本");
  assert.ok(service.includes("artifact-docx-preview-v1"), "docx 预览协议也要带版本");
  assert.ok(service.includes('"只有 xlsx 与 docx 产物支持页面预览'), "其余格式必须明确拒绝");
});
