---
schema_version: 1
open_count: 3
waived_count: 0
fixed_count: 4
total_count: 7
last_updated: 2026-08-25T05:59:43.598Z
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
  }
]
````
