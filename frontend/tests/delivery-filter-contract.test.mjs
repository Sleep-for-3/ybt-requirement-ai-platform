import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it } from "node:test";

const root = process.cwd();
const lib = readFileSync(path.join(root, "lib/delivery-status.ts"), "utf8");
const page = readFileSync(path.join(root, "app/projects/[projectId]/readiness/page.tsx"), "utf8");

describe("交付状态筛选：点一下就只看这一档，勾选后走同一个批量冻结入口", () => {
  it("筛选键覆盖全部就绪状态，且带“全部需求”", () => {
    assert.match(lib, /export type DeliveryStatusFilter = "all" \| DeliveryReadiness;/);
    assert.match(lib, /export const DELIVERY_STATUS_FILTERS/);
    assert.match(lib, /key: "all", label: "全部需求"/);
    // 七态都要能筛；少一个就等于那一档需求点不进去
    for (const key of ["stale", "delivered_stale", "metadata_stale", "no_snapshot", "frozen", "exportable", "delivered"]) {
      assert.match(lib, new RegExp(`"${key}"`));
    }
    assert.match(lib, /\.\.\.DELIVERY_FILTER_ORDER\.map\(\(key\) => \(\{ key, label: READINESS_LABELS\[key\] \}\)\)/);
  });

  it("条数来自服务端 summary，不在前端重新数", () => {
    assert.match(lib, /export function deliveryFilterCount\(summary: DeliveryStatusSummary, filter: DeliveryStatusFilter\): number/);
    assert.match(lib, /return summary\.metadata_stale \?\? 0;/);
    assert.match(lib, /return summary\.stale;/);
    // 不允许前端把同一批行数成两档
    assert.doesNotMatch(lib, /filter\(\(item\) => deliveryReadiness\(item\) === filter\)\.length/);
  });

  it("筛选只按服务端的就绪状态，不按就绪文案猜", () => {
    assert.match(lib, /return items\.filter\(\(item\) => deliveryReadiness\(item\) === filter\);/);
    assert.match(lib, /case "metadata_stale":\r?\n\s+return "这些只需要重新冻结一次：正文口径没变，变的是模板带过来的表级引用元数据。";/);
  });

  it("页面渲染筛选条、当前显示数与“勾选这 N 条”", () => {
    assert.match(page, /aria-label="交付状态筛选"/);
    assert.match(page, /DELIVERY_STATUS_FILTERS\.map/);
    assert.match(page, /deliveryFilterCount\(delivery\.summary, filter\.key\)/);
    assert.match(page, /当前显示 \{visibleDeliveryItems\.length\} \/ \{delivery\.items\.length\} 条/);
    assert.match(page, /勾选这 \{visibleDeliveryItems\.length\} 条/);
    assert.match(page, /filterDeliveryItems\(delivery\.items, deliveryFilter\)/);
  });

  it("表体只画筛选结果，筛空时要解释而不是给一张空表", () => {
    assert.match(page, /sortDeliveryItems\(visibleDeliveryItems, deliverySort\)\.map\(\(item\) => \{/);
    assert.match(page, /当前筛选没有需求（共 \{delivery\.items\.length\} 条）/);
    // 勾选集合仍然按 requirement_id 存，切筛选不会把已勾的丢掉
    assert.match(page, /const next = new Set\(current\);/);
  });
});
