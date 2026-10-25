import { readFileSync } from "node:fs";
import { strict as assert } from "node:assert";
import test from "node:test";

const panel = readFileSync(new URL("../components/requirement-workspace/RequirementTemplateExportPanel.tsx", import.meta.url), "utf8");

test("preview dialog has an in-file field finder", () => {
  assert.ok(panel.includes('aria-label="在产物里查找"'), "预览里必须有查找输入框");
  assert.ok(panel.includes("字段编码或名称"), "占位文案要告诉用户查什么");
  assert.ok(panel.includes("只在当前这份产物里查找，不跨文件、不重新渲染"), "要说清查找范围");
});

test("finder reports hit counts and explains misses", () => {
  assert.ok(panel.includes("命中 ${previewHitCount}"), "必须显示命中数量");
  assert.ok(panel.includes("已滚到第一处"), "命中后要说明已定位");
  assert.ok(panel.includes("没有找到「"), "查不到时要明确说没有，而不是静默无反应");
  assert.ok(panel.includes("也可能被预览截断"), "查不到时要点出截断这一可能原因");
});

test("matches are highlighted and scrolled to, without re-rendering", () => {
  assert.ok(panel.includes('data-preview-hit'), "命中行/章节要可识别");
  assert.ok(panel.includes("data-preview-hit=\"first\""), "要标出第一处命中用于滚动");
  assert.ok(panel.includes("scrollIntoView"), "命中后要滚到第一处");
  assert.ok(panel.includes("docxHitSections.includes(index)"), "docx 章节要按命中高亮");
  assert.ok(panel.includes("sheetHitRows.includes(rowIndex)"), "xlsx 行要按命中高亮");
  // 查找必须是纯前端过滤已下载的预览数据：不允许为搜索再请求后端
  assert.ok(!panel.includes("/preview?query="), "查找不得新增后端请求");
});

test("xlsx search covers every sheet and says where the hit is", () => {
  assert.ok(panel.includes("preview.sheets.forEach((sheet, sheetIndex)"), "必须遍历所有工作表，而不是只查当前那张");
  assert.ok(panel.includes("另外 ${otherHitSheets} 个工作表也有命中"), "多个工作表都有命中时要说明");
  assert.ok(panel.includes("setPreviewSheetIndex(sheetSearch.targetIndex)"), "命中在别的工作表时要自动切过去");
  assert.ok(panel.includes("所有工作表里都没有这段文字"), "查不到要说清是查了所有工作表");
});
