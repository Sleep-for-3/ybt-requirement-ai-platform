export const MODES = {
  regulatory: { label: "监管知识问答", description: "根据监管制度、监管答疑和已沉淀业务知识回答。", example: "客户证件类型的报送范围和监管依据是什么？", sections: ["结论", "适用范围", "监管依据", "待确认事项", "文档引用"] },
  data_field: { label: "数据字段与血缘问答", description: "查询真实目录、来源字段、映射与血缘，不执行SQL或查询客户明细。", example: "CERT_TYPE 来自哪个系统和表？有哪些码值转换？", sections: ["目标字段", "来源路径", "Join/关联条件", "过滤和加工转换", "码值映射", "缺口和待确认事项"] }
};
const BUSINESS_LABELS={regulatory_qa:"监管答疑",regulatory_policy:"监管制度",field_explanation:"字段解释",historical_mapping:"历史业务口径",historical_traceability:"历史技术溯源",east_mapping:"EAST 映射",business_research:"业务调研",technical_research:"技术调研",data_dictionary:"数据字典",code_mapping:"码值映射",manual_note:"人工沉淀",sql_evidence:"SQL 证据",project:"项目",institution:"机构",global:"全局",indexed:"已建立索引",parsed:"已解析",parsing:"正在解析",pending:"等待处理",failed:"处理失败",archived:"已归档",partially_indexed:"部分建立索引",parsed_with_warnings:"已解析，有警告"};
export function knowledgeLabel(value){const mapped=BUSINESS_LABELS[value];if(mapped)return mapped;if(typeof value==="string"&&/[\u4e00-\u9fff]/.test(value))return value;return "其他状态或分类";}
export function answerMode(value) { return value === "data_field" ? "data_field" : "regulatory"; }
export function askErrorMessage(error) {
  if (error?.status === 401) return "登录状态已失效，请重新登录。";
  if (error?.status === 403 || error?.status === 404) return "当前账号无权在此项目提问，请确认项目选择和访问权限。";
  if (error?.status === 0) return "网络连接失败，请检查连接后重试。";
  if (error?.status === 400 || error?.status === 422) return "问题或筛选条件无效，请检查后重新提交。";
  return "回答服务暂不可用，请稍后重试。";
}

/**
 * 回答阶段的中文提示（页面与回归共用同一份逻辑，避免“测试一套、页面另一套”）。
 *
 * 三种基础状态保留原有口径；引用支撑校验是**附加**信息：
 * - 开关未开启时明示“尚未进行引用支撑校验”，绝不出现任何“已验证”字样；
 * - 校验失败/未完成时明示无法验证，而不是让用户以为已经核实过；
 * - 底层错误串（timeout / RuntimeError 等）一律不上页面，只给中文归类。
 */
export function answerStatusNotice(result) {
  const status = result?.answer_status;
  const support = result?.citation_support;
  const base = status === "degraded"
    ? "回答服务暂不可用，以下展示已获取的证据，结论待确认。"
    : status === "needs_confirmation"
      ? "证据不足或尚未确认，请核验下方缺口。"
      : "已找到依据，请核验适用范围与引用。";
  if (!support || support.enabled === false) {
    return { text: base, tone: status === "degraded" ? "danger" : "neutral",
      verification: null };
  }
  const verification = support.verification || "unknown";
  const tone = verification === "verified" ? "neutral" : status === "degraded" ? "danger" : "warning";
  return { text: `${base}${supportVerificationNotice(support)}`, tone, verification };
}

/** 引用支撑校验的中文结论；未知值不得回显原始英文。 */
export function supportVerificationNotice(support) {
  const counts = supportCounts(support);
  const verification = support?.verification;
  const suffix = counts.unjudged > 0 && verification !== "verified"
    ? `（另有 ${counts.unjudged} 条结论未能判定）`
    : "";
  const text = {
    verified: "引用支撑校验通过：结论与引用一致。",
    partially_supported: "部分结论有引用支撑，其余无法验证，请以引用原文为准。",
    unsupported: "关键结论缺少引用支撑，不能作为已证实结论使用。",
    unknown: "引用支撑校验未完成，结论暂无法验证。",
    degraded: "引用支撑校验失败，本次结论无法验证。"
  }[String(verification || "")] || "引用支撑校验状态未知，请人工核验引用原文。";
  return text + suffix;
}

