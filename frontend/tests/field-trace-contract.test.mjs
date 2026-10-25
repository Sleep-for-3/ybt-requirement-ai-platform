import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const summary = readFileSync("components/requirement-workspace/FieldTraceSummary.tsx", "utf8");
const selectedEditor = readFileSync("components/requirement-workspace/SelectedFieldEditor.tsx", "utf8");
const contentEditor = readFileSync("components/requirement-workspace/RequirementContentEditor.tsx", "utf8");

test("字段溯源面板展示集市映射条数与逐条来源", () => {
  assert.match(summary, /aria-label="字段溯源与解析事实"/);
  assert.match(summary, /集市映射 \{mappings\.length\} 条/);
  assert.match(summary, /mapping\.mart_table_summary \|\| "未登记集市表"/);
  assert.match(summary, /mapping\.mart_field_summary \|\| "未登记集市字段"/);
});

test("无集市映射时明确说明导出溯源列组会留空，而不是显示空白", () => {
  assert.match(summary, /该字段没有固定的集市映射：导出文档的溯源列组会留空/);
});

test("多集市映射提示不得默认取第一条", () => {
  assert.match(summary, /同一监管字段来自 \{mappings\.length\} 个集市字段/);
  assert.match(summary, /不能默认取第一条/);
});

test("已确认脚本规则与来源节点来自 confirmedPath，而不是自己编造数字", () => {
  assert.match(summary, /record\.confirmedPath\?\.rule_ids\?\.length/);
  assert.match(summary, /record\.confirmedPath\?\.nodes\?\.length/);
});

test("共享事实编辑器与需求专属内容编辑器都必须渲染该面板", () => {
  for (const [name, source] of [["SelectedFieldEditor", selectedEditor], ["RequirementContentEditor", contentEditor]]) {
    assert.match(source, /import \{ FieldTraceSummary \}/, `${name} 必须引用共享溯源面板`);
    assert.match(source, /<FieldTraceSummary record=\{record\} \/>/, `${name} 必须渲染共享溯源面板`);
  }
  assert.doesNotMatch(selectedEditor, /function TraceSummary\(/, "不应再保留重复实现");
});
