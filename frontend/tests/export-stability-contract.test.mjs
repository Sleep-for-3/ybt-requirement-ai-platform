/**
 * 交付稳定性核对契约：重放一致才算稳定；旧版渲染器产物与不支持重放都不能算通过。
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..");
const page = readFileSync(join(root, "app", "projects", "[projectId]", "readiness", "page.tsx"), "utf8");
const lib = readFileSync(join(root, "lib", "export-stability.ts"), "utf8");
const service = readFileSync(
  join(root, "..", "backend", "app", "services", "requirement_export_stability.py"),
  "utf8",
);
const api = readFileSync(join(root, "..", "backend", "app", "api", "requirements.py"), "utf8");

test("看板有稳定性核对入口，点开调只读端点并列到产物级", () => {
  assert.match(page, /aria-label="交付稳定性核对"/);
  assert.match(page, /\/projects\/\$\{projectId\}\/export-stability\?limit=20/);
  assert.match(page, /aria-label="交付稳定性核对"/);
  assert.match(page, /data-stability-status=\{item\.status\}/);
  assert.match(page, /data-artifact-id=\{item\.artifact_id\}/);
  assert.match(page, /aria-label="关闭稳定性核对"/);
  assert.match(page, /\{EXPORT_STABILITY_DISCLAIMER\}/);
});

test("文案不把“旧版渲染器/不支持重放”混成通过", () => {
  assert.match(lib, /旧版渲染器 \$\{summary\.historical\} 个/);
  assert.match(lib, /不支持重放 \$\{summary\.unsupported\} 个/);
  assert.match(lib, /没有发现渲染器漂移或内容漂移/);
  assert.match(lib, /先查是冻结内容变了还是渲染器改了没升版本/);
  assert.match(lib, /EXPORT_STABILITY_DISCLAIMER =\s*\n?\s*"稳定性核对只读：不重新冻结、不重新生成、不写库。/);
  assert.doesNotMatch(lib, /全部通过|已确认稳定|可以交付/);
});

test("服务端先判版本再判字节，旧版渲染器单独计数", () => {
  assert.match(service, /STATUS_HISTORICAL = "historical"/);
  assert.match(service, /def current_renderer_version\(/);
  assert.match(service, /if expected and \(artifact\.renderer_version or ""\) != expected:/);
  assert.match(service, /旧版渲染器已不存在/);
  // 判定顺序：产物在不在 → 版本对不对 → 字节一不一致。
  const historicalAt = service.indexOf("STATUS_HISTORICAL\n");
  const identicalAt = service.indexOf("entry[\"status\"] = STATUS_IDENTICAL");
  assert.ok(historicalAt > 0 && identicalAt > historicalAt, "历史版本判定必须在字节比对之前");
});

test("服务端只读：不写库、不删记录、不重新冻结", () => {
  assert.doesNotMatch(service, /db\.add\(/);
  assert.doesNotMatch(service, /db\.commit\(/);
  assert.doesNotMatch(service, /db\.delete\(/);
  assert.doesNotMatch(service, /\.delete\(/);
  assert.doesNotMatch(service, /freeze_draft|ensure_artifact\(/);
  assert.match(service, /只读：只读库里的冻结内容与产物文件/);
});

test("端点只读且按项目鉴权", () => {
  assert.match(api, /@router\.get\("\/projects\/\{project_id\}\/export-stability"\)/);
  assert.match(api, /require_project_permission\(project_id, "project\.view"\)/);
  assert.match(api, /from app\.services\.requirement_export_stability import StabilityError, build_stability/);
});
