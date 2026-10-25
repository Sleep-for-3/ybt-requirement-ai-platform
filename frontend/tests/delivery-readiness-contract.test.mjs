import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

const lib = readFileSync(new URL("../lib/delivery-status.ts", import.meta.url), "utf8");
const page = readFileSync(
  new URL("../app/projects/[projectId]/readiness/page.tsx", import.meta.url),
  "utf8",
);

describe("项目级交付就绪：只在服务端判定的基础上展示，不自行推断", () => {
  it("就绪度七态齐全，且 exportable 必须有产物", () => {
    for (const key of ["delivered", "delivered_stale", "exportable", "frozen", "metadata_stale", "stale", "no_snapshot"]) {
      assert.match(lib, new RegExp(`\\b${key}\\b`));
    }
    assert.match(lib, /delivered: "已正式交付"/);
    assert.match(lib, /delivered_stale: "已交付，内容已改"/);
    assert.match(lib, /exportable: "可直接重新导出"/);
    assert.match(lib, /frozen: "已冻结，尚未导出"/);
    // 只差一次重新冻结的需求，不能和"正文真改了"混成一条
    assert.match(lib, /metadata_stale: "仅引用元数据更新"/);
    // 已冻结但没产物不能叫"可直接导出"
    assert.match(lib, /return item\.artifact_count \? "exportable" : "frozen";/);
  });

  it("就绪度优先读服务端字段，缺失时按同一规则回退", () => {
    assert.match(lib, /const given = \(item as DeliveryStatusItem & \{ readiness\?: DeliveryReadiness \}\)\.readiness;/);
    assert.match(lib, /if \(given\) return given;/);
  });

  it("排序只重排展示，按就绪度时需要动手的排前面", () => {
    assert.match(lib, /const READINESS_RANK: Record<DeliveryReadiness, number> = \{/);
    assert.match(lib, /stale: 0,/);
    // 需要动手的（含"交付后内容又改了"）都排在已交付前面
    assert.match(lib, /delivered_stale: 1,/);
    assert.match(lib, /metadata_stale: 2,/);
    assert.match(lib, /exportable: 5,/);
    assert.match(lib, /delivered: 6,/);
    assert.match(lib, /export function sortDeliveryItems\(items: DeliveryStatusItem\[\], mode: "priority" \| "id"\)/);
  });

  it("正式交付文案必须点出与当前内容是否一致", () => {
    assert.match(lib, /export function formalDeliveryText\(item: DeliveryStatusItem\): string/);
    assert.match(lib, /"无正式交付"/);
    assert.match(lib, /内容早于当前版本/);
    assert.match(lib, /内容与当前一致/);
  });

  it("头条五条互斥且与总数对得上", () => {
    assert.match(lib, /可直接导出 \$\{summary\.exportable \?\? 0\} 条/);
    assert.match(lib, /已冻结未导出 \$\{summary\.frozen_pending_export \?\? 0\} 条/);
    assert.match(lib, /有未冻结改动 \$\{summary\.stale\} 条/);
    assert.match(lib, /无快照 \$\{summary\.no_snapshot\} 条/);
    // 仅元数据更新单独一段，且与 stale 互斥
    assert.match(lib, /仅元数据更新 \$\{metaOnly\} 条（仅引用元数据变化）/);
  });

  it("页面渲染就绪度徽标、正式交付列与排序开关", () => {
    assert.match(page, /READINESS_LABELS\[readiness\]/);
    assert.match(page, /READINESS_BADGE\[readiness\]/);
    assert.match(page, /formalDeliveryText\(item\)/);
    // 表体画的是筛选结果；默认「全部需求」时等于全部
    assert.match(page, /sortDeliveryItems\(visibleDeliveryItems, deliverySort\)/);
    assert.match(page, /aria-pressed=\{deliverySort === "priority"\}/);
    assert.match(page, /aria-pressed=\{deliverySort === "id"\}/);
    assert.match(page, /按就绪度/);
    assert.match(page, /按需求编号/);
    assert.match(page, /交付就绪/);
    assert.match(page, /正式交付/);
  });

  it("页面不得自行推断冻结或就绪状态", () => {
    assert.doesNotMatch(page, /frozen\s*=\s*[^;]*requirement_version/);
    assert.doesNotMatch(page, /frozen\s*=\s*[^;]*snapshot_count/);
    assert.doesNotMatch(page, /readiness\s*=\s*[^;]*artifact_count\s*\?/);
    assert.doesNotMatch(page, /const READINESS_LABELS/);
  });
});
