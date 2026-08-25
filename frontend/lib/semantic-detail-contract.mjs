import {
  restrictedSemanticEntityLabel,
  semanticEntityLabel
} from "./semantic-entity-types.mjs";

const LOCAL_ORIGIN = "http://semantic-catalog.local";
const LINEAGE_PATH = "/lineage";
const LINEAGE_SELECTORS = new Set(["scenarioTechnicalLineageId", "nodeId"]);
const LINEAGE_QUERY_KEYS = new Set([...LINEAGE_SELECTORS, "from", "semanticConceptId"]);
const APPROVED_DESTINATIONS = Object.freeze([
  { path: "/fields", descendants: true },
  { path: "/mart", descendants: false },
  { path: "/catalog", descendants: false },
  { path: "/knowledge/documents", descendants: true },
  { path: "/lineage/fields", descendants: true },
  { path: "/semantics", descendants: true },
  { path: "/tasks", descendants: true },
  { path: "/review-tasks", descendants: false }
]);

export function lawfulSemanticDetailHref(value, semanticConceptId) {
  const href = typeof value === "string" ? value : "";
  if (!href.startsWith("/") || href.startsWith("//") || /[\\\u0000-\u001f\u007f]/.test(href)) return null;
  try {
    decodeURIComponent(href);
  } catch {
    return null;
  }

  let parsed;
  try {
    parsed = new URL(href, LOCAL_ORIGIN);
  } catch {
    return null;
  }
  if (parsed.origin !== LOCAL_ORIGIN || parsed.hash) return null;
  if (parsed.pathname === LINEAGE_PATH) {
    return lawfulLineageQuery(parsed, semanticConceptId) ? href : null;
  }
  return APPROVED_DESTINATIONS.some(({ path, descendants }) => (
    parsed.pathname === path || (descendants && parsed.pathname.startsWith(`${path}/`))
  )) ? href : null;
}

export function semanticDetailReferenceModel(reference, semanticConceptId) {
  const entityType = typeof reference?.entity_type === "string" ? reference.entity_type : "";
  if (reference?.restricted === true) {
    return {
      entity_type: entityType,
      restricted: true,
      label: restrictedSemanticEntityLabel(entityType)
    };
  }

  const displayName = cleanDisplayText(reference?.display_name) || semanticEntityLabel(entityType);
  const displayCode = cleanDisplayText(reference?.display_code);
  return {
    entity_type: entityType,
    restricted: false,
    label: displayCode ? `${displayName} · ${displayCode}` : displayName,
    href: lawfulSemanticDetailHref(reference?.href, semanticConceptId),
    fallback: "尚无可导航详情"
  };
}

export function conflictSourceCollectionModel(conflictKey, sources = [], expanded = false) {
  const normalized = Array.isArray(sources) ? sources.map((source) => ({
    source_type: cleanDisplayText(source?.source_type),
    source_id: positiveInteger(source?.source_id),
    summary: typeof source?.summary === "string" ? source.summary : "",
    authority: cleanDisplayText(source?.authority) || null
  })) : [];
  const isExpanded = expanded === true;
  return {
    id: `semantic-conflict-sources-${stableIdSegment(conflictKey)}`,
    hasSources: normalized.length > 0,
    expanded: isExpanded,
    remainingCount: Math.max(0, normalized.length - 2),
    visibleSources: isExpanded ? normalized : normalized.slice(0, 2)
  };
}

export function boundedDisclosureModel({ scope, type, id, text, lines = 6, expanded = false } = {}) {
  const fullText = typeof text === "string" ? text : "";
  const boundedLines = lines === 3 ? 3 : 6;
  const characterLimit = boundedLines * 80;
  const hasText = fullText.trim().length > 0;
  const isLong = hasText && (fullText.length > characterLimit || fullText.split(/\r?\n/).length > boundedLines);
  const baseId = `semantic-${stableIdSegment(scope)}-${stableIdSegment(type)}-${stableIdSegment(id)}`;
  const isExpanded = isLong && expanded === true;
  return {
    controlId: `${baseId}-control`,
    panelId: `${baseId}-panel`,
    hasText,
    isLong,
    lines: boundedLines,
    ariaExpanded: isExpanded,
    fullText,
    visibleText: isLong && !isExpanded ? `${fullText.slice(0, characterLimit)}…` : fullText
  };
}

function lawfulLineageQuery(parsed, semanticConceptId) {
  const entries = [...parsed.searchParams.entries()];
  if (entries.length !== 3) return false;
  if (entries.some(([key]) => !LINEAGE_QUERY_KEYS.has(key))) return false;

  const selectors = entries.filter(([key]) => LINEAGE_SELECTORS.has(key));
  const from = entries.filter(([key]) => key === "from");
  const concepts = entries.filter(([key]) => key === "semanticConceptId");
  if (selectors.length !== 1 || from.length !== 1 || concepts.length !== 1) return false;
  if (!selectors[0][1] || from[0][1] !== "semantics") return false;

  const conceptId = positiveInteger(semanticConceptId);
  return conceptId !== null && concepts[0][1] === String(conceptId);
}

function cleanDisplayText(value) {
  return typeof value === "string" ? value.trim() : "";
}

function stableIdSegment(value) {
  const text = String(value ?? "unknown");
  return encodeURIComponent(text).replaceAll("%", "_") || "unknown";
}

function positiveInteger(value) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}
