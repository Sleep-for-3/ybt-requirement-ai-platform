import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../app/templates/[templateId]/page.tsx", import.meta.url), "utf8");
const language = readFileSync(new URL("../lib/product-language.ts", import.meta.url), "utf8");

test("template detail page uses the shared parse status dictionary", () => {
  // 真实模板版本 parse_status="success"；本页曾自带小映射缺这一项，界面显示“未配置中文名称”。
  assert.match(language, /success:\s*"解析成功"/);
  assert.match(page, /import \{ parseStatusLabel \} from "@\/lib\/product-language"/);
  assert.doesNotMatch(page, /const PARSE_STATUS:Record<string,string>=/);
});

test("template detail page attributes parse findings to their sheet", () => {
  assert.match(page, /const sheetFindings=\(sheetName:string\)=>\(parseReport\?\.findings\|\|\[\]\)\.filter/);
  assert.match(page, /locator\?\.sheet===sheetName/);
  // “只看有解析提示”的筛选必须同时看 warnings_json 与 findings，否则真实模板显示“有警告 0 个”。
  assert.match(page, /const sheetHasWarning=\(sheet:ParseResult\)=>Boolean\(\(sheet\.warnings_json\|\|\[\]\)\.length\)\|\|sheetFindings\(sheet\.sheet_name\)\.length>0/);
  assert.match(page, /有解析提示/);
});

test("template detail page surfaces unrecognized columns and skipped rows", () => {
  assert.match(page, /未识别列 \{parseReport\?\.columns_unrecognized\?\.length\?\?0\} 处/, "未识别列必须按数组长度计数（接口返回的是列名列表，直接插值会渲染成空白）");
  assert.match(page, /跳过数据行 \{parseReport\?\.row_skipped_duplicate\?\?0\} 行/);
});

