import assert from "node:assert/strict";
import test from "node:test";

import {
  canViewNavigationAudience,
  detailHrefWithReturnTo,
  navigationAccessForProject,
  navigationTrailForPath,
  parentReturnHref
} from "../lib/navigation-contract.mjs";

test("technical navigation is scoped to the currently selected project", () => {
  const auth = {
    effective_project_permissions: {
      "101": ["catalog.search", "lineage.view"],
      "202": ["business.edit", "knowledge.search"]
    },
    institution_memberships: [{ institution_id: 1, role: "member", status: "active" }]
  };

  const technicalProject = navigationAccessForProject(auth, 101);
  const businessProject = navigationAccessForProject(auth, 202);

  assert.equal(canViewNavigationAudience("technical", technicalProject), true);
  assert.equal(canViewNavigationAudience("technical", businessProject), false);
  assert.equal(canViewNavigationAudience(undefined, businessProject), true);
});

test("administrator and cockpit navigation only use server-computed capabilities", () => {
  const admin = navigationAccessForProject({
    effective_project_permissions: {},
    institution_memberships: [{ institution_id: 1, role: "member", status: "active" }],
    capabilities: { can_view_admin: true, can_view_institution_cockpit: true }
  }, null);
  const roleNameOnly = navigationAccessForProject({
    effective_project_permissions: {},
    institution_memberships: [{ institution_id: 1, role: "institution_admin", status: "active" }]
  }, null);

  assert.equal(canViewNavigationAudience("admin", admin), true);
  assert.equal(canViewNavigationAudience("cockpit", admin), true);
  assert.equal(canViewNavigationAudience("admin", roleNameOnly), false);
  assert.equal(canViewNavigationAudience("cockpit", roleNameOnly), false);
});

test("named product roles receive menus only from backend capabilities and project permissions", () => {
  const scenarios = [
    ["Platform Administrator", { can_view_admin: true, can_view_institution_cockpit: true }, [], true, true],
    ["Institution Administrator", { can_view_admin: true, can_view_institution_cockpit: true }, [], true, true],
    ["Security Administrator", { can_view_admin: true, can_view_institution_cockpit: true }, [], true, true],
    ["Auditor", { can_view_admin: false, can_view_institution_cockpit: true }, ["audit.read"], false, true],
    ["Project Manager", { can_view_admin: false, can_view_institution_cockpit: false }, ["project.manage"], false, false],
    ["Business Analyst", { can_view_admin: false, can_view_institution_cockpit: false }, ["business.edit"], false, false],
    ["Technical Analyst", { can_view_admin: false, can_view_institution_cockpit: false }, ["technical.edit"], false, false],
    ["Member", { can_view_admin: false, can_view_institution_cockpit: false }, [], false, false]
  ];
  for (const [name, capabilities, permissions, expectedAdmin, expectedCockpit] of scenarios) {
    const access = navigationAccessForProject({ capabilities, effective_project_permissions: { "7": permissions } }, 7);
    assert.equal(canViewNavigationAudience("admin", access), expectedAdmin, `${name} admin`);
    assert.equal(canViewNavigationAudience("cockpit", access), expectedCockpit, `${name} cockpit`);
  }
});

test("every production detail route has a deterministic business parent", () => {
  const routes = new Map([
    ["/datasources/8/catalog", "/datasources"],
    ["/deliverable-templates/3", "/deliverable-templates"],
    ["/deliverables/9", "/deliverables"],
    ["/evaluations/4", "/evaluations"],
    ["/fields/7/scenarios", "/fields"],
    ["/historical-calibers/5", "/historical-calibers"],
    ["/jobs/22", "/jobs"],
    ["/knowledge/documents/6", "/knowledge/documents"],
    ["/lineage/changes/10", "/lineage/changes"],
    ["/lineage/fields/11", "/lineage"],
    ["/lineage/impacts/12", "/lineage/changes"],
    ["/lineage/scripts/13", "/lineage/scripts"],
    ["/projects/14/dashboard", "/projects"],
    ["/projects/14/members", "/projects"],
    ["/projects/14/onboarding", "/projects"],
    ["/projects/14/readiness", "/projects"],
    ["/semantics/15", "/semantics"],
    ["/tasks/16", "/tasks"],
    ["/uat/findings/17", "/uat"],
    ["/uat/runs/18", "/uat"],
    ["/uat/suites/19", "/uat"]
  ]);

  for (const [path, expectedParent] of routes) {
    assert.equal(navigationTrailForPath(path).parentHref, expectedParent, path);
  }
});

