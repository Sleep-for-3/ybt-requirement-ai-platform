const CONCEPT_TYPES = new Set([
  "business_term",
  "metric",
  "dimension",
  "code_set",
  "business_rule",
  "regulatory_rule"
]);
const LIFECYCLE_STATUSES = new Set(["draft", "ai_suggested", "confirmed", "rejected", "deprecated"]);
const DETAIL_TABS = new Set(["overview", "bindings", "relations", "evidence", "lineage", "governance", "versions"]);
const DEFAULT_PAGE_SIZE = 50;
const CURRENT_ONLY_LABEL = "当前状态，不代表该历史日期";

const ENTITY_LABELS = {
  target_table: "目标表",
  target_field: "目标字段",
  mart_table: "集市表",
  mart_field: "集市字段",
  source_table: "来源表",
  source_field: "来源字段",
  scenario: "业务场景",
  knowledge_unit: "知识单元",
  source_to_mart_mapping: "来源到集市映射",
  mart_to_ybt_mapping: "集市到一表通映射",
  scenario_business_mapping: "场景业务映射",
  scenario_technical_lineage: "场景技术血缘"
};

export function parseCatalogQuery(input = "") {
  const params = toSearchParams(input);
  return normalizeCatalogState({
    q: textParam(params, "q"),
    type: enumParam(params, "type", CONCEPT_TYPES),
    domain: textParam(params, "domain"),
    status: enumParam(params, "status", LIFECYCLE_STATUSES),
    owner: textParam(params, "owner"),
    as_of: dateParam(params, "as_of"),
    has_binding: booleanParam(params, "has_binding"),
    has_relation: booleanParam(params, "has_relation"),
    pending_review: booleanParam(params, "pending_review"),
    audit: booleanParam(params, "audit") === true,
    view: params.get("view") === "table" ? "table" : "directory",
    page: positiveInteger(params.get("page"), 1),
    page_size: boundedPageSize(params.get("page_size"))
  });
}

export function serializeCatalogQuery(input) {
  const state = normalizeCatalogState(input);
  const params = new URLSearchParams();
  setText(params, "q", state.q);
  setText(params, "type", state.type);
  setText(params, "domain", state.domain);
  setText(params, "status", state.status);
  setText(params, "owner", state.owner);
  setText(params, "as_of", state.as_of);
  setBoolean(params, "has_binding", state.has_binding);
  setBoolean(params, "has_relation", state.has_relation);
  setBoolean(params, "pending_review", state.pending_review);
  if (state.audit) params.set("audit", "1");
  if (state.view === "table") params.set("view", "table");
  if (state.page !== 1) params.set("page", String(state.page));
  if (state.page_size !== DEFAULT_PAGE_SIZE) params.set("page_size", String(state.page_size));
  return params.toString();
}

export function applyCatalogQueryChange(current, changes, options = {}) {
  const resetPage = options.resetPage !== false && !Object.prototype.hasOwnProperty.call(changes, "page");
  return normalizeCatalogState({ ...current, ...changes, page: resetPage ? 1 : changes.page ?? current.page });
}

export function catalogHasFilters(input) {
  const state = normalizeCatalogState(input);
  return Boolean(
    state.q || state.type || state.domain || state.status || state.owner || state.as_of ||
    state.has_binding !== null || state.has_relation !== null || state.pending_review !== null || state.audit
  );
}

export function buildCatalogRequestKey(projectId, input) {
  return `${positiveInteger(projectId, 0)}:${serializeCatalogQuery(input)}`;
}

export function parseDetailQuery(input = "") {
  const params = toSearchParams(input);
  const tab = enumParam(params, "tab", DETAIL_TABS) || "overview";
  return {
    tab,
    as_of: dateParam(params, "as_of"),
    version: nullablePositiveInteger(params.get("version")),
    returnTo: safeSemanticReturnTo(params.get("returnTo") || "")
  };
}

export function serializeDetailQuery(input) {
  const params = new URLSearchParams();
  const tab = DETAIL_TABS.has(String(input?.tab || "")) ? String(input.tab) : "overview";
  if (tab !== "overview") params.set("tab", tab);
  const asOf = isIsoDate(input?.as_of) ? String(input.as_of) : "";
  setText(params, "as_of", asOf);
  const version = nullablePositiveInteger(input?.version);
  if (version !== null) params.set("version", String(version));
  const returnTo = safeSemanticReturnTo(input?.returnTo || "");
  setText(params, "returnTo", returnTo);
  return params.toString();
}

