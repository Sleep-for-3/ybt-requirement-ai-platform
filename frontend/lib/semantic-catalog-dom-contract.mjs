import { createElement } from "react";

import { restrictedSemanticEntityLabel } from "./semantic-entity-types.mjs";

export const DETAIL_TAB_IDS = Object.freeze([
  "overview", "bindings", "relations", "evidence", "lineage", "governance", "versions"
]);

export function tabId(tab) { return `semantic-tab-${validTab(tab)}`; }
export function panelId(tab) { return `semantic-panel-${validTab(tab)}`; }

export function tabContractAttributes(tab, activeTab) {
  const valid = validTab(tab);
  const selected = valid === validTab(activeTab);
  return {
    id: tabId(valid),
    role: "tab",
    "aria-selected": selected,
    "aria-controls": panelId(valid),
    tabIndex: selected ? 0 : -1
  };
}

export function panelContractAttributes(tab) {
  const valid = validTab(tab);
  return {
    id: panelId(valid),
    role: "tabpanel",
    "aria-labelledby": tabId(valid),
    tabIndex: 0
  };
}

export function moveTabContract(state, key) {
  const current = DETAIL_TAB_IDS.indexOf(validTab(state?.focused || state?.selected));
  let next = current;
  if (key === "ArrowRight") next = (current + 1) % DETAIL_TAB_IDS.length;
  else if (key === "ArrowLeft") next = (current - 1 + DETAIL_TAB_IDS.length) % DETAIL_TAB_IDS.length;
  else if (key === "Home") next = 0;
  else if (key === "End") next = DETAIL_TAB_IDS.length - 1;
  else return { selected: validTab(state?.selected), focused: validTab(state?.focused || state?.selected) };
  return { selected: DETAIL_TAB_IDS[next], focused: DETAIL_TAB_IDS[next] };
}

export function retryAccessibleName(label) { return `重试加载${cleanLabel(label)}`; }
export function asyncRegionContractAttributes(kind, label) {
  if (kind === "loading") return { role: "status", "aria-busy": true, "aria-label": `正在加载${cleanLabel(label)}` };
  if (kind === "forbidden" || kind === "error") return { role: "alert" };
  return { "aria-live": "polite" };
}

export function transitionRetryContract(state, event) {
  const objectLabel = cleanLabel(state?.objectLabel);
  const attempt = Number(state?.attempt || 0);
  if (event === "retry") return { phase: "loading", attempt: attempt + 1, objectLabel, accessibleName: retryAccessibleName(objectLabel) };
  if (event === "resolve") return { phase: "success", attempt, objectLabel, accessibleName: "" };
  if (event === "reject") return { phase: "error", attempt, objectLabel, accessibleName: retryAccessibleName(objectLabel) };
  return { ...state, objectLabel };
}

export function transitionVersionDisclosureContract(expandedVersion, requestedVersion) {
  const requested = positiveInteger(requestedVersion);
  const expanded = positiveInteger(expandedVersion);
  const next = requested !== null && requested !== expanded ? requested : null;
  return { expandedVersion: next, ariaExpanded: next !== null };
}

export function restrictedReferenceContract(reference) {
  const entityType = String(reference?.entity_type || "");
  return {
    entity_type: entityType,
    restricted: true,
    label: restrictedSemanticEntityLabel(entityType)
  };
}

export function buildChainTextContract(chain, meta = {}) {
  const references = [chain?.concept, ...(chain?.targets || []), ...(chain?.marts || []), ...(chain?.sources || [])].filter(Boolean);
  const items = references.map((reference) => reference?.restricted === true
    ? restrictedReferenceContract(reference).label
    : cleanLabel(reference?.display_code ? `${reference.display_name} · ${reference.display_code}` : reference?.display_name));
  const overflow = Math.max(0, Number(meta?.overflow || 0));
  return { items, overflowText: overflow ? `另有 ${overflow} 个节点因上限未展示。` : "" };
}

export function SemanticContractFixture(input = {}) {
  const label = cleanLabel(input.label);
  switch (input.kind) {
    case "loading":
      return createElement("section", asyncRegionContractAttributes("loading", label), `正在加载${label}`);
    case "forbidden":
      return createElement("section", asyncRegionContractAttributes("forbidden", label), createElement("h2", null, `无权查看${label}`), createElement("p", null, "概览仍可继续查看。"));
    case "error":
      return createElement("section", asyncRegionContractAttributes("error", label), createElement("h2", null, `${label}加载失败`), createElement("button", { "aria-label": retryAccessibleName(label), type: "button" }, retryAccessibleName(label)));
    case "candidate":
      return createElement("section", { "aria-label": label }, createElement("h2", null, "待治理候选"), createElement("p", null, "发现候选关联，但尚未经过人工确认。"));
    case "conflict":
      return createElement("section", { role: "alert" }, createElement("h2", null, "高权威事实存在冲突"), createElement("p", null, label), createElement("p", null, "系统未选择任何胜出方。"));
    case "pending-review":
      return createElement("div", null, createElement("span", null, "已确认"), createElement("span", { role: "status" }, "待评审"));
    case "audit-version":
      return createElement("article", null, createElement("span", null, label), createElement("span", null, "非当前事实"));
    case "restricted": {
      const model = restrictedReferenceContract(input.reference);
      return createElement("span", null, model.label);
    }
    case "tabs": {
      const active = validTab(input.activeTab);
      return createElement("div", null,
        createElement("div", { role: "tablist", "aria-label": "语义详情区域" }, ...DETAIL_TAB_IDS.map((tab) => createElement("button", { ...tabContractAttributes(tab, active), key: tab, type: "button" }, tab))),
        createElement("section", panelContractAttributes(active), active)
      );
    }
    case "long-text":
      return createElement("p", { className: "whitespace-pre-wrap break-words" }, label);
    default:
      return createElement("section", { "aria-live": "polite" }, label);
  }
}

function validTab(value) { return DETAIL_TAB_IDS.includes(String(value || "")) ? String(value) : "overview"; }
function cleanLabel(value) { return typeof value === "string" ? value : ""; }
function positiveInteger(value) { const parsed = Number(value); return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null; }
