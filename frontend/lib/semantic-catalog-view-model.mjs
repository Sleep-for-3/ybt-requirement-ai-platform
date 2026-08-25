import {
  restrictedSemanticEntityLabel,
  semanticEntityLabel
} from "./semantic-entity-types.mjs";

const CONCEPT_TYPES = new Set([
  "business_term",
  "metric",
  "dimension",
  "code_set",
  "business_rule",
  "regulatory_rule"
]);
const LIFECYCLE_STATUSES = new Set(["draft", "ai_suggested", "confirmed", "rejected", "deprecated"]);
const AUDIT_STATUSES = new Set(["rejected", "deprecated"]);
const DEFAULT_AUDIT_STATUS = "rejected";
const UNCATEGORIZED_DOMAIN = "__uncategorized__";
const DETAIL_TABS = new Set(["overview", "bindings", "relations", "evidence", "lineage", "governance", "versions"]);
const DEFAULT_PAGE_SIZE = 50;
const CURRENT_ONLY_LABEL = "当前状态，不代表该历史日期";

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
  const next = { ...current, ...changes, page: resetPage ? 1 : changes.page ?? current.page };
  if (
    changes.audit === false &&
    !Object.prototype.hasOwnProperty.call(changes, "status") &&
    AUDIT_STATUSES.has(String(current?.status || ""))
  ) next.status = "";
  if (Object.prototype.hasOwnProperty.call(changes, "status")) {
    const status = String(changes.status || "");
    if (AUDIT_STATUSES.has(status)) next.audit = true;
  }
  return normalizeCatalogState(next);
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

export function buildCatalogApiQuery(input) {
  const state = normalizeCatalogState(input);
  const params = new URLSearchParams();
  params.set("mode", state.audit ? "audit" : "candidate");
  setText(params, "q", state.q);
  setText(params, "type", state.type);
  setText(params, "domain", state.domain);
  setText(params, "status", state.status);
  setText(params, "owner", state.owner);
  setText(params, "as_of", state.as_of);
  if (state.has_binding !== null) params.set("has_binding", String(state.has_binding));
  if (state.has_relation !== null) params.set("has_relation", String(state.has_relation));
  if (state.pending_review !== null) params.set("pending_review", String(state.pending_review));
  if (state.audit) params.set("audit", "true");
  params.set("page", String(state.page));
  params.set("page_size", String(state.page_size));
  return params.toString();
}

export function commitCatalogSearch(current, draft) {
  return applyCatalogQueryChange(current, { q: cleanText(draft) });
}

export function createCatalogRequestCoordinator() {
  let active = null;
  return {
    begin(key) {
      active?.controller.abort();
      const controller = new AbortController();
      const request = {
        key: String(key),
        controller,
        signal: controller.signal,
        accept: () => active === request && !controller.signal.aborted
      };
      active = request;
      return request;
    },
    clear() {
      active?.controller.abort();
      active = null;
    }
  };
}

