import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = path => readFile(new URL(path, import.meta.url), "utf8");

test("resources workbench renders real governance summary with permission filtering", async()=>{
  const source=await read("../app/resources/page.tsx");
  assert.match(source,/resources\/governance-summary/);
  assert.match(source,/canViewNavigationAudience/);
  for(const label of ["资料治理","数据资产","最近变更","待处理事项","暂无数据"])assert.ok(source.includes(label));
  assert.doesNotMatch(source,/Math\.random|mockCount|记录数量:\s*\d/);
});

test("template list and detail preserve governed version journey", async()=>{
  const [list,detail]=await Promise.all([read("../app/templates/page.tsx"),read("../app/templates/[templateId]/page.tsx")]);
  assert.match(list,/href={`\/templates\/\$\{item\.id\}\?returnTo=/);
  for(const label of ["稳定模板代码","监管版本 / 发布批次","上传草稿并解析"])assert.ok(list.includes(label));
  for(const label of ["内部版本","监管版本","版本差异","原始文件和解析结果","应用记录和影响范围","人工审核通过","激活生效"])assert.ok(detail.includes(label));
});

test("knowledge UI exposes authority lifecycle, existing logical document, trust and index state", async()=>{
  const [list,detail,ask]=await Promise.all([read("../app/knowledge/documents/page.tsx"),read("../app/knowledge/documents/[documentId]/page.tsx"),read("../app/knowledge/ask/page.tsx")]);
  for(const label of ["来源类别","为“","监管文号","内部修订版本","上传草稿并解析"])assert.ok(list.includes(label));
  for(const label of ["仍在使用内部版本","监管版本","内部修订","变更说明","审核通过","激活生效"])assert.ok(detail.includes(label));
  for(const label of ["可信性说明","正式索引覆盖状态","关键词降级检索","资料冲突，不能静默合并","查询历史口径"])assert.ok(ask.includes(label));
});
