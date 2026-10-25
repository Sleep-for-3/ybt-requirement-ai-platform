import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";

const cwd = process.cwd();
const lib = readFileSync(path.join(cwd, "lib", "table-coverage.ts"), "utf8");
const page = readFileSync(path.join(cwd, "app", "projects", "[projectId]", "readiness", "page.tsx"), "utf8");

test("覆盖度必须把需求维与脚本维分开：脚本未解析出写入 != 需求没做", () => {
  assert.match(lib, /脚本存在但未解析出写入/);
  assert.match(lib, /缺少跑批脚本/);
  assert.match(page, /不等于"需求没做"/);
  assert.match(page, /需要人工确认是否已停用/);
  // 状态只能来自服务端字段，不能按需求条数猜。
  assert.doesNotMatch(page, /state\s*=\s*item\.requirement_count/);
  assert.match(page, /COVERAGE_LABELS\[item\.state\]/);
});

test("汇总头条要给出五类计数，筛选条与计数同源", () => {
  assert.match(lib, /已冻结 \$\{summary\.frozen\} 张/);
  assert.match(lib, /有需求未冻结 \$\{summary\.covered_draft\} 张/);
  assert.match(lib, /脚本可建需未建需 \$\{summary\.script_ready\} 张/);
  assert.match(lib, /脚本存在但未解析出写入 \$\{summary\.script_disabled\} 张/);
  assert.match(lib, /缺少跑批脚本 \$\{summary\.script_absent\} 张/);
  assert.match(lib, /return summary\[key\] \?\? 0;/);
  assert.match(page, /coverageFilterCount\(coverage\.summary, filter\.key\)/);
});

test("筛选后为空要解释，而不是给一张空表", () => {
  assert.match(page, /当前条件下没有监管表/);
  assert.match(page, /全部监管表/);
  assert.match(page, /当前显示/);
  assert.match(page, /再显示 30 张/);
});

test("页面必须走服务端聚合接口并渲染明细", () => {
  assert.match(page, /\/projects\/\$\{projectId\}\/table-coverage/);
  assert.match(page, /aria-label="监管表覆盖度"/);
  assert.match(page, /coverageDetail\(item\)/);
  assert.match(page, /filterCoverage\(coverage\.items, coverageFilter\)/);
  assert.match(page, /该区块不影响上方内容/);
});

test("原因必须来自服务端，不能在前端猜", () => {
  assert.match(lib, /script_reason_kind\?: string \| null;/);
  assert.match(lib, /script_reason\?: string \| null;/);
  assert.match(page, /\{item\.script_reason \? \(/);
  // 不能按"有没有需求"或"脚本版本数"在前端编造原因。
  assert.doesNotMatch(page, /script_reason\s*=/);
});