export function catalogResponseKind(input) {
  if (input?.phase === "loading") return "loading";
  if (input?.phase === "error") return Number(input?.error?.status) === 403 ? "forbidden" : "error";
  if (input?.phase === "success") return Number(input?.page?.total) === 0 ? "empty" : "populated";
  return "idle";
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

export function returnToCurrentDetail(input) {
  return {
    ...parseDetailQuery(serializeDetailQuery(input || {})),
    as_of: "",
    version: null
  };
}

export function detailAuditRequested(input) {
  const returnTo = safeSemanticReturnTo(input?.returnTo || "");
  if (!returnTo) return false;
  const queryIndex = returnTo.indexOf("?");
  if (queryIndex === -1) return false;
  return booleanParam(new URLSearchParams(returnTo.slice(queryIndex + 1)), "audit") === true;
}

export function buildDetailApiQuery(input, options = {}) {
  const state = parseDetailQuery(serializeDetailQuery(input || {}));
  const params = new URLSearchParams();
  setText(params, "as_of", state.as_of);
  if (options.audit === true || detailAuditRequested(state)) params.set("audit", "true");
  return params.toString();
}

export function buildDetailRequestKey(projectId, conceptId, region, input, options = {}) {
  return [
    positiveInteger(projectId, 0),
    positiveInteger(conceptId, 0),
    DETAIL_TABS.has(String(region || "")) || region === "shell" ? String(region) : "overview",
    buildDetailApiQuery(input, options)
  ].join(":");
}

export function detailShellResponseKind(input, currentRequestKey = "") {
  if (currentRequestKey && input?.phase !== "idle" && input?.requestKey !== currentRequestKey) return "loading";
  if (input?.phase === "loading") return "loading";
  if (input?.phase === "success") return "success";
  if (input?.phase === "error") {
    const status = Number(input?.error?.status);
    if (status === 404) return "not-found";
    if (status === 403) return "forbidden";
    if (status === 409) return "conflict";
    return "error";
  }
  return "idle";
}

export function createDetailRegionState() {
  return { phase: "idle", attempt: 0, requestKey: "", data: null, error: null };
}

export function transitionDetailRegion(state, event) {
  const current = state || createDetailRegionState();
  if (event?.type === "retry") {
    return { ...createDetailRegionState(), attempt: Number(current.attempt || 0) + 1 };
  }
  if (event?.type === "load") {
    return {
      phase: "loading",
      attempt: Number(current.attempt || 0),
      requestKey: String(event.requestKey || ""),
      data: null,
      error: null
    };
  }
  if ((event?.type === "resolve" || event?.type === "reject") && event.requestKey !== current.requestKey) {
    return current;
  }
  if (event?.type === "resolve") {
    return { ...current, phase: "success", data: event.data ?? null, error: null };
  }
  if (event?.type === "reject") {
    return { ...current, phase: "error", data: null, error: event.error || new Error("请求失败") };
  }
  return current;
}

export function detailRegionHasContent(data) {
  if (!data || typeof data !== "object") return false;
  if (typeof data.lifecycle_status === "string") return true;
  const contentKeys = [
    "confirmed", "candidates", "audit", "chains", "verified", "open_questions",
    "conflicts", "audit_events", "evidence", "knowledge"
  ];
  return contentKeys.some((key) => nestedCollectionHasItems(data[key]));
}

export function detailRegionResponseKind(input) {
  if (input?.phase === "loading") return "loading";
  if (input?.phase === "error") return Number(input?.error?.status) === 403 ? "forbidden" : "error";
  if (input?.phase === "success") return detailRegionHasContent(input.data) ? "success-populated" : "success-empty";
  return "idle";
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

export function sortSemanticVersions(versions = []) {
  return [...versions].sort((left, right) => {
    const byDate = String(left?.effective_from || "").localeCompare(String(right?.effective_from || ""));
    if (byDate) return byDate;
    const byVersion = Number(left?.version_no || 0) - Number(right?.version_no || 0);
    if (byVersion) return byVersion;
    return Number(left?.id || 0) - Number(right?.id || 0);
  });
}

export function isSemanticQuestionOpen(question) {
  return ["open", "assigned", "answered"].includes(String(question?.question_status || "").toLowerCase());
}

export function semanticReferenceLabel(reference) {
  const entityType = String(reference?.entity_type || "");
  if (reference?.restricted === true) return restrictedSemanticEntityLabel(entityType);
  const name = cleanText(reference?.display_name) || semanticEntityLabel(entityType);
  const code = cleanText(reference?.display_code);
  return code ? `${name} · ${code}` : name;
}

export function catalogDomainLabel(value) {
  const domain = cleanText(value);
  return domain === UNCATEGORIZED_DOMAIN ? "未分类" : domain;
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
      label: restrictedSemanticEntityLabel(entityType),
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
  let status = LIFECYCLE_STATUSES.has(String(input.status || "")) ? String(input.status) : "";
  let audit = input.audit === true;
  if (audit && !AUDIT_STATUSES.has(status)) status = DEFAULT_AUDIT_STATUS;
  else if (!audit && AUDIT_STATUSES.has(status)) audit = true;
  return {
    q: cleanText(input.q),
    type: CONCEPT_TYPES.has(String(input.type || "")) ? String(input.type) : "",
    domain: cleanText(input.domain),
    status,
    owner: cleanText(input.owner),
    as_of: isIsoDate(input.as_of) ? String(input.as_of) : "",
    has_binding: normalizeNullableBoolean(input.has_binding),
    has_relation: normalizeNullableBoolean(input.has_relation),
    pending_review: normalizeNullableBoolean(input.pending_review),
    audit,
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

function nestedCollectionHasItems(value) {
  if (Array.isArray(value)) return value.length > 0;
  if (!value || typeof value !== "object") return false;
  return Object.values(value).some((item) => nestedCollectionHasItems(item));
}
