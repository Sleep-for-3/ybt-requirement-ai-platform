import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import test from "node:test";

const page = fileURLToPath(new URL("../app/resources/reverse-requirements/page.tsx", import.meta.url));

const source = readFileSync(page, "utf8");

test("reverse requirements page explains a missing write target instead of staying silent", () => {
  assert.match(source, /preview\.targets\.length===0/, "页面必须在没有写入目标时给出显式提示");
  assert.match(source, /没有解析出写入目标/, "提示必须说明“没有解析出写入目标”");
  assert.match(source, /脚本被整段注释屏蔽/, "提示必须列出脚本被注释屏蔽这一真实原因");
  assert.match(source, /reparse_drift_report\.py/, "提示必须指向解析器落后检查脚本");
  assert.match(source, /不会为没有写入目标的脚本编造需求/, "提示必须说明平台不会编造需求");
});

test("reverse requirements page opens the gap list when there is nothing to confirm", () => {
  assert.match(source, /<details open=\{preview\.targets\.length===0\}/, "没有写入目标时待核验事项应默认展开");
});

test("create button cannot be enabled without a confirmed target binding", () => {
  assert.match(
    source,
    /disabled=\{!confirmed\|\|!scenario\|\|!Object\.keys\(choices\)\.length\|\|Object\.values\(choices\)\.some\(c=>!c\.name\.trim\(\)\|\|!Object\.keys\(c\.bindings\)\.length\)\}/,
    "建需按钮必须要求已勾选确认、已选场景、有目标且每个目标都有字段绑定",
  );
});
