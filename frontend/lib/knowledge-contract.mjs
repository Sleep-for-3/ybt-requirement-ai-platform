export const MODES = {
  regulatory: { label: "监管知识问答", description: "根据监管制度、监管答疑和已沉淀业务知识回答。", example: "客户证件类型的报送范围和监管依据是什么？", sections: ["结论", "适用范围", "监管依据", "待确认事项", "文档引用"] },
  data_field: { label: "数据字段与血缘问答", description: "查询真实目录、来源字段、映射与血缘，不执行SQL或查询客户明细。", example: "CERT_TYPE 来自哪个系统和表？有哪些码值转换？", sections: ["目标字段", "来源路径", "Join/关联条件", "过滤和加工转换", "码值映射", "缺口和待确认事项"] }
};
const BUSINESS_LABELS={regulatory_qa:"监管答疑",regulatory_policy:"监管制度",field_explanation:"字段解释",historical_mapping:"历史业务口径",historical_traceability:"历史技术溯源",east_mapping:"EAST 映射",business_research:"业务调研",technical_research:"技术调研",data_dictionary:"数据字典",code_mapping:"码值映射",manual_note:"人工沉淀",sql_evidence:"SQL 证据",project:"项目",institution:"机构",global:"全局",indexed:"已建立索引",parsed:"已解析",parsing:"正在解析",pending:"等待处理",failed:"处理失败",archived:"已归档",partially_indexed:"部分建立索引",parsed_with_warnings:"已解析，有警告"};
export function knowledgeLabel(value){return BUSINESS_LABELS[value]||value||"待确认";}
export function answerMode(value) { return value === "data_field" ? "data_field" : "regulatory"; }
export function askErrorMessage(error) {
  if (error?.status === 401) return "登录状态已失效，请重新登录。";
  if (error?.status === 403 || error?.status === 404) return "当前账号无权在此项目提问，请确认项目选择和访问权限。";
  if (error?.status === 0) return "网络连接失败，请检查连接后重试。";
  if (error?.status === 400 || error?.status === 422) return "问题或筛选条件无效，请检查后重新提交。";
  return "回答服务暂不可用，请稍后重试。";
}
export function askPayload(mode, query, target, scenario, includeHistory = false, historicalAsOf = "") {
  return { query: query.trim(), answer_mode: answerMode(mode), top_k: 8,
    ...(includeHistory ? { include_history: true, ...(historicalAsOf ? { historical_as_of: historicalAsOf } : {}) } : {}),
    ...(mode === "data_field" ? { target_field_id: target || null, scenario_id: scenario || null } : {}) };
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
