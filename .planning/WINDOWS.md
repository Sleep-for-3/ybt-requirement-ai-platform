---
schema_version: 1
open_count: 4
waived_count: 0
fixed_count: 8
total_count: 12
last_updated: 2026-08-25T10:06:04.785Z
---

# Broken Windows Ledger

> Cross-phase defect register. With `workflow.windows_enforce` enabled, `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 09 | unrun-verify | backend/app/services/semantic/version_service.py |  | PostgreSQL row-lock concurrent confirmation staging qualification was not run; SQLite and portable-query tests passed | open |  | 2026-08-20T10:59:28.682Z |  |
| 2 | 09 | deviation | backend/app/services/semantic/__init__.py |  | Lazy builder export was required to preserve the existing semantic package import graph | fixed |  | 2026-08-22T16:55:16.015Z | 2026-08-22T16:56:02.619Z |
| 3 | 10 | deviation | backend/tests/test_productization.py | 165 | Windows ACL productization test reports null protection state on this host; unchanged from the 10-03 baseline. | open |  | 2026-08-23T09:59:42.617Z |  |
| 4 | 10 | deviation | backend/tests/test_productization.py | 195 | Interactive lifecycle-script productization test times out after input 0 on this host; unchanged from the 10-03 baseline. | open |  | 2026-08-23T09:59:43.455Z |  |
| 5 | 10 | deviation | backend/app/services/mapping/context_adapters.py |  | Metadata catalog compatibility required bounded current-task candidate profile evidence in the frozen Scenario technical projection without restoring a shared-fact fallback. | fixed |  | 2026-08-23T11:34:50.912Z | 2026-08-23T11:35:15.542Z |
| 6 | 11 | deviation | backend/tests/test_semantic_catalog_api.py |  | Preserved related concept ID before fixture session close to avoid DetachedInstanceError | fixed |  | 2026-08-25T05:59:11.554Z | 2026-08-25T05:59:42.594Z |
| 7 | 11 | deviation | backend/app/services/semantic/catalog_query_service.py |  | Aligned catalog unresolved-question aggregate with open assigned and answered lifecycle | fixed |  | 2026-08-25T05:59:12.444Z | 2026-08-25T05:59:43.598Z |
| 8 | 11 | deviation | frontend/app/semantics/[id]/page.tsx |  | Auto-fixed stale prior-project semantic shell render by binding state to full request identity. | fixed |  | 2026-08-25T06:35:43.480Z | 2026-08-25T06:36:22.797Z |
| 9 | 11 | deviation | frontend/lib/semantic-catalog-dom-contract.mjs |  | Runtime-only DOM contract uses tested import-site type suppressions because plan scope excludes a declaration peer. | fixed |  | 2026-08-25T06:35:44.651Z | 2026-08-25T06:36:23.711Z |
| 10 | 11 | unrun-verify | frontend/app/semantics/[id]/page.tsx |  | Live human viewport inspection is deferred to phase UI review; deterministic DOM and keyboard checks passed. | open |  | 2026-08-25T06:35:45.749Z |  |
| 11 | 11 | deviation | frontend/lib/semantic-catalog-dom-contract.mjs |  | Removed the duplicate incomplete DOM entity-label table so catalog and detail references share the exhaustive production source. | fixed |  | 2026-08-25T10:05:56.488Z | 2026-08-25T10:06:03.902Z |
| 12 | 11 | deviation | frontend/lib/semantic-entity-types.d.mts |  | Corrected the shared entity-label constant declaration syntax discovered by the frontend lint gate. | fixed |  | 2026-08-25T10:05:57.281Z | 2026-08-25T10:06:04.785Z |

````json
[
  {
    "id": 1,
    "kind": "unrun-verify",
    "phase": "09",
    "file": "backend/app/services/semantic/version_service.py",
    "line": null,
    "description": "PostgreSQL row-lock concurrent confirmation staging qualification was not run; SQLite and portable-query tests passed",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-20T10:59:28.682Z",
    "resolved_at": null
  },
  {
    "id": 2,
    "kind": "deviation",
    "phase": "09",
    "file": "backend/app/services/semantic/__init__.py",
    "line": null,
    "description": "Lazy builder export was required to preserve the existing semantic package import graph",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-08-22T16:55:16.015Z",
    "resolved_at": "2026-08-22T16:56:02.619Z"
  },
  {
    "id": 3,
    "kind": "deviation",
    "phase": "10",
    "file": "backend/tests/test_productization.py",
    "line": 165,
    "description": "Windows ACL productization test reports null protection state on this host; unchanged from the 10-03 baseline.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-23T09:59:42.617Z",
    "resolved_at": null
  },
  {
    "id": 4,
    "kind": "deviation",
    "phase": "10",
    "file": "backend/tests/test_productization.py",
    "line": 195,
    "description": "Interactive lifecycle-script productization test times out after input 0 on this host; unchanged from the 10-03 baseline.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-23T09:59:43.455Z",
    "resolved_at": null
  },
  {
    "id": 5,
    "kind": "deviation",
    "phase": "10",
    "file": "backend/app/services/mapping/context_adapters.py",
    "line": null,
    "description": "Metadata catalog compatibility required bounded current-task candidate profile evidence in the frozen Scenario technical projection without restoring a shared-fact fallback.",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-08-23T11:34:50.912Z",
    "resolved_at": "2026-08-23T11:35:15.542Z"
  },
  {
    "id": 6,
    "kind": "deviation",
    "phase": "11",
    "file": "backend/tests/test_semantic_catalog_api.py",
    "line": null,
    "description": "Preserved related concept ID before fixture session close to avoid DetachedInstanceError",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-08-25T05:59:11.554Z",
    "resolved_at": "2026-08-25T05:59:42.594Z"
  },
  {
    "id": 7,
    "kind": "deviation",
    "phase": "11",
    "file": "backend/app/services/semantic/catalog_query_service.py",
    "line": null,
    "description": "Aligned catalog unresolved-question aggregate with open assigned and answered lifecycle",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-08-25T05:59:12.444Z",
    "resolved_at": "2026-08-25T05:59:43.598Z"
  },
  {
    "id": 8,
    "kind": "deviation",
    "phase": "11",
    "file": "frontend/app/semantics/[id]/page.tsx",
    "line": null,
    "description": "Auto-fixed stale prior-project semantic shell render by binding state to full request identity.",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-08-25T06:35:43.480Z",
    "resolved_at": "2026-08-25T06:36:22.797Z"
  },
  {
    "id": 9,
    "kind": "deviation",
    "phase": "11",
    "file": "frontend/lib/semantic-catalog-dom-contract.mjs",
    "line": null,
    "description": "Runtime-only DOM contract uses tested import-site type suppressions because plan scope excludes a declaration peer.",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-08-25T06:35:44.651Z",
    "resolved_at": "2026-08-25T06:36:23.711Z"
  },
  {
    "id": 10,
    "kind": "unrun-verify",
    "phase": "11",
    "file": "frontend/app/semantics/[id]/page.tsx",
    "line": null,
    "description": "Live human viewport inspection is deferred to phase UI review; deterministic DOM and keyboard checks passed.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-08-25T06:35:45.749Z",
    "resolved_at": null
  },
  {
    "id": 11,
    "kind": "deviation",
    "phase": "11",
    "file": "frontend/lib/semantic-catalog-dom-contract.mjs",
    "line": null,
    "description": "Removed the duplicate incomplete DOM entity-label table so catalog and detail references share the exhaustive production source.",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-08-25T10:05:56.488Z",
    "resolved_at": "2026-08-25T10:06:03.902Z"
  },
  {
    "id": 12,
    "kind": "deviation",
    "phase": "11",
    "file": "frontend/lib/semantic-entity-types.d.mts",
    "line": null,
    "description": "Corrected the shared entity-label constant declaration syntax discovered by the frontend lint gate.",
    "status": "fixed",
    "reason": "",
    "recorded_at": "2026-08-25T10:05:57.281Z",
    "resolved_at": "2026-08-25T10:06:04.785Z"
  }
]
````