export function safeSemanticReturnTo(value) {
  let candidate = String(value || "").trim();
  for (let index = 0; index < 2; index += 1) {
    try {
      const decoded = decodeURIComponent(candidate);
      if (decoded === candidate) break;
      candidate = decoded;
    } catch {
      return "";
    }
  }
  if (!candidate || /[\\\u0000-\u001f\u007f]/.test(candidate) || candidate.startsWith("//")) return "";
  const queryIndex = candidate.indexOf("?");
  const pathname = queryIndex === -1 ? candidate : candidate.slice(0, queryIndex);
  if (pathname !== "/semantics" && pathname !== "/semantics/") return "";
  return candidate;
}

export function partitionSemanticRows(rows = []) {
  const partitions = { trusted: [], candidate: [], audit: [] };
  for (const row of rows) {
    const status = String(row?.status || "").toLowerCase();
    if (status === "confirmed") partitions.trusted.push(row);
    else if (status === "draft" || status === "ai_suggested") partitions.candidate.push(row);
    else if (status === "rejected" || status === "deprecated") partitions.audit.push(row);
  }
  return partitions;
}

export function confirmedRelatedAssetCount(bindings = []) {
  return bindings.reduce((count, binding) => count + (String(binding?.status || "").toLowerCase() === "confirmed" ? 1 : 0), 0);
}

export function resolveFormalDefinition(item) {
  const version = item?.effective_version;
  if (!version || version.status !== "confirmed") return null;
  return {
    versionId: version.id,
    versionNo: version.version_no,
    definition: typeof version.definition === "string" ? version.definition : "",
    effectiveFrom: version.effective_from,
    effectiveTo: version.effective_to ?? null
  };
}

export function markCurrentOnly(asOf, temporal) {
  const currentOnly = Boolean(isIsoDate(asOf) && !temporal);
  return { currentOnly, label: currentOnly ? CURRENT_ONLY_LABEL : "" };
}

export function groupCatalogItems(items = []) {
  const groups = new Map();
  for (const item of items) {
    const domain = typeof item?.business_domain === "string" && item.business_domain.trim()
      ? item.business_domain.trim()
      : "未分类";
    const existing = groups.get(domain) || [];
    existing.push(item);
    groups.set(domain, existing);
  }
  return Array.from(groups, ([domain, groupedItems]) => ({ domain, items: groupedItems }))
    .sort((left, right) => {
      if (left.domain === "未分类") return right.domain === "未分类" ? 0 : 1;
      if (right.domain === "未分类") return -1;
      return left.domain.localeCompare(right.domain, "zh-CN");
    });
}

export function redactSemanticReference(reference, semanticConceptId) {
  const entityType = String(reference?.entity_type || "");
  if (reference?.restricted === true) {
    return {
      entity_type: entityType,
      restricted: true,
      label: `${ENTITY_LABELS[entityType] || "数据资产"} · 受限`,
      destination: null
    };
  }
  const destination = resolveSemanticDestination(reference, semanticConceptId);
  return {
    entity_type: entityType,
    restricted: false,
    entity_id: nullablePositiveInteger(reference?.entity_id),
    display_name: cleanText(reference?.display_name),
    display_code: cleanText(reference?.display_code) || null,
    destination
  };
}

