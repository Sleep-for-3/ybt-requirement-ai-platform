const TECHNICAL_PERMISSIONS = new Set([
  "catalog.manage",
  "catalog.search",
  "impact.review",
  "impact.view",
  "lineage.manage",
  "lineage.review",
  "lineage.view",
  "profile.request",
  "script.sync",
  "script.upload",
  "technical.edit",
  "technical.review"
]);

const SECTIONS = [
  ["/deliverable-templates", "交付模板"],
  ["/historical-calibers", "历史口径"],
  ["/knowledge", "知识与证据"],
  ["/review-tasks", "我的待办"],
  ["/datasources", "数据源"],
  ["/deliverables", "交付成果"],
  ["/evaluations", "RAG 评测"],
  ["/semantics", "监管语义"],
  ["/quality", "质量期望"],
  ["/questions", "待确认问题"],
  ["/projects", "项目"],
  ["/catalog", "数据目录"],
  ["/fields", "字段与口径"],
  ["/lineage", "技术血缘"],
  ["/tasks", "安全查询"],
  ["/jobs", "后台任务"],
  ["/mart", "监管集市"],
  ["/admin", "系统管理"],
  ["/uat", "UAT 验收"],
  ["/workspace", "需求工作台"]
];

const DETAIL_PARENTS = [
  [/^\/admin\/(institutions|users|permissions|health|system-health)$/, "/admin"],
  [/^\/datasources\/\d+\/catalog$/, "/datasources"],
  [/^\/deliverable-templates\/\d+$/, "/deliverable-templates"],
  [/^\/deliverables\/\d+$/, "/deliverables"],
  [/^\/evaluations\/\d+$/, "/evaluations"],
  [/^\/fields\/\d+\/scenarios$/, "/fields"],
  [/^\/historical-calibers\/\d+$/, "/historical-calibers"],
  [/^\/jobs\/\d+$/, "/jobs"],
  [/^\/knowledge\/documents\/\d+$/, "/knowledge/documents"],
  [/^\/lineage\/changes\/\d+$/, "/lineage/changes"],
  [/^\/lineage\/fields\/\d+$/, "/lineage"],
  [/^\/lineage\/impacts\/\d+$/, "/lineage/changes"],
  [/^\/lineage\/scripts\/\d+$/, "/lineage/scripts"],
  [/^\/projects\/\d+\/(dashboard|members|onboarding|readiness)$/, "/projects"],
  [/^\/semantics\/\d+$/, "/semantics"],
  [/^\/tasks\/\d+$/, "/tasks"],
  [/^\/uat\/(findings|runs|suites)\/\d+$/, "/uat"]
];

export function navigationAccessForProject(auth, projectId) {
  const permissions = projectId
    ? auth?.effective_project_permissions?.[String(projectId)] || []
    : [];
  return {
    isAdmin: Boolean(auth?.capabilities?.can_view_admin),
    canViewCockpit: Boolean(auth?.capabilities?.can_view_institution_cockpit),
    isTechnical: permissions.some((permission) => TECHNICAL_PERMISSIONS.has(permission))
  };
}

export function canViewNavigationAudience(audience, access) {
  if (!audience) return true;
  if (audience === "admin") return access.isAdmin;
  if (audience === "cockpit") return access.canViewCockpit;
  return access.isTechnical;
}

export function navigationTrailForPath(pathname) {
  const section = SECTIONS.find(([route]) => pathname === route || pathname.startsWith(`${route}/`));
  const parent = DETAIL_PARENTS.find(([pattern]) => pattern.test(pathname));
  return {
    parentHref: parent?.[1] || null,
    sectionHref: section?.[0] || null,
    sectionLabel: section?.[1] || null
  };
}

export function parentReturnHref(parentHref, queryString = "") {
  if (!parentHref) return null;
  const params = new URLSearchParams(queryString);
  const returnTo = params.get("returnTo");
  if (returnTo === parentHref || returnTo?.startsWith(`${parentHref}?`)) return returnTo;

  const scope = new URLSearchParams();
  for (const key of ["projectId", "as_of"]) {
    const value = params.get(key);
    if (value) scope.set(key, value);
  }
  const suffix = scope.toString();
  return `${parentHref}${suffix ? `?${suffix}` : ""}`;
}

export function detailHrefWithReturnTo(detailHref, listPath, listQuery = "") {
  const url = new URL(detailHref, "http://navigation.local");
  const trail = navigationTrailForPath(url.pathname);
  if (trail.parentHref !== listPath) return detailHref;

  const returnTo = `${listPath}${listQuery ? `?${listQuery}` : ""}`;
  url.searchParams.set("returnTo", returnTo);
  return `${url.pathname}${url.search}${url.hash}`;
}
