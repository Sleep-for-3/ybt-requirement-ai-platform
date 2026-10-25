import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const libPath = new URL("../lib/script-basis-freshness.ts", import.meta.url);
const pagePath = new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url);

async function read(path) {
  return readFile(path, "utf8");
}

test("新鲜的脚本依据有四种状态标签，且没有依据时不说成最新", async () => {
  const lib = await read(libPath);
  assert.match(lib, /aligned: "依据最新"/);
  assert.match(lib, /script_updated: "脚本有更新"/);
  assert.match(lib, /parse_changed: "脚本解析状态变化"/);
  assert.match(lib, /version_missing: "依据版本已不存在"/);
  assert.match(lib, /不适用（没有冻结脚本依据）/);
});

test("版本明细必须给出冻结版本与最新版本，而不是只说落后", async () => {
  const lib = await read(libPath);
  assert.match(lib, /冻结 \$\{frozen\} → 最新 \$\{latest\}/);
  assert.match(lib, /已不在脚本版本列表里/);
  assert.match(lib, /FRESHNESS_NOTE/);
  assert.match(lib, /脚本升级不会自动改写已冻结依据/);
});

test("看板必须有脚本依据列与明细弹层，判据来自服务端", async () => {
  const page = await read(pagePath);
  assert.match(page, /<th className="py-1 pr-3 font-medium">脚本依据<\/th>/);
  assert.match(page, /aria-label=\{`查看脚本依据 \$\{item\.target_table_code \|\| item\.name\}`\}/);
  assert.match(page, /aria-label="脚本依据"/);
  assert.match(page, /freshnessStateOf\(itemFreshness\)/);
  assert.match(page, /freshnessVersionText\(version\)/);
  assert.match(page, /FRESHNESS_NOTE/);
  assert.match(page, /\/script-basis-freshness/);
});

test("前端不得自己按版本号数量推断依据是否落后", () => {
  return read(pagePath).then((page) => {
    assert.doesNotMatch(page, /frozen_version_no\s*[<>]=?\s*latest_version_no/);
    assert.doesNotMatch(page, /const\s+freshness\s*=\s*\{/);
  });
});
