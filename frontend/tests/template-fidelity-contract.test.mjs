import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const panelPath = new URL("../components/requirement-workspace/RequirementTemplateExportPanel.tsx", import.meta.url);
const servicePath = new URL("../../backend/app/services/requirement_survey_fidelity.py", import.meta.url);
const apiPath = new URL("../../backend/app/api/requirements.py", import.meta.url);

test("面板：模板一致性只对 xlsx 开放且结论来自服务端", async () => {
  const panel = await readFile(panelPath, "utf8");
  assert.match(panel, /item\.format === "xlsx" \? <button className="text-teal-700 underline" disabled=\{busy \|\| fidelityBusy\}/);
  assert.match(panel, /aria-label=\{`查看模板一致性 \$\{item\.file_name\}`\}/);
  assert.match(panel, /apiGet<FidelityPayload>\(`\$\{base\}\/render-artifacts\/\$\{item\.id\}\/template-fidelity`\)/);
  // 结论必须用服务端 verdict / failed_labels，不在前端猜。
  assert.match(panel, /fidelity\.verdict === "pass" \? "与标准模板一致"/);
  assert.match(panel, /fidelity\.failed_labels\.join\("、"\)/);
});

test("面板：比对明细要区分「不一致」「文档为空」「模板未给值」", async () => {
  const panel = await readFile(panelPath, "utf8");
  assert.match(panel, /role="dialog" aria-label="模板一致性"/);
  for (const label of ["模板列", "可比字段", "一致", "不一致", "文档为空", "模板未给值"]) {
    assert.ok(panel.includes(`>${label}<`), `缺少列 ${label}`);
  }
  assert.match(panel, /模板未给值但文档写了内容（需求侧补充，非模板事实）/);
  assert.match(panel, /比对只读：不修改文件、不修改需求/);
  // 计数不得由前端重算。
  assert.doesNotMatch(panel, /fidelity\.columns\.filter\(\(column\) => column\.matched_count\)\.length/);
});

test("服务端：比对按需求的目标表取模板值，不是只按字段代码", async () => {
  const service = await readFile(servicePath, "utf8");
  const api = await readFile(apiPath, "utf8");
  assert.match(service, /FIDELITY_VERSION = "requirement-template-fidelity-v1"/);
  // SFJJGDM 这类系统字段在每张表里都有同名行：必须按需求的目标表限定。
  assert.match(service, /TargetField\.target_table_id == target_table_id/);
  assert.match(service, /requirement\.scope_json or \{\}\)\.get\("target_table_id"\)/);
  // 模板没给值不能判不一致。
  assert.match(service, /模板本身没有值：不能判"不一致"/);
  // 只读：不写库。
  assert.doesNotMatch(service, /db\.add\(/);
  assert.doesNotMatch(service, /db\.commit\(/);
  assert.match(api, /@router\.get\("\/projects\/\{project_id\}\/requirements\/\{requirement_id\}\/render-artifacts\/\{artifact_id\}\/template-fidelity"\)/);
});
