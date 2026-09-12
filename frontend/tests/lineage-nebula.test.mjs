import assert from "node:assert/strict";
import test from "node:test";

import {
  LAYER_ORDER,
  MISSING_BUSINESS_REMARK,
  NEBULA_MOTION_NOTE,
  buildNebulaModel,
  curvePath,
  edgeGeometry,
  layerAccent,
  layoutNebula,
  nebulaFactSignature,
  nebulaTableRows,
  normalizeLayerCode,
  resolveNebulaLabel,
  summarizeGaps
} from "../lib/lineage-nebula.mjs";

function node(id, layerCode, options = {}) {
  const { name = `节点${id}`, technical = `TBL_${id}.COL_${id}`, comment = null, quality, source, unresolved = false } = options;
  return {
    id: String(id),
    entity_type: "target_field",
    canonical_entity_id: Number(id),
    node_type: "column",
    display: {
      display_name: name,
      business_name: name,
      comment,
      technical_name: technical,
      qualified_technical_name: technical,
      label_quality: quality || (name ? "confirmed" : "missing"),
      display_name_source: source || (name ? "business_name" : "technical_name"),
      layer_code: layerCode
    },
    layer_code: layerCode,
    unresolved_flag: unresolved,
    resolution_status: "resolved",
    script_file_version_ids: [11]
  };
}

function edge(id, from, to, options = {}) {
  const { relationSource = "technical_lineage", join = null, filter = null, expression = null } = options;
  return {
    id: String(id),
    source_node_id: String(from),
    target_node_id: String(to),
    edge_type: "column_level",
    relation_source: relationSource,
    confidence_level: "high",
    verification_status: "verified",
    join_condition: join,
    filter_condition: filter,
    transformation_expression: expression,
    evidence_refs: [{ id: 1, source_name: "脚本" }]
  };
}

function payload(options = {}) {
  const {
    nodes = [
      node(4, "TARGET", { name: "监管报送客户标识" }),
      node(1, "SOURCE", { name: "源系统客户标识" }),
      node(2, "MART", { name: "监管集市客户标识" }),
      node(3, "UNKNOWN_LAYER", { name: "未登记层级字段", technical: "MISC.FLD" })
    ],
    edges = [
      edge("e1", 1, 2, { join: "CUSTOMER.CUST_ID = MART.CUSTOMER_ID", filter: "IS_DELETED = 0" }),
      edge("e2", 2, 4, { relationSource: "business_mapping", expression: "直接映射" })
    ],
    paths = [
      { path_id: "p1", node_ids: ["1", "2", "4"], edge_ids: ["e1", "e2"], complete: true, confidence: "high" }
    ],
    gaps = []
  } = options;
  return {
    project_id: 7,
    root: { entity_type: "target_field", entity_id: 4, node_id: "4", display: { display_name: "监管报送客户标识" } },
    revision_id: 33,
    revision_no: 5,
    as_of: "2026-09-10T10:00:00+08:00",
    direction: "upstream",
    depth: 6,
    view: "business",
    nodes,
    edges,
    paths,
    gap_recommendations: gaps,
    truncated: false,
    warnings: [],
    confidence: "high"
  };
}

test("layers follow the data-flow order and unknown layers fall back safely", () => {
  const model = buildNebulaModel(payload());

  assert.deepEqual(
    model.layers.map((layer) => layer.layerCode),
    ["SOURCE", "MART", "TARGET", "UNKNOWN"]
  );
  assert.deepEqual(
    model.layers.map((layer) => layer.layerName),
    ["源系统", "监管集市", "监管输出", "未识别层级"]
  );
  assert.equal(normalizeLayerCode({ layer_code: "dwd" }), "DWD");
  assert.equal(normalizeLayerCode({ layer_code: "有问题的层级" }), "UNKNOWN");
  assert.equal(model.revision.label, "已发布血缘版本 v5");
  assert.equal(model.stats.layerCount, 4);
  assert.equal(model.stats.edgeCount, 2);
});

test("the same payload always produces the same model regardless of input order", () => {
  const forward = buildNebulaModel(payload());
  const reversed = buildNebulaModel(payload({ nodes: [...payload().nodes].reverse(), edges: [...payload().edges].reverse() }));

  assert.deepEqual(nebulaFactSignature(forward), nebulaFactSignature(reversed));
  assert.deepEqual(
    forward.layers.map((layer) => layer.nodes.map((item) => item.id)),
    reversed.layers.map((layer) => layer.nodes.map((item) => item.id))
  );
});

