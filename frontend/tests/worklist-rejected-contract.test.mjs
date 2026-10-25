import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "..");
const repoRoot = path.resolve(frontend, "..");

const pagePath = path.join(frontend, "app", "projects", "[projectId]", "readiness", "page.tsx");
const libPath = path.join(frontend, "lib", "requirement-worklist.ts");
const servicePath = path.join(repoRoot, "backend", "app", "services", "requirement_field_worklist.py");

test("被否产物是独立的一类待办，不是折进缺口计数", async () => {
  const lib = await readFile(libPath, "utf8");

  assert.match(lib, /"artifact_rejected"/, "原因枚举必须有 artifact_rejected");
  assert.match(lib, /WORKLIST_REASON_ORDER[\s\S]{0,200}artifact_rejected/, "筛选顺序里要能看到它");
  assert.match(lib, /artifact_rejected: "先按登记依据改正文/, "必须给出下一步动作");
  // 被否是"整份文档"的事，字段行上要能说清是哪一份产物哪一条依据。
  assert.match(lib, /export type WorklistRejectedArtifact/, "需要单独的类型描述被否产物");
  assert.match(lib, /basis: string/, "依据原文必须透传到前端");
  assert.match(lib, /rejected_requirement_count\?: number/, "计数取服务端");
});

test("被否产物的文案不冒充「改完就好」，也不隐藏旧产物仍在", async () => {
  const lib = await readFile(libPath, "utf8");

  const helper = lib.slice(lib.indexOf("export function worklistRejectedHeadline"), lib.indexOf("export function worklistReasonCount"));

  assert.match(helper, /被人判「不通过」/, "必须直说判定结论");
  assert.match(helper, /涉及 \$\{fields\} 个字段/, "要说影响多少字段");
  assert.match(helper, /重新冻结导出/, "必须指出下一步");
  assert.match(helper, /旧产物不会被覆盖/, "不能让读者以为旧文件会被替换");
  assert.doesNotMatch(helper, /已解决|已完成/, "被否不是完成态");
});

test("字段行带得出「为什么被列进来」", async () => {
  const lib = await readFile(libPath, "utf8");
  const page = await readFile(pagePath, "utf8");

  assert.match(lib, /export function artifactRejectedText/, "需要把产物号、时间、依据拼成一句");
  assert.match(lib, /产物 #\$\{rejected\.artifact_id\} 被人判「不通过」/, "文案要能直接落到具体产物");
  assert.match(page, /artifactRejectedText\(item\)/, "行的 tooltip 必须用它");
  assert.match(page, /aria-label="被否产物提示"/, "弹层顶部要有单独提示区");
  assert.match(page, /data-rejected-artifact=\{entry\.artifact_id\}/, "提示区要列出是哪几份产物");
});

test("判定时间按 UTC 解释再转本地，不能把 UTC 当本地时间", async () => {
  const lib = await readFile(libPath, "utf8");

  assert.match(lib, /export function formatServerTime/, "需要一个统一的时间格式化函数");
  assert.match(lib, /不带时区的 UTC 时间/, "注释要说明数据来源的语义");
  assert.match(lib, /hasZone \? text : `\$\{text\}Z`/, "无时区的串必须按 UTC 补 Z");
  assert.match(lib, /formatServerTime\(rejected\.created_at\)/, "artifactRejectedText 要用它，而不是直接 slice");
  assert.doesNotMatch(lib, /created_at\.slice\(0, 16\)/, "直接切片会把 UTC 显示成本地时间");
});

test("判定在服务里，且按内容哈希继续压着（round 69 换掉了「只认同一份产物」）", async () => {
  const service = await readFile(servicePath, "utf8");

  assert.match(service, /def _rejected_artifacts/, "服务里要有独立判定函数");
  assert.match(service, /order_by\(RequirementRenderArtifact\.id\.desc\(\)\)/, "取产物按 id 倒序");
  assert.match(
    service,
    /setdefault\(int\(artifact_row\.requirement_id\), \[\]\)\.append/,
    "每条需求保留全部产物（按 id 倒序），才比得出内容变没变",
  );
  assert.match(
    service,
    /_text\(rejected_artifact\.content_hash\) != _text\(artifact_row\.content_hash\)/,
    "只换版式重导（content_hash 相同）必须继续压着，内容真变了才解除",
  );
  assert.match(service, /"later_artifact_count"/, "要说清被否之后又导出了几份");
  assert.match(service, /"rejected_requirement_count"/, "响应体要给出被否份数");
  assert.match(service, /"rejected_requirements"/, "响应体要给出被否清单");
  assert.match(service, /处置登记不会让被否的产物重新变成可交付/, "note 要写清处置与验收不是一回事");
  assert.doesNotMatch(service, /\.delete\(/, "只读归并，不得删除任何登记");
});