test("admin pages have the canonical system-management hierarchy", () => {
  for (const path of ["/admin/institutions", "/admin/users", "/admin/permissions", "/admin/health"]) {
    const trail = navigationTrailForPath(path);
    assert.equal(trail.sectionHref, "/admin", path);
    assert.equal(trail.sectionLabel, "系统管理", path);
    assert.equal(trail.parentHref, "/admin", path);
  }
  assert.equal(navigationTrailForPath("/admin").parentHref, null);
});

test("work center is canonical and review task details preserve its journey", () => {
  assert.deepEqual(navigationTrailForPath("/work"), {
    parentHref: null,
    sectionHref: "/work",
    sectionLabel: "我的工作"
  });
  assert.equal(navigationTrailForPath("/review-tasks").sectionHref, "/review-tasks");
  assert.equal(navigationTrailForPath("/review-tasks").sectionLabel, "我的工作");
  const trail = navigationTrailForPath("/tasks/16", "from=work&returnTo=%2Fwork%3Fstatus%3Dreturned");
  assert.equal(trail.parentHref, "/work");
  assert.equal(trail.sectionHref, "/work");
  assert.equal(parentReturnHref(trail.parentHref, "from=work&returnTo=%2Fwork%3Fstatus%3Dreturned"), "/work?status=returned");
});

test("detail return links restore only a lawful parent list state", () => {
  assert.equal(
    parentReturnHref("/semantics", "returnTo=%2Fsemantics%3Fq%3Dloan%26page%3D3"),
    "/semantics?q=loan&page=3"
  );
  assert.equal(
    parentReturnHref("/semantics", "returnTo=https%3A%2F%2Fevil.example%2Fsteal&projectId=8&tab=evidence"),
    "/semantics?projectId=8"
  );
  assert.equal(
    parentReturnHref("/lineage/changes", "returnTo=%2Fadmin%2Fusers&as_of=2026-08-26"),
    "/lineage/changes?as_of=2026-08-26"
  );
});

test("list-to-detail links carry the complete list URL as return state", () => {
  assert.equal(
    detailHrefWithReturnTo("/jobs/22", "/jobs", "status=failed&page=4"),
    "/jobs/22?returnTo=%2Fjobs%3Fstatus%3Dfailed%26page%3D4"
  );
  assert.equal(
    detailHrefWithReturnTo("/datasources/8/catalog?projectId=3", "/datasources", "sort=name"),
    "/datasources/8/catalog?projectId=3&returnTo=%2Fdatasources%3Fsort%3Dname"
  );
  assert.equal(detailHrefWithReturnTo("/tasks/16", "/review-tasks", "page=2"), "/tasks/16");
});

test("resources has explicit list parents and no dependency on browser history", () => {
  const lists=["/knowledge","/knowledge/ask","/knowledge/search","/knowledge/documents","/datasources","/catalog","/business-systems","/mart","/historical-calibers","/templates","/fields","/traceability-templates","/resources/architecture","/resources/import","/resources/reverse-requirements"];
  assert.equal(navigationTrailForPath("/resources").parentHref,null);
  for(const path of lists){
    const trail=navigationTrailForPath(path);
    assert.equal(trail.parentHref,"/resources",path);
    assert.equal(trail.sectionHref,"/resources",path);
  }
  assert.equal(navigationTrailForPath("/knowledge/documents/7").parentHref,"/knowledge/documents");
  assert.equal(navigationTrailForPath("/datasources/4/catalog").parentHref,"/datasources");
  const link=detailHrefWithReturnTo("/knowledge/documents/7","/knowledge/documents","projectId=1&q=policy");
  assert.equal(parentReturnHref("/knowledge/documents",new URL(link,"http://local").search),"/knowledge/documents?projectId=1&q=policy");
  assert.equal(parentReturnHref("/resources","projectId=1&returnTo=%2Fworkspace"),"/resources?projectId=1");
});