test("business names stay primary while technical names remain secondary", () => {
  const labelled = resolveNebulaLabel(node(1, "MART", { name: "监管集市客户标识", technical: "MART_CUSTOMER.CUSTOMER_ID", comment: "监管集市客户唯一标识" }));
  assert.equal(labelled.primary, "监管集市客户标识");
  assert.equal(labelled.technical, "MART_CUSTOMER.CUSTOMER_ID");
  assert.equal(labelled.comment, "监管集市客户唯一标识");
  assert.equal(labelled.missingRemark, false);

  const technicalOnly = resolveNebulaLabel({
    display: {
      display_name: "ODS_CUSTOMER.CUST_ID",
      technical_name: "ODS_CUSTOMER.CUST_ID",
      label_quality: "missing",
      display_name_source: "technical_name"
    }
  });
  assert.equal(technicalOnly.primary, MISSING_BUSINESS_REMARK);
  assert.equal(technicalOnly.rawPrimary, "ODS_CUSTOMER.CUST_ID");
  assert.equal(technicalOnly.missingRemark, true);
});

test("focusing a node highlights its path and dims the rest", () => {
  const nodes = [...payload().nodes, node(9, "SOURCE", { name: "未参与路径的源字段" })];
  const model = buildNebulaModel(payload({ nodes }), { focusNodeId: "2" });

  assert.equal(model.focus.active, true);
  assert.deepEqual([...model.focus.highlightedNodeIds].sort(), ["1", "2", "4"]);
  // 未参与该路径的节点（含未登记层级节点）都应被弱化，但不会被移除。
  assert.deepEqual([...model.focus.dimmedNodeIds].sort(), ["3", "9"]);
  assert.deepEqual(
    model.edges.map((item) => [item.id, item.highlighted, item.dimmed]),
    [
      ["e1", true, false],
      ["e2", true, false]
    ]
  );
  const sourceLayer = model.layers.find((layer) => layer.layerCode === "SOURCE");
  assert.deepEqual([...sourceLayer.nodes].map((item) => item.label.primary).sort(), ["未参与路径的源字段", "源系统客户标识"]);
  assert.equal(sourceLayer.nodeCount, 2);
});

test("dimming hides edges that are not on the focused path", () => {
  const nodes = [...payload().nodes, node(9, "SOURCE", { name: "旁路源字段" })];
  const edges = [...payload().edges, edge("e9", 9, 2)];
  const focused = buildNebulaModel(payload({ nodes, edges }), { focusNodeId: "2" });
  const unfocused = buildNebulaModel(payload({ nodes, edges }));

  assert.equal(focused.edges.find((item) => item.id === "e9").dimmed, true);
  assert.equal(unfocused.edges.every((item) => item.dimmed === false && item.highlighted === true), true);
  assert.deepEqual(unfocused.focus.dimmedNodeIds, []);
});

test("per-layer truncation drops hidden nodes together with their edges", () => {
  const dense = [
    node(1, "SOURCE", { name: "A源字段" }),
    node(2, "SOURCE", { name: "B源字段" }),
    node(3, "SOURCE", { name: "C源字段" }),
    node(4, "TARGET", { name: "监管报送字段" })
  ];
  const edges = [edge("e1", 1, 4), edge("e2", 2, 4), edge("e3", 3, 4)];
  const model = buildNebulaModel(payload({ nodes: dense, edges, paths: [] }), { maxNodesPerLayer: 2 });

  const sourceLayer = model.layers.find((layer) => layer.layerCode === "SOURCE");
  assert.equal(sourceLayer.nodeCount, 3);
  assert.equal(sourceLayer.nodes.length, 2);
  assert.equal(sourceLayer.hiddenCount, 1);
  assert.equal(sourceLayer.truncated, true);
  assert.equal(model.stats.hiddenNodeCount, 1);
  // 被截断节点的边不能出现在图或表格里。
  assert.deepEqual(model.edges.map((item) => item.id), ["e1", "e2"]);
  assert.equal(model.warnings.some((warning) => warning.includes("已按顺序截断")), true);
  assert.equal(model.flags.layerTruncated, true);
});

