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

test("only active institution administrators receive administrator navigation", () => {
  const admin = navigationAccessForProject({
    effective_project_permissions: {},
    institution_memberships: [{ institution_id: 1, role: "institution_admin", status: "active" }]
  }, null);
  const inactiveAdmin = navigationAccessForProject({
    effective_project_permissions: {},
    institution_memberships: [{ institution_id: 1, role: "security_admin", status: "inactive" }]
  }, null);

  assert.equal(canViewNavigationAudience("admin", admin), true);
  assert.equal(canViewNavigationAudience("admin", inactiveAdmin), false);
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
