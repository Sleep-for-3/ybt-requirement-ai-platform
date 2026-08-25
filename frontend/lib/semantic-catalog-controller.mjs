export function createCatalogState() {
  return {
    phase: "idle",
    requestKey: "",
    attempt: 0,
    page: null,
    error: null
  };
}

export function transitionCatalogState(state, event) {
  const current = state || createCatalogState();
  const requestKey = cleanRequestKey(event?.requestKey);

  if (event?.type === "scope-change") {
    if (!requestKey) return createCatalogState();
    if (current.requestKey === requestKey) return current;
    return loadingState(requestKey, 0);
  }

  if (event?.type === "begin") {
    if (!requestKey) return createCatalogState();
    return loadingState(requestKey, nonNegativeInteger(event.attempt, current.attempt));
  }

  if (event?.type === "retry") {
    if (!requestKey || requestKey !== current.requestKey) return current;
    return loadingState(requestKey, nonNegativeInteger(current.attempt, 0) + 1);
  }

  if (event?.type === "resolve" || event?.type === "reject") {
    const attempt = nonNegativeInteger(event.attempt, -1);
    if (
      current.phase !== "loading" ||
      requestKey !== current.requestKey ||
      attempt !== current.attempt
    ) return current;
    if (event.type === "resolve") {
      return {
        ...current,
        phase: "success",
        page: event.page ?? null,
        error: null
      };
    }
    return {
      ...current,
      phase: "error",
      page: null,
      error: event.error instanceof Error ? event.error : new Error("请求失败")
    };
  }

  return current;
}

export function catalogStateForScope(state, requestKey) {
  const currentKey = cleanRequestKey(requestKey);
  if (!currentKey) return createCatalogState();
  if (state?.requestKey === currentKey && state?.phase !== "idle") return state;
  return loadingState(currentKey, 0);
}

export function catalogPaginationModel(input = {}) {
  const pageSize = positiveInteger(input.pageSize, 50);
  const total = Math.max(0, finiteInteger(input.total, 0));
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const page = Math.min(pages, positiveInteger(input.page, 1));
  const atFirst = page <= 1;
  const atLast = page >= pages;
  return {
    page,
    pages,
    start: total ? (page - 1) * pageSize + 1 : 0,
    end: Math.min(total, page * pageSize),
    showEdges: pages > 5,
    first: { page: 1, disabled: atFirst },
    previous: { page: Math.max(1, page - 1), disabled: atFirst },
    next: { page: Math.min(pages, page + 1), disabled: atLast },
    last: { page: pages, disabled: atLast }
  };
}

function loadingState(requestKey, attempt) {
  return {
    phase: "loading",
    requestKey,
    attempt,
    page: null,
    error: null
  };
}

function cleanRequestKey(value) {
  return typeof value === "string" ? value : "";
}

function finiteInteger(value, fallback) {
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : fallback;
}

function nonNegativeInteger(value, fallback) {
  const parsed = finiteInteger(value, fallback);
  return parsed >= 0 ? parsed : fallback;
}

function positiveInteger(value, fallback) {
  const parsed = finiteInteger(value, fallback);
  return parsed > 0 ? parsed : fallback;
}
