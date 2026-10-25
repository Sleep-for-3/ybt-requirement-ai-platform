import { readFileSync } from "node:fs";

const panel = readFileSync("components/requirement-workspace/RequirementTemplateExportPanel.tsx", "utf8");
const service = readFileSync("../backend/app/services/requirement_delivery_checklist.py", "utf8");
const tests = [
  {
    name: "入口与标签：产物行提供交付检查单",
    ok: panel.includes("交付检查单") && panel.includes("aria-label={`查看交付检查单 ${item.file_name}`}") && panel.includes("openChecklist(item)"),
  },
  {
    name: "弹层：结论与四项检查表",
    ok: panel.includes('role="dialog" aria-label="交付检查单"') && panel.includes("交付检查单通过") && panel.includes("交付检查单未通过") && panel.includes("checklist.checks.map"),
  },
  {
    name: "预览截断必须显式提示且不当阻断",
    ok: panel.includes("checklist.summary.preview_truncated") && panel.includes("字段齐备性检查只覆盖可见部分"),
  },
  {
    name: "只读说明：不代表业务已确认",
    ok: panel.includes("通过只代表这份文件与冻结内容自洽，不代表业务口径已被业务确认"),
  },
  {
    name: "服务端：只读已落库字节，不重渲染",
    ok: service.includes("read_artifact_bytes") && !service.includes("render_requirement_artifact"),
  },
  {
    name: "身份检查用回查而不是重算（产物表无 config_digest）",
    ok: service.includes("find_artifact") && !service.includes("artifact.config_digest") && service.includes("产物身份可回查"),
  },
  {
    name: "清单版本常量存在",
    ok: service.includes('CHECKLIST_VERSION = "requirement-delivery-checklist-v1"'),
  },
  {
    name: "字段齐备性检查读冻结内容",
    ok: service.includes("load_frozen_draft") && service.includes("field_code"),
  },
];

let failed = 0;
for (const item of tests) {
  if (item.ok) {
    console.log(`PASS ${item.name}`);
  } else {
    failed += 1;
    console.error(`FAIL ${item.name}`);
  }
}
if (failed) {
  console.error(`${failed} 项失败`);
  process.exitCode = 1;
} else {
  console.log(`全部 ${tests.length} 项通过`);
}
