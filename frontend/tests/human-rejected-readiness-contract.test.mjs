/**
 * 人工核对「不通过」必须能压住就绪度，不能只躺在审计里。
 *
 * 为什么单独钉住：`readiness` 是看板排序与筛选的唯一依据。如果"不通过"只被写进
 * 审计表，看板会照旧显示"可直接重新导出"，负责人就会把一份被人否掉的文件再发一次。
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const read = (...parts) => readFileSync(join(root, ...parts), "utf8");
const lib = read("lib", "delivery-status.ts");
const page = read("app", "projects", "[projectId]", "readiness", "page.tsx");

test("就绪度枚举与文案包含 human_rejected，并排在需要动手的一侧", () => {
  assert.match(lib, /export type DeliveryReadiness =\r?\n\s*\| "human_rejected"/);
  assert.match(lib, /human_rejected: "人工核对不通过"/);
  assert.match(lib, /human_rejected: "badge-danger"/);
  // 排序：被否掉的行必须排在"已交付/可直接重新导出"之前。
  assert.match(lib, /human_rejected: -1,/);
  assert.match(lib, /const DELIVERY_FILTER_ORDER: DeliveryReadiness\[\] = \[\r?\n\s*"human_rejected",/);
});

test("筛选条数与提示都认得这个状态，且提示写明旧产物不会被覆盖", () => {
  assert.match(lib, /case "human_rejected":\r?\n\s*return summary\.human_rejected \?\? 0;/);
  assert.match(lib, /\+ \(summary\.human_rejected \?\? 0\)/);
  assert.match(lib, /case "human_rejected":\r?\n\s*return "这些产物的最新一份被人核对判了「不通过」：先按依据改正文，再重新冻结导出；旧产物不会被覆盖。"/);
});

test("前端推导与服务端同口径，详情不是空话", () => {
  // 老后端缺 readiness 时才本地推导：本地也必须能识别 human_rejected。
  assert.match(lib, /if \(item\.human_rejected\) return "human_rejected";/);
  assert.match(lib, /export function deliveryAttestationText\(item: DeliveryStatusItem\): string \{/);
  assert.match(lib, /还没有人工核对登记/);
  // 详情必须写清是谁、凭什么、针对哪份产物，而不是只写"不通过"。
  // round 69：被否的可能不是最新那份（换版式重导过），所以文案写"产物 #M"而不是"最新产物 #M"。
  assert.match(lib, /产物 #\$\{artifactId\} 被人工核对判「不通过」/);
  assert.match(lib, /const basis = rejection\?\.basis \?\? record\?\.basis \?\? "";/);
  assert.match(lib, /之后导出的 #\$\{rejection\.superseded_by\.id\} 内容与它一致（只换了版式\/渲染器）/);
});

test("看板把人工核对登记显示在就绪度下面，并带结论供核对", () => {
  assert.match(page, /import \{[\s\S]*?deliveryAttestationText[\s\S]*?\} from "@\/lib\/delivery-status"/);
  assert.match(page, /aria-label=\{`人工核对登记 \$\{item\.requirement_id\}`\}/);
  assert.match(page, /data-attestation-conclusion=\{item\.latest_attestation\.conclusion\}/);
  assert.match(page, /data-attestation-on-latest=\{item\.latest_attestation\.on_latest_artifact \? "1" : "0"\}/);
  assert.match(page, /\{deliveryAttestationText\(item\)\}/);
});

test("服务端把人工核对结论接进就绪度，且按内容哈希压着同一份正文", () => {
  const service = readFileSync(
    join(root, "..", "backend", "app", "services", "requirement_delivery_status.py"),
    "utf8",
  );
  assert.match(service, /RequirementArtifactAttestation/);
  assert.match(service, /def _readiness\([\s\S]*?human_rejected: bool = False,[\s\S]*?\) -> str:/);
  assert.match(service, /if human_rejected:\r?\n\s*# 最近一份产物被人判"不通过"[\s\S]*?return "human_rejected"/);
  // round 69：判据从"同一个 artifact_id"改成"同一份 content_hash"，
  // 否则换版式重导一次（正文没动）红牌就会自己消失。
  assert.match(service, /rejection_matches_latest_content = bool\(/);
  assert.match(service, /rejection_content_hash == latest_artifact\.content_hash/);
  assert.match(service, /human_rejected = bool\(rejection is not None and rejection_matches_latest_content\)/);
  assert.match(service, /"rejection": None if rejection is None else \{/);
  assert.match(service, /"human_rejected": 0,/);
});