test("the graph and the table are driven by exactly the same facts", () => {
  const model = buildNebulaModel(payload());
  const signature = nebulaFactSignature(model);
  const rows = nebulaTableRows(model);
  const nodeIds = new Set(model.layers.flatMap((layer) => layer.nodes.map((item) => item.id)));

  assert.deepEqual(signature.rowEdgeIds, signature.edgeIds);
  assert.equal(rows.length, model.edges.length);
  for (const row of rows) {
    assert.equal(nodeIds.has(row.source.id), true);
    assert.equal(nodeIds.has(row.target.id), true);
    assert.ok(row.summary.length > 0);
  }
  const first = rows.find((row) => row.edgeId === "e1");
  assert.equal(first.source.primary, "源系统客户标识");
  assert.equal(first.target.primary, "监管集市客户标识");
  assert.equal(first.relation, "脚本解析血缘");
  assert.match(first.summary, /关联 CUSTOMER\.CUST_ID = MART\.CUSTOMER_ID/);
  assert.match(first.summary, /过滤 IS_DELETED = 0/);
});

test("layout and edge geometry are deterministic and bounded", () => {
  const model = buildNebulaModel(payload());
  const layout = layoutNebula(model);
  const again = layoutNebula(buildNebulaModel(payload()));

  assert.deepEqual(layout.positions, again.positions);
  assert.equal(layout.columns.length, model.layers.length);
  assert.equal(layout.width, 28 * 2 + model.layers.length * 300);
  assert.equal(layout.height, 28 * 2 + 36 + 1 * 104);
  const geometry = edgeGeometry(model, layout);
  assert.equal(geometry.length, model.edges.length);
  for (const item of geometry) {
    assert.match(item.path, /^M \d+/);
    assert.match(item.path, / C /);
  }
  assert.match(curvePath({ x1: 100, y1: 10, x2: 20, y2: 30 }), /^M 100 10 C 124 10, -4 30, 20 30$/);
});

test("gap recommendations keep reviewer fields and are grouped by type and source", () => {
  const gaps = [
    {
      gap_type: "missing_lineage_revision",
      problem_statement: "项目尚无已发布的正式血缘版本",
      recommended_change: "构建、审核并发布项目级血缘版本后再冻结需求快照",
      rationale: "正式需求文档只能引用可按版本回看的事实",
      estimated_impact: "影响需求文档完整性",
      confidence_level: "high",
      approval_status: "pending_review",
      source: "lineage_path",
      affected_assets: [{ entity_type: "target_field", canonical_entity_id: 4, display_name: "监管报送客户标识", label_quality: "confirmed" }]
    },
    {
      gap_type: "missing_business_comment",
      problem_statement: "路径中有 1 个资产缺少可用中文业务备注",
      recommended_change: "在元数据目录维护中文业务名称",
      rationale: "平台面向业务用户，缺备注会降低可读性",
      estimated_impact: "业务无法确认字段口径",
      confidence_level: "medium",
      approval_status: "approved",
      source: "requirement_snapshot",
      affected_assets: [{ entity_type: "mart_field", display_name: "未命名集市字段", technical_name: "MART.X" }]
    }
  ];
  const summary = summarizeGaps(gaps);

  assert.equal(summary.total, 2);
  assert.deepEqual(summary.bySource, { lineage_path: 1, requirement_snapshot: 1 });
  assert.deepEqual(summary.byType, { missing_business_comment: 1, missing_lineage_revision: 1 });
  assert.equal(summary.pendingReview, 1);
  assert.deepEqual(
    summary.items.map((item) => `${item.source}:${item.gapType}`),
    ["lineage_path:missing_lineage_revision", "requirement_snapshot:missing_business_comment"]
  );
  assert.equal(summary.items[0].assets[0].displayName, "监管报送客户标识");
  assert.equal(summary.items[1].assets[0].displayName, "未命名集市字段");
  assert.equal(summarizeGaps(undefined).total, 0);
});

test("motion copy is explicit and every layer has a stable accent", () => {
  assert.match(NEBULA_MOTION_NOTE, /不代表跑批脚本正在运行/);
  assert.match(NEBULA_MOTION_NOTE, /不代表数据正在实时流动/);
  for (const code of LAYER_ORDER) {
    assert.match(layerAccent(code), /^#[0-9a-f]{6}$/i);
  }
  assert.equal(layerAccent("NOT_A_LAYER"), layerAccent("UNKNOWN"));
});
