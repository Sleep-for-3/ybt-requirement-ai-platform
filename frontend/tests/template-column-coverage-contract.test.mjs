import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const lib = readFileSync(new URL("../lib/template-column-coverage.ts", import.meta.url), "utf8");
const page = readFileSync(
  new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url),
  "utf8",
);

test("模板列填充率按列给出缺口归属，不把模板缺陷算成平台缺陷", () => {
  for (const source of ["template", "mapping", "script", "requirement"]) {
    assert.ok(lib.includes(`"${source}"`), `缺少来源类型 ${source}`);
  }
  assert.ok(lib.includes("模板没给"), "缺少「模板没给」的短标签");
  assert.ok(lib.includes("集市映射缺"), "缺少集市映射缺口标签");
  assert.ok(lib.includes("fill_rate"), "必须使用服务端给的 fill_rate，而不是前端重算");
  assert.ok(!/fill_rate\s*=\s*filled\s*\//.test(page), "页面不得自己算填充率分母");
});

test("填充率只做格式化，状态判定区分填满/部分/整列为空", () => {
  assert.ok(lib.includes("column.missing <= 0"), "填满判定要看缺口数");
  assert.ok(lib.includes("column.filled <= 0"), "整列为空判定要看已填数");
  assert.ok(lib.includes("toFixed(1)"), "填充率应保留一位小数");
});

test("看板必须渲染标准模板列填充区块并展示缺口归属", () => {
  assert.ok(page.includes('aria-label="标准模板列填充"'), "缺少标准模板列填充区块");
  assert.ok(page.includes("/template-coverage"), "必须请求 /projects/{id}/template-coverage");
  assert.ok(page.includes("TEMPLATE_SOURCE_SHORT[column.source]"), "缺口归属必须来自服务端 source");
  assert.ok(page.includes("column.source_label"), "必须展示服务端给出的归属说明");
  assert.ok(page.includes("fillPercent(column)"), "填充率列必须走 fillPercent");
  assert.ok(page.includes("templateCoverageHeadline(templateCoverage)"), "必须有整表标题");
});

test("缺口清单可以按列展开，并声明截断而不是静默只给前几条", () => {
  assert.ok(page.includes('aria-label="模板列缺口清单"'), "缺少缺口清单弹层");
  assert.ok(page.includes("template-coverage/gaps/"), "必须走服务端缺口清单接口");
  assert.ok(page.includes('aria-label={`查看缺口清单 ${column.label}`}'), "列名必须是打开清单的按钮");
  assert.ok(lib.includes("export function templateGapCsv"), "缺少 CSV 导出函数");
  assert.ok(lib.includes("export function gapSummaryText"), "缺少缺口摘要文案");
  assert.ok(lib.includes("已截断"), "截断必须在文案里说明，不能只给前 N 条");
  assert.ok(page.includes("gapPanel?.truncated"), "页面必须按 truncated 提供下载全部入口");
  assert.ok(page.includes("gapPanel.source_label"), "缺口归属必须来自服务端，不在前端猜");
  assert.ok(!/column\.key === "mart_mapping"/.test(page), "禁止前端按列名硬编码归属");
});

test("CSV 导出挡住公式注入并保留 BOM 与引号转义", () => {
  assert.ok(lib.includes("ufeff"), "CSV 必须带 BOM，Excel 打开才不乱码");
  assert.ok(lib.includes("\\r\\n"), "CSV 行尾必须是 CRLF");
  assert.ok(lib.includes("/^[=+\\-@]/"), "以 = + - @ 开头的单元格必须转义，避免 CSV 注入");
  assert.ok(lib.includes('"/g'), "引号必须按 CSV 规则双写");
  assert.ok(lib.includes("item.value ??"), "当前值缺失时要写空，而不是字符串 null");
});

test("缺口清单可按监管表筛选，且不改变整列总数口径", () => {
  // 2422 条缺口里派工通常只想派某一张表；筛选只缩小返回范围。
  assert.ok(page.includes('aria-label="按监管表筛选缺口"'), "缺少按监管表筛选输入框");
  assert.ok(page.includes("openGapPanel(gapColumn, 500, gapFilter)"), "筛选必须把表编号传给服务端");
  assert.ok(page.includes("table_code=${encodeURIComponent(filter)}"), "表编号必须走 table_code 参数");
  assert.ok(page.includes("清除筛选"), "筛选后要能清除，否则用户回不到整列口径");
  assert.ok(page.includes('setGapFilter("")'), "关闭弹层必须重置筛选");
  assert.ok(lib.includes("filtered_total"), "筛选条数必须来自服务端 filtered_total");
  assert.ok(lib.includes("该列共"), "摘要必须同时给出该列总数，避免把筛出的条数当整列缺口");
  assert.ok(lib.includes("gaps.table_filter"), "摘要必须基于服务端回显的 table_filter 判断是否在筛选");
  assert.ok(!/filtered_total\s*=\s*gaps\.items/.test(lib), "筛选条数不得由前端按返回行数重算");
  // 真实事故：ILIKE %T_8_1% 把 T_8_10/11… 也筛进来，弹层却说"筛选「T_8_1」"。
  // 所以界面必须说明"默认完全匹配，前缀要写 *"，语义不能靠猜。
  assert.ok(page.includes("表编号完全匹配"), "输入框必须说明默认是完全匹配");
  assert.ok(page.includes("T_8*"), "必须告诉用户前缀要写 *");
});