/** 校验的分母与计数，供页面展示“已判定/未知/未判定”。 */
export function supportCounts(support) {
  const toInt = (value) => (Number.isFinite(Number(value)) ? Math.trunc(Number(value)) : 0);
  const total = toInt(support?.claims_total);
  const judged = toInt(support?.claims_judged);
  return {
    total,
    judged,
    unjudged: Math.max(toInt(support?.claims_unjudged), total - judged),
    supported: toInt(support?.claims_supported),
    unsupported: toInt(support?.claims_unsupported),
    unknown: toInt(support?.claims_unknown),
    coverage: typeof support?.claim_coverage === "number" ? support.claim_coverage : null,
    truncated: Boolean(support?.coverage_truncated)
  };
}

/** 覆盖率的中文展示；分母为 0 时显示“—”，不得伪装成 100%。 */
export function coverageText(value) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(0)}%` : "—";
}
export function askPayload(mode, query, target, scenario, includeHistory = false, historicalAsOf = "", pin = null) {
  // 版本钉扎只在需求与内容版本同时给出时才发送；任一缺失都不猜测，交由后端一致性校验。
  const pinFields = pin && pin.requirementId && pin.contentVersion
    ? { requirement_id: Number(pin.requirementId), requirement_content_version: Number(pin.contentVersion) }
    : {};
  return { query: query.trim(), answer_mode: answerMode(mode), top_k: 8,
    ...(includeHistory ? { include_history: true, ...(historicalAsOf ? { historical_as_of: historicalAsOf } : {}) } : {}),
    ...(mode === "data_field" ? { target_field_id: target || null, scenario_id: scenario || null } : {}),
    ...pinFields };
}
/** 钉扎状态的用户可见说明：不得把“未固定”渲染成“已固定”。 */
export function pinNotice(pin, versionPin) {
  if (!pin) return { tone: "none", text: "" };
  const label = `需求 v${pin.contentVersion}`;
  if (!versionPin) return { tone: "warn", text: `已请求固定${label}的监管版本，但本次回答未回显固定版本，结论需人工核对。` };
  const pinned = versionPin.pinned_versions && typeof versionPin.pinned_versions === "object"
    ? Object.entries(versionPin.pinned_versions).map(([title, version]) => `${title}=${version}`) : [];
  return { tone: "pinned", text: `本次回答固定使用${label}冻结的监管版本：${pinned.length ? pinned.join("；") : "（该需求未记录具体制度版本）"}` };
}
export function citationLocator(c) {
  return { page_no: c.source_page_no, sheet_name: c.source_sheet_name, cell_range: c.source_cell_range,
    block_id: c.knowledge_unit_id ? `knowledge-unit-${c.knowledge_unit_id}` : undefined, text_quote: c.quoted_content, ...c.locator };
}
export function locateBlock(blocks, locator = {}) {
  let match = locator.block_id && blocks.find(b => b.block_id === locator.block_id);
  if (match) return match.block_id;
  const keys = ["sheet_name", "cell_range", "paragraph_index", "page_no", "heading", "line_start", "table_index", "row_no"].filter(k => locator[k] != null);
  if (keys.length) match = blocks.find(b => keys.every(k => b.locator?.[k] === locator[k]));
  if (!match && locator.text_quote) match = blocks.find(b => b.text.includes(locator.text_quote));
  return match?.block_id || null;
}
export function viewerFormat(type) { return type === "pdf" ? "pdf" : type === "xlsx" ? "grid" : ["txt", "md", "sql"].includes(type) ? "text" : "blocks"; }
export function ownedBlobUrl(blob, api = URL) {
  const url = api.createObjectURL(blob); let active = true;
  return { url, dispose() { if (active) { active = false; api.revokeObjectURL(url); } } };
}
export function evidenceTarget(c, projectId) {
  if(c.citation_type==="knowledge_document"||c.document_id||c.knowledge_unit_id)
    return {kind:"document",documentId:c.document_id,unitId:c.knowledge_unit_id,versionId:c.document_version_id,locator:citationLocator(c)};
  if(c.project_id!==projectId)return null;
  const source=c.source_type||c.mapping_type||c.citation_type;
  const key={catalog_column:"catalog_column_id",source_field:"source_field_id",lineage_edge:"lineage_edge_id",scenario_technical:"mapping_id",source_to_mart:"mapping_id",mart_to_ybt:"mapping_id"}[source];
  const id=key&&c[key];
  if(!Number.isInteger(id)||id<=0)return null;
  return {kind:"entity",path:`/projects/${projectId}/knowledge/evidence/${source}/${id}`};
}