export function resolveSemanticDestination(reference, semanticConceptId) {
  if (!reference || reference.restricted === true) return { href: null, fallback: "尚无可导航详情" };
  const entityId = nullablePositiveInteger(reference.entity_id);
  const conceptId = nullablePositiveInteger(semanticConceptId);
  if (entityId === null || conceptId === null) return { href: null, fallback: "尚无可导航详情" };
  let pathname = "";
  const query = new URLSearchParams();
  switch (reference.entity_type) {
    case "target_field":
      pathname = `/fields/${entityId}/scenarios`;
      break;
    case "target_table":
      pathname = "/fields";
      query.set("targetTableId", String(entityId));
      break;
    case "mart_table":
      pathname = "/mart";
      query.set("martTableId", String(entityId));
      break;
    case "mart_field":
      pathname = "/mart";
      query.set("martFieldId", String(entityId));
      break;
    case "source_table":
      pathname = "/catalog";
      query.set("sourceTableId", String(entityId));
      break;
    case "source_field":
      pathname = "/catalog";
      query.set("sourceFieldId", String(entityId));
      break;
    case "scenario": {
      const targetFieldId = nullablePositiveInteger(reference.target_field_id);
      if (targetFieldId === null) return { href: null, fallback: "尚无可导航详情" };
      pathname = `/fields/${targetFieldId}/scenarios`;
      query.set("scenarioId", String(entityId));
      break;
    }
    case "knowledge_unit": {
      const documentId = nullablePositiveInteger(reference.document_id);
      if (documentId === null) return { href: null, fallback: "尚无可导航详情" };
      pathname = `/knowledge/documents/${documentId}`;
      query.set("unitId", String(entityId));
      break;
    }
    case "scenario_technical_lineage": {
      const targetFieldId = nullablePositiveInteger(reference.target_field_id);
      if (targetFieldId === null) return { href: null, fallback: "尚无可导航详情" };
      pathname = `/lineage/fields/${targetFieldId}`;
      break;
    }
    default:
      return { href: null, fallback: "尚无可导航详情" };
  }
  query.set("from", "semantics");
  query.set("semanticConceptId", String(conceptId));
  return { href: `${pathname}?${query.toString()}`, fallback: null };
}

function normalizeCatalogState(input = {}) {
  return {
    q: cleanText(input.q),
    type: CONCEPT_TYPES.has(String(input.type || "")) ? String(input.type) : "",
    domain: cleanText(input.domain),
    status: LIFECYCLE_STATUSES.has(String(input.status || "")) ? String(input.status) : "",
    owner: cleanText(input.owner),
    as_of: isIsoDate(input.as_of) ? String(input.as_of) : "",
    has_binding: normalizeNullableBoolean(input.has_binding),
    has_relation: normalizeNullableBoolean(input.has_relation),
    pending_review: normalizeNullableBoolean(input.pending_review),
    audit: input.audit === true,
    view: input.view === "table" ? "table" : "directory",
    page: positiveInteger(input.page, 1),
    page_size: boundedPageSize(input.page_size)
  };
}

function toSearchParams(input) {
  if (input instanceof URLSearchParams) return new URLSearchParams(input);
  if (typeof input === "string") return new URLSearchParams(input.startsWith("?") ? input.slice(1) : input);
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(input || {})) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  return params;
}

function cleanText(value) {
  return typeof value === "string" ? value.trim().slice(0, 500) : "";
}

function textParam(params, key) {
  return cleanText(params.get(key));
}

function enumParam(params, key, allowed) {
  const value = params.get(key) || "";
  return allowed.has(value) ? value : "";
}

function booleanParam(params, key) {
  const value = params.get(key);
  if (value === "1" || value === "true") return true;
  if (value === "0" || value === "false") return false;
  return null;
}

function normalizeNullableBoolean(value) {
  return value === true ? true : value === false ? false : null;
}

function dateParam(params, key) {
  const value = params.get(key) || "";
  return isIsoDate(value) ? value : "";
}

function isIsoDate(value) {
  const text = String(value || "");
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text)) return false;
  const [year, month, day] = text.split("-").map(Number);
  const date = new Date(Date.UTC(year, month - 1, day));
  return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}

function nullablePositiveInteger(value) {
  const number = typeof value === "number" ? value : Number(String(value || ""));
  return Number.isSafeInteger(number) && number > 0 ? number : null;
}

function positiveInteger(value, fallback) {
  return nullablePositiveInteger(value) ?? fallback;
}

function boundedPageSize(value) {
  const parsed = nullablePositiveInteger(value);
  return parsed !== null && parsed <= 100 ? parsed : DEFAULT_PAGE_SIZE;
}

function setText(params, key, value) {
  if (value) params.set(key, value);
}

function setBoolean(params, key, value) {
  if (value === true) params.set(key, "1");
  if (value === false) params.set(key, "0");
}
